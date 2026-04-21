"""Phase 3 cross-front-door integration test.

Acceptance criterion from ``plans/sprites-production-tech.md``:

    Cross-front-door integration test: a human and an MCP agent in the
    same game observe identical production completion turns.

Strategy — rather than racing two separate clients, this test seats
alice and bob in one game, pre-seeds a city with a freshly queued
``TrainUnitAction`` (the game has no cities at start), then advances
turns by having alice submit empty actions via the REST ``/actions``
endpoint and bob submit empty actions via the MCP ``submit_actions``
tool. On every turn we read alice's state via *both* surfaces and
assert they agree byte-for-byte on ``cities[1].build_queue`` and on the
turn number on which the unit materialises. Because REST and MCP share
a controller + database, any drift in production timing between the
two front doors would surface here immediately.
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
    BuildJob,
    City,
    Coord,
    ResourceBag,
    Terrain,
    Tile,
    UNIT_PRODUCTION_COST,
    UnitType,
)
from backend.src.main import app
from backend.src.mcp_server.server import create_mcp_server

_GAME_PREFIX = "game"


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


async def _seed_city_with_queued_scout(
    game_id: str, owner: str, city_id: int = 1
) -> None:
    """Overwrite the game's state with a single city owned by ``owner``
    that has a SCOUT already queued (progress=0). Uses plains tiles in a
    10x10 world so the city tile is guaranteed passable.
    """
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        assert state is not None

        # Rewrite tiles as plains so the city tile is trivially legal and
        # the test doesn't depend on map-gen RNG.
        new_tiles = []
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
        # Drop starting units — they'd sit on tiles we just recreated and
        # we don't want them to interfere with production.
        state.units.clear()

        # Seed a single city for ``owner`` at (5, 5).
        city = City(id=city_id, owner=owner, loc=Coord(x=5, y=5))
        city.build_queue = BuildJob(
            type="unit",
            target=UnitType.SCOUT.value,
            progress=0,
            total_cost=UNIT_PRODUCTION_COST[UnitType.SCOUT],
        )
        state.cities = {city_id: city}
        tile = state.get_tile(Coord(x=5, y=5))
        assert tile is not None
        tile.city_id = city_id
        tile.owner = owner
        state.next_city_id = city_id + 1

        # Give stockpiles headroom (resources would have been deducted at
        # queue time; we skip that bookkeeping here since the test is
        # about timing, not economics).
        for p in state.players:
            state.stockpiles[p] = ResourceBag(food=100, ore=100, wood=100)

        await controller.repo.update_game_state(game_id, state)
        await session.commit()


@pytest.mark.asyncio
async def test_rest_and_mcp_observe_identical_production_completion_turn(
    client: TestClient, mcp: Any, _clean_rows: None
) -> None:
    # MCP owns game creation here — seat alice + bob and mint api keys.
    # The server auto-generates a ``game_<hex>`` id; we use what it returns.
    resp = await _mcp_call(mcp, "create_game", {"players": ["alice", "bob"]})
    assert "error" not in resp, resp
    game_id = resp["game_id"]
    assert game_id.startswith(_GAME_PREFIX + "_")
    alice_key = resp["api_keys"]["alice"]
    bob_key = resp["api_keys"]["bob"]

    # Pre-seed alice's city with a freshly queued Scout job. Scout costs
    # 5 production; plain city produces 2/turn → completes on turn 3.
    await _seed_city_with_queued_scout(game_id, owner="alice")

    # Sanity: both front doors agree on the initial queue state.
    rest_state_0 = _rest_get_state(client, game_id, alice_key)
    mcp_state_0 = await _mcp_call(mcp, "get_game_state", {"api_key": alice_key})
    rest_queue_0 = rest_state_0["cities"]["1"]["build_queue"]
    mcp_queue_0 = mcp_state_0["state"]["cities"]["1"]["build_queue"]
    assert rest_queue_0 == mcp_queue_0
    assert rest_queue_0["progress"] == 0
    assert rest_queue_0["total_cost"] == UNIT_PRODUCTION_COST[UnitType.SCOUT]

    # Drive turns, with alice submitting via REST and bob via MCP so
    # both front doors participate in each resolution.
    expected_progress_after_turn = {1: 2, 2: 4, 3: None}  # None: completed
    rest_completion_turn: int | None = None
    mcp_completion_turn: int | None = None

    for turn_number in (1, 2, 3):
        alice_submit = client.post(
            f"/api/v1/actions?game_id={game_id}",
            json=[],
            headers={"Authorization": f"Bearer {alice_key}"},
        )
        assert alice_submit.status_code == 200, alice_submit.text

        bob_submit = await _mcp_call(
            mcp, "submit_actions", {"api_key": bob_key, "actions": []}
        )
        assert bob_submit.get("turn_resolved") is True, bob_submit

        rest_state = _rest_get_state(client, game_id, alice_key)
        mcp_state = await _mcp_call(mcp, "get_game_state", {"api_key": alice_key})

        # Turn counter advances in lockstep.
        assert rest_state["turn"] == turn_number
        assert mcp_state["state"]["turn"] == turn_number

        rest_city = rest_state["cities"]["1"]
        mcp_city = mcp_state["state"]["cities"]["1"]

        # Identical observable state across front doors.
        assert rest_city["build_queue"] == mcp_city["build_queue"]

        expected = expected_progress_after_turn[turn_number]
        if expected is None:
            # Completion: the queue is empty in both views, and the Scout
            # has materialised on alice's city tile in both views.
            assert rest_city["build_queue"] is None
            assert mcp_city["build_queue"] is None
            alice_units_rest = [
                u for u in rest_state["units"].values() if u["owner"] == "alice"
            ]
            alice_units_mcp = [
                u for u in mcp_state["state"]["units"].values() if u["owner"] == "alice"
            ]
            assert any(u["type"] == UnitType.SCOUT.value for u in alice_units_rest)
            assert any(u["type"] == UnitType.SCOUT.value for u in alice_units_mcp)
            rest_completion_turn = turn_number
            mcp_completion_turn = turn_number
        else:
            assert rest_city["build_queue"]["progress"] == expected
            assert mcp_city["build_queue"]["progress"] == expected

    # The whole point: both front doors report the same completion turn.
    assert rest_completion_turn is not None
    assert mcp_completion_turn is not None
    assert rest_completion_turn == mcp_completion_turn == 3
