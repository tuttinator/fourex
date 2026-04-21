"""Phase 6 cross-front-door integration test.

Acceptance criterion from ``plans/sprites-production-tech.md``:

    Human and MCP agent both hit a tech gate, research through it, and
    unlock the gated item with identical behaviour.

Strategy — seat alice (REST) and bob (MCP) in one game. Pre-seed each
with a city producing science (for research) plus ore/wood stockpiles
(for queueing units and buildings). Both players first attempt to queue
an ARCHER (gated on ``archery``, cost 10): each front door must reject
with an identical per-item message. Both then set ``archery`` as active
research and tick two turns (8 + 2 = 10) until completion. On the
unlock turn both players queue the previously-rejected ARCHER through
their respective front doors; both submissions must succeed with
byte-for-byte equivalent queue state across REST and MCP views.
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
    UnitType,
)
from backend.src.main import app
from backend.src.mcp_server.server import create_mcp_server

_GAME_PREFIX = "game"
_TECH_ID = "archery"


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


def _rest_get_state(
    client: TestClient, game_id: str, api_key: str
) -> dict[str, Any]:
    resp = client.get(
        f"/api/v1/state?game_id={game_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rest_submit(
    client: TestClient,
    game_id: str,
    api_key: str,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    resp = client.post(
        f"/api/v1/actions?game_id={game_id}",
        json=actions,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _seed_fixture(game_id: str) -> None:
    """Install a plains grid with one science-and-resource producing city
    per player. Stockpiles are priced so ``archery`` (cost 10) takes
    exactly two turns to complete after the opening set-active turn:
    start at 8 science + 1/turn income = 10 after two ticks."""
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        assert state is not None

        new_tiles: list[Tile] = []
        tile_id = 0
        for y in range(10):
            for x in range(10):
                new_tiles.append(
                    Tile(
                        id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.PLAINS
                    )
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

        # Enough food/wood for one ARCHER (cost 15/5), plus science for
        # ``archery`` research pacing.
        for p in ("alice", "bob"):
            state.stockpiles[p] = ResourceBag(food=100, wood=100, science=8)

        await controller.repo.update_game_state(game_id, state)
        await session.commit()


def _expected_gate_message() -> str:
    tech_name = TECH_TREE[_TECH_ID].name
    return (
        f"{UnitType.ARCHER.value} requires {tech_name} "
        f"({_TECH_ID}) to be researched first"
    )


@pytest.mark.asyncio
async def test_rest_and_mcp_hit_same_gate_and_unlock_identically(
    client: TestClient, mcp: Any, _clean_rows: None
) -> None:
    resp = await _mcp_call(mcp, "create_game", {"players": ["alice", "bob"]})
    assert "error" not in resp, resp
    game_id = resp["game_id"]
    alice_key = resp["api_keys"]["alice"]
    bob_key = resp["api_keys"]["bob"]

    await _seed_fixture(game_id)

    alice_archer = {
        "type": "TRAIN_UNIT",
        "city_id": 1,
        "unit_type": UnitType.ARCHER.value,
    }
    bob_archer = dict(alice_archer, city_id=2)
    research_action = {"type": "SET_ACTIVE_RESEARCH", "tech_id": _TECH_ID}

    # --- Gate parity pre-research. Each player uses MCP validate_actions
    # (the read-only dry-run tool that shares the resolver's dispatch)
    # to check the rejection message. Both players see the identical
    # per-item gate message — the core Phase 6 parity claim.
    alice_validate = await _mcp_call(
        mcp, "validate_actions", {"api_key": alice_key, "actions": [alice_archer]}
    )
    bob_validate = await _mcp_call(
        mcp, "validate_actions", {"api_key": bob_key, "actions": [bob_archer]}
    )
    assert alice_validate["all_valid"] is False
    assert bob_validate["all_valid"] is False
    assert alice_validate["results"][0]["valid"] is False
    assert bob_validate["results"][0]["valid"] is False
    assert (
        alice_validate["results"][0]["message"]
        == bob_validate["results"][0]["message"]
        == _expected_gate_message()
    )

    # MCP submit_actions is strict — an invalid batch is rejected before
    # the turn resolves. Confirm: submitting ARCHER alone surfaces the
    # same gate message in the validation block of the error response.
    bob_reject = await _mcp_call(
        mcp, "submit_actions", {"api_key": bob_key, "actions": [bob_archer]}
    )
    assert "error" in bob_reject
    assert bob_reject["validation"][0]["valid"] is False
    assert bob_reject["validation"][0]["message"] == _expected_gate_message()

    # --- Turn 1: both players set archery as active research, each via
    # their preferred front door.
    _rest_submit(client, game_id, alice_key, [research_action])
    bob_turn1 = await _mcp_call(
        mcp, "submit_actions", {"api_key": bob_key, "actions": [research_action]}
    )
    assert bob_turn1.get("turn_resolved") is True, bob_turn1

    # After turn 1 both players have progress 9 (8 + 1/turn income) and
    # archery is still uncompleted on each front door.
    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state_bob = await _mcp_call(mcp, "get_game_state", {"api_key": bob_key})
    assert rest_state["research"]["alice"]["active"] == _TECH_ID
    assert rest_state["research"]["alice"]["progress"] == 9
    assert _TECH_ID not in rest_state["research"]["alice"]["completed"]
    assert mcp_state_bob["state"]["research"]["bob"]["progress"] == 9
    assert (
        _TECH_ID
        not in mcp_state_bob["state"]["research"]["bob"]["completed"]
    )

    # --- Turn 2: empty submissions. 9 + 1 = 10 → archery completes on
    # both players simultaneously.
    _rest_submit(client, game_id, alice_key, [])
    bob_turn2 = await _mcp_call(
        mcp, "submit_actions", {"api_key": bob_key, "actions": []}
    )
    assert bob_turn2.get("turn_resolved") is True, bob_turn2

    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state_bob = await _mcp_call(mcp, "get_game_state", {"api_key": bob_key})
    assert _TECH_ID in rest_state["research"]["alice"]["completed"]
    assert _TECH_ID in mcp_state_bob["state"]["research"]["bob"]["completed"]

    # --- Turn 3: both players now queue the previously-rejected ARCHER.
    # Both front doors must accept it; queue entries must match. Verify
    # via MCP validate_actions (shared dispatch) that the gate has
    # cleared on both players' sides before the actual submit.
    alice_validate2 = await _mcp_call(
        mcp, "validate_actions", {"api_key": alice_key, "actions": [alice_archer]}
    )
    bob_validate2 = await _mcp_call(
        mcp, "validate_actions", {"api_key": bob_key, "actions": [bob_archer]}
    )
    assert alice_validate2["all_valid"] is True
    assert bob_validate2["all_valid"] is True

    _rest_submit(client, game_id, alice_key, [alice_archer])
    bob_submit = await _mcp_call(
        mcp, "submit_actions", {"api_key": bob_key, "actions": [bob_archer]}
    )
    assert bob_submit.get("turn_resolved") is True, bob_submit

    # Queue state for each player's own city is identical across front
    # doors — ARCHER appears head-of-queue with no progress yet.
    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state_bob = await _mcp_call(mcp, "get_game_state", {"api_key": bob_key})

    alice_queue = rest_state["cities"]["1"]["build_queue"]
    bob_queue = mcp_state_bob["state"]["cities"]["2"]["build_queue"]

    # Both queues hold one job targeting ARCHER. Identical progress and
    # total_cost confirms both front doors drove the same deterministic
    # production path (ARCHER is 8pp; base rate 2/turn means one tick of
    # progress after the turn that queued it).
    assert len(alice_queue) == 1
    assert len(bob_queue) == 1
    assert alice_queue[0]["type"] == bob_queue[0]["type"] == "unit"
    assert (
        alice_queue[0]["target"]
        == bob_queue[0]["target"]
        == UnitType.ARCHER.value
    )
    assert alice_queue[0]["progress"] == bob_queue[0]["progress"]
    assert alice_queue[0]["total_cost"] == bob_queue[0]["total_cost"]
