"""Phase 4 cross-front-door integration test.

Acceptance criterion from ``plans/sprites-production-tech.md``:

    Cross-front-door integration test: human and MCP agent both reorder
    and cancel queue entries with identical observable state.

Strategy — alice (REST) and bob (MCP) play the same game. We pre-seed
alice's city with three queued scouts using ``SET_CITY_PRODUCTION``
issued through alternating front doors, then reorder through MCP,
cancel the (now-waiting) tail entry through REST, and verify both front
doors see identical ``build_queue`` content on every step.
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


async def _seed_alice_city(game_id: str, city_id: int = 1) -> None:
    """Overwrite the game's state with a plains grid and a single alice
    city ready to accept queue operations. Alice's stockpile is padded
    so every SET_CITY_PRODUCTION action we send through the test
    succeeds on the funding check."""
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        assert state is not None

        new_tiles = []
        tile_id = 0
        for y in range(10):
            for x in range(10):
                new_tiles.append(
                    Tile(id=tile_id, loc=Coord(x=x, y=y), terrain=Terrain.GRASS)
                )
                tile_id += 1
        state.tiles = new_tiles
        state.map_width = 10
        state.map_height = 10
        state.units.clear()

        city = City(id=city_id, owner="alice", loc=Coord(x=5, y=5))
        state.cities = {city_id: city}
        tile = state.get_tile(Coord(x=5, y=5))
        assert tile is not None
        tile.city_id = city_id
        tile.owner = "alice"
        state.next_city_id = city_id + 1

        # Pad stockpiles; we only care about queue mechanics here.
        for p in state.players:
            state.stockpiles[p] = ResourceBag(
                food=500, ore=500, wood=500, crystal=500
            )

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
) -> None:
    resp = await _mcp_call(
        mcp, "submit_actions", {"api_key": api_key, "actions": actions}
    )
    assert resp.get("turn_resolved") is True, resp


@pytest.mark.asyncio
async def test_rest_and_mcp_observe_identical_queue_after_reorder_and_cancel(
    client: TestClient, mcp: Any, _clean_rows: None
) -> None:
    resp = await _mcp_call(mcp, "create_game", {"players": ["alice", "bob"]})
    assert "error" not in resp, resp
    game_id = resp["game_id"]
    alice_key = resp["api_keys"]["alice"]
    bob_key = resp["api_keys"]["bob"]

    await _seed_alice_city(game_id)

    # Turn 1: alice (REST) queues scout+soldier, bob (MCP) sends nothing.
    await _alice_rest_submit(
        client,
        game_id,
        alice_key,
        [
            {
                "type": "SET_CITY_PRODUCTION",
                "city_id": 1,
                "unit_type": UnitType.SCOUT.value,
            },
            {
                "type": "SET_CITY_PRODUCTION",
                "city_id": 1,
                "unit_type": UnitType.SOLDIER.value,
            },
        ],
    )
    await _bob_mcp_submit(mcp, bob_key, [])

    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state = await _mcp_call(mcp, "get_game_state", {"api_key": alice_key})
    rest_queue = rest_state["cities"]["1"]["build_queue"]
    mcp_queue = mcp_state["state"]["cities"]["1"]["build_queue"]
    assert rest_queue == mcp_queue
    # After 1 turn the scout (head) has progressed by 2.
    assert [j["target"] for j in rest_queue] == [
        UnitType.SCOUT.value,
        UnitType.SOLDIER.value,
    ]
    assert rest_queue[0]["progress"] == 2
    assert rest_queue[1]["progress"] == 0

    # Turn 2: alice reorders via MCP, then bob submits empty via MCP to
    # trigger resolution. Alice's key authenticates her on both front
    # doors; submitting the reorder via MCP proves MCP can drive the
    # queue-manipulation action surface.
    alice_mcp_resp = await _mcp_call(
        mcp,
        "submit_actions",
        {
            "api_key": alice_key,
            "actions": [
                {
                    "type": "REORDER_CITY_QUEUE",
                    "city_id": 1,
                    "new_order": [1, 0],
                }
            ],
        },
    )
    assert alice_mcp_resp.get("turn_resolved") is False, alice_mcp_resp
    await _bob_mcp_submit(mcp, bob_key, [])

    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state = await _mcp_call(mcp, "get_game_state", {"api_key": alice_key})
    rest_queue = rest_state["cities"]["1"]["build_queue"]
    mcp_queue = mcp_state["state"]["cities"]["1"]["build_queue"]
    assert rest_queue == mcp_queue
    # Soldier is now at head; its progress is 2 after this turn's advance
    # (reorder resolves before production-advance, so the resolver then
    # ticks the new head). Scout moves to index 1 with its original
    # 2 progress carried.
    assert [j["target"] for j in rest_queue] == [
        UnitType.SOLDIER.value,
        UnitType.SCOUT.value,
    ]
    assert rest_queue[0]["progress"] == 2  # soldier, newly-ticked head
    assert rest_queue[1]["progress"] == 2  # scout progress preserved

    # Turn 3: alice cancels the waiting scout via REST.
    await _alice_rest_submit(
        client,
        game_id,
        alice_key,
        [
            {
                "type": "CANCEL_CITY_PRODUCTION",
                "city_id": 1,
                "queue_index": 1,
            }
        ],
    )
    await _bob_mcp_submit(mcp, bob_key, [])

    rest_state = _rest_get_state(client, game_id, alice_key)
    mcp_state = await _mcp_call(mcp, "get_game_state", {"api_key": alice_key})
    rest_queue = rest_state["cities"]["1"]["build_queue"]
    mcp_queue = mcp_state["state"]["cities"]["1"]["build_queue"]
    assert rest_queue == mcp_queue
    # Only the soldier remains; its progress is now 4 (2 from the turn
    # 2 advance + 2 from turn 3's advance).
    assert [j["target"] for j in rest_queue] == [UnitType.SOLDIER.value]
    assert rest_queue[0]["progress"] == 4
