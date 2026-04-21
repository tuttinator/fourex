"""Phase 5 cross-front-door integration test.

Acceptance criterion from ``plans/sprites-production-tech.md``:

    Cross-front-door integration test: human and MCP agent complete the
    same research with identical timing.

Strategy — seat alice (REST) and bob (MCP) in one game. Pre-seed each
with a city producing science and a matching science stockpile. Both
players set ``masonry`` (cost 10) as their active research: alice via
the REST ``/actions`` endpoint, bob via the MCP ``submit_actions``
tool. We then tick turns with empty submissions and, on every turn,
read the game state via *both* surfaces and assert they agree byte-for-
byte on each caller's own ``research`` block and on the turn on which
``masonry`` moves into ``completed``. ``get_tech_tree`` is also checked
against the REST state to guarantee the MCP read-only tool stays in
sync with the resolver.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.api.persistent_game_controller import (
    get_persistent_game_controller,
)
from backend.src.api.websocket import manager
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerAction,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
)
from backend.src.game.models import (
    TECH_TREE,
    City,
    Coord,
    ResourceBag,
    Terrain,
    Tile,
)
from backend.src.main import app
from backend.src.mcp_server.server import create_mcp_server

_GAME_PREFIX = "game"
_TECH_ID = "masonry"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mcp() -> Any:
    return create_mcp_server()


@pytest_asyncio.fixture
async def _clean_rows() -> None:
    await init_db()
    async with async_session_factory() as session:
        for table in (
            PlayerApiKey,
            GameSnapshot,
            TurnSnapshot,
            TurnAction,
            PlayerAction,
            GameTurn,
        ):
            await session.execute(
                delete(table).where(table.game_id.like(f"{_GAME_PREFIX}_%"))
            )
        await session.execute(delete(Game).where(Game.id.like(f"{_GAME_PREFIX}_%")))
        await session.commit()
    manager._by_game.clear()
    yield
    async with async_session_factory() as session:
        for table in (
            PlayerApiKey,
            GameSnapshot,
            TurnSnapshot,
            TurnAction,
            PlayerAction,
            GameTurn,
        ):
            await session.execute(
                delete(table).where(table.game_id.like(f"{_GAME_PREFIX}_%"))
            )
        await session.execute(delete(Game).where(Game.id.like(f"{_GAME_PREFIX}_%")))
        await session.commit()
    manager._by_game.clear()


async def _mcp_call(mcp: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(tool, args)
    if isinstance(result, tuple):
        return result[1]  # type: ignore[return-value]
    return json.loads(result[0].text)  # type: ignore[union-attr]


def _rest_get_state(client: TestClient, game_id: str, api_key: str) -> dict[str, Any]:
    resp = client.get(
        f"/api/v1/state?game_id={game_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _seed_research_fixture(game_id: str) -> None:
    """Install a plains grid with one science-producing city per player
    and a science stockpile priced so masonry takes exactly two turns
    to complete (cost 10; start with 8, plus 1/turn base income)."""
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        assert state is not None

        new_tiles: list[Tile] = []
        tile_id = 0
        for y in range(10):
            for x in range(10):
                new_tiles.append(
                    Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.PLAINS)
                )
                tile_id += 1
        state.tiles = new_tiles
        state.map_width = 10
        state.map_height = 10
        state.units.clear()
        state.cities.clear()

        alice_city = City(id=1, owner="alice", loc=Coord(x=3, y=3))
        bob_city = City(id=2, owner="bob", loc=Coord(x=7, y=7))
        state.cities[1] = alice_city
        state.cities[2] = bob_city
        state.next_city_id = 3
        for cid, city in state.cities.items():
            tile = state.get_tile(city.loc)
            assert tile is not None
            tile.city_id = cid
            tile.owner = city.owner

        # Science-only stockpile — other fields don't matter for this test.
        # 8 + 1/turn × 2 turns = 10 = cost of masonry. Completion lands on
        # the second resolution.
        for p in ("alice", "bob"):
            state.stockpiles[p] = ResourceBag(science=8)

        await controller.repo.update_game_state(game_id, state)
        await session.commit()


async def _alice_rest_submit(
    client: TestClient, game_id: str, api_key: str, actions: list[dict[str, Any]]
) -> None:
    resp = client.post(
        f"/api/v1/actions?game_id={game_id}",
        json=actions,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text


async def _bob_mcp_submit(
    mcp: Any, api_key: str, actions: list[dict[str, Any]]
) -> dict[str, Any]:
    return await _mcp_call(
        mcp, "submit_actions", {"api_key": api_key, "actions": actions}
    )


def _rest_research(rest_state: dict[str, Any], player: str) -> dict[str, Any]:
    return rest_state["research"][player]


def _mcp_research(mcp_state: dict[str, Any], player: str) -> dict[str, Any]:
    return mcp_state["state"]["research"][player]


@pytest.mark.asyncio
async def test_rest_and_mcp_complete_same_research_with_identical_timing(
    client: TestClient, mcp: Any, _clean_rows: None
) -> None:
    resp = await _mcp_call(mcp, "create_game", {"players": ["alice", "bob"]})
    assert "error" not in resp, resp
    game_id = resp["game_id"]
    alice_key = resp["api_keys"]["alice"]
    bob_key = resp["api_keys"]["bob"]

    await _seed_research_fixture(game_id)

    cost = TECH_TREE[_TECH_ID].cost_science
    assert cost == 10

    # Before anyone selects a tech, both front doors agree that nobody
    # is researching anything and that the full starter set is already
    # completed.
    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state = await _mcp_call(mcp, "get_game_state", {"api_key": alice_key})
    alice_rest = _rest_research(rest_state, "alice")
    alice_mcp = _mcp_research(mcp_state, "alice")
    assert alice_rest == alice_mcp
    assert alice_rest["active"] is None
    assert "bronze_working" in alice_rest["completed"]
    # Redaction — alice does not see bob's research through either door.
    assert "bob" not in rest_state["research"]
    assert "bob" not in mcp_state["state"]["research"]

    # get_tech_tree agrees with the REST snapshot from the first byte.
    tt = await _mcp_call(mcp, "get_tech_tree", {"api_key": alice_key})
    assert tt["research"] == alice_rest
    assert _TECH_ID in tt["tech_tree"]
    assert tt["tech_tree"][_TECH_ID]["cost_science"] == cost

    # Turn 1: alice (REST) and bob (MCP) both pick masonry. Submitting
    # both in the same turn triggers resolution after the second submit.
    await _alice_rest_submit(
        client,
        game_id,
        alice_key,
        [{"type": "SET_ACTIVE_RESEARCH", "tech_id": _TECH_ID}],
    )
    bob_resp = await _bob_mcp_submit(
        mcp, bob_key, [{"type": "SET_ACTIVE_RESEARCH", "tech_id": _TECH_ID}]
    )
    assert bob_resp.get("turn_resolved") is True, bob_resp

    # After turn 1 each player's city has produced 1 science. The prior
    # stockpile (8) plus this turn's income (1) is 9 — one short of
    # masonry's cost. No completion yet, both players share identical
    # progress, and each front door reports it identically.
    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state_alice = await _mcp_call(mcp, "get_game_state", {"api_key": alice_key})
    mcp_state_bob = await _mcp_call(mcp, "get_game_state", {"api_key": bob_key})

    alice_rest = _rest_research(rest_state, "alice")
    alice_mcp = _mcp_research(mcp_state_alice, "alice")
    bob_mcp = _mcp_research(mcp_state_bob, "bob")
    assert alice_rest == alice_mcp
    assert alice_rest["active"] == _TECH_ID
    assert alice_rest["progress"] == 9
    assert _TECH_ID not in alice_rest["completed"]
    # Bob, driving MCP only, has identical progress to REST-driven alice —
    # the two front doors produce equivalent state.
    assert bob_mcp["active"] == _TECH_ID
    assert bob_mcp["progress"] == 9
    assert _TECH_ID not in bob_mcp["completed"]

    # Turn 2: empty submissions from both. 9 + 1 = 10 = cost → completion
    # lands on this turn for both players simultaneously.
    await _alice_rest_submit(client, game_id, alice_key, [])
    bob_resp = await _bob_mcp_submit(mcp, bob_key, [])
    assert bob_resp.get("turn_resolved") is True, bob_resp

    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state_alice = await _mcp_call(mcp, "get_game_state", {"api_key": alice_key})
    mcp_state_bob = await _mcp_call(mcp, "get_game_state", {"api_key": bob_key})

    alice_rest = _rest_research(rest_state, "alice")
    alice_mcp = _mcp_research(mcp_state_alice, "alice")
    bob_mcp = _mcp_research(mcp_state_bob, "bob")

    # Byte-for-byte parity between REST and MCP on alice's own research.
    assert alice_rest == alice_mcp
    # Both players completed masonry on the same turn.
    assert _TECH_ID in alice_rest["completed"]
    assert alice_rest["active"] is None
    assert alice_rest["progress"] == 0
    assert _TECH_ID in bob_mcp["completed"]
    assert bob_mcp["active"] is None
    assert bob_mcp["progress"] == 0

    # get_tech_tree still matches the REST snapshot after completion.
    tt = await _mcp_call(mcp, "get_tech_tree", {"api_key": alice_key})
    assert tt["research"] == alice_rest
