"""Tests for Phase 5 MCP game state and turn flow tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, update

from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
)
from backend.src.mcp_server.server import create_mcp_server


@pytest_asyncio.fixture
async def db_session():
    """Async DB session with cleanup."""
    await init_db()
    async with async_session_factory() as session:
        yield session
        await session.rollback()
        # Clean up test data
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("game_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("game_%"))
        )
        await session.execute(
            delete(GameTurn).where(GameTurn.game_id.like("game_%"))
        )
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("game_%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like("game_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("game_%")))
        await session.commit()


@pytest.fixture
def mcp():
    """Create an MCP server instance with all tools registered."""
    return create_mcp_server()


async def call(mcp: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and parse the JSON response."""
    result = await mcp.call_tool(tool, args)
    if isinstance(result, tuple):
        return result[1]  # type: ignore[return-value]
    return json.loads(result[0].text)  # type: ignore[union-attr]


async def create_two_player_game(mcp: Any) -> dict[str, Any]:
    """Helper: create a game with alice and bob, return game data."""
    return await call(mcp, "create_game", {"players": ["alice", "bob"]})


# ---------------------------------------------------------------------------
# get_game_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_game_state_success(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    state = await call(mcp, "get_game_state", {"api_key": api_key})

    assert state["game_id"] == game_data["game_id"]
    assert state["player"] == "alice"
    assert state["turn"] == 0
    assert "state" in state
    # Fog-of-war: should have some tiles but not all (20x20 = 400 tiles)
    assert len(state["state"]["tiles"]) < 400


@pytest.mark.asyncio
async def test_get_game_state_invalid_key(db_session, mcp):
    data = await call(mcp, "get_game_state", {"api_key": "fx_invalid"})
    assert "error" in data


# ---------------------------------------------------------------------------
# is_my_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_my_turn_before_submission(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "is_my_turn", {"api_key": api_key})

    assert result["turn"] == 0
    assert result["waiting_for_you"] is True
    assert result["has_submitted"] is False
    assert result["total_players"] == 2


@pytest.mark.asyncio
async def test_is_my_turn_after_submission(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    # Alice submits (empty actions = pass)
    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})

    result = await call(mcp, "is_my_turn", {"api_key": alice_key})

    assert result["has_submitted"] is True
    assert result["waiting_for_you"] is False


@pytest.mark.asyncio
async def test_is_my_turn_invalid_key(db_session, mcp):
    data = await call(mcp, "is_my_turn", {"api_key": "fx_bad"})
    assert "error" in data


# ---------------------------------------------------------------------------
# submit_actions — basic flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_empty_actions(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})

    assert result["actions_submitted"] == 0
    assert result["turn_resolved"] is False


@pytest.mark.asyncio
async def test_submit_actions_both_players_resolves_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Both submit empty actions
    result_a = await call(
        mcp, "submit_actions", {"api_key": alice_key, "actions": []}
    )
    assert result_a["turn_resolved"] is False

    result_b = await call(
        mcp, "submit_actions", {"api_key": bob_key, "actions": []}
    )
    assert result_b["turn_resolved"] is True
    assert result_b["new_turn"] == 1


@pytest.mark.asyncio
async def test_submit_actions_activates_game(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    # Before submit, game is "created"
    info = await call(mcp, "get_game_info", {"game_id": game_data["game_id"]})
    assert info["status"] == "created"

    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})

    # After submit, game should be "active"
    info = await call(mcp, "get_game_info", {"game_id": game_data["game_id"]})
    assert info["status"] == "active"


@pytest.mark.asyncio
async def test_submit_actions_invalid_key(db_session, mcp):
    data = await call(
        mcp, "submit_actions", {"api_key": "fx_nope", "actions": []}
    )
    assert "error" in data


@pytest.mark.asyncio
async def test_submit_actions_ended_game(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    # End the game manually
    async with async_session_factory() as session:
        from backend.src.database.repository import GameRepository

        repo = GameRepository(session)
        await repo.end_game(game_data["game_id"])
        await session.commit()

    result = await call(
        mcp, "submit_actions", {"api_key": alice_key, "actions": []}
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# submit_actions — with real moves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_move_action(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    # Get state to find alice's unit
    state = await call(mcp, "get_game_state", {"api_key": alice_key})
    units = state["state"]["units"]

    # Find alice's unit
    alice_unit = None
    for uid, u in units.items():
        if u["owner"] == "alice":
            alice_unit = (int(uid), u)
            break

    if alice_unit is None:
        pytest.skip("Could not find alice's unit in visible state")

    unit_id, unit_data = alice_unit
    ux, uy = unit_data["loc"]["x"], unit_data["loc"]["y"]

    # Try adjacent tiles until we find a valid one
    from backend.src.game.models import Coord, GameState, Terrain

    full_state_data = state["state"]
    tiles_by_loc = {(t["loc"]["x"], t["loc"]["y"]): t for t in full_state_data["tiles"]}

    target = None
    for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
        nx, ny = (ux + dx) % 20, (uy + dy) % 20
        tile = tiles_by_loc.get((nx, ny))
        if tile and tile["terrain"] in ("plains", "forest") and tile.get("unit_id") is None:
            target = {"x": nx, "y": ny}
            break

    if target is None:
        pytest.skip("No valid adjacent tile for move")

    move_action = {"type": "MOVE", "unit_id": unit_id, "to": target}
    result = await call(
        mcp, "submit_actions", {"api_key": alice_key, "actions": [move_action]}
    )

    assert "error" not in result
    assert result["actions_submitted"] == 1


# ---------------------------------------------------------------------------
# validate_actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_empty_actions(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp, "validate_actions", {"api_key": alice_key, "actions": []}
    )

    assert result["all_valid"] is True
    assert result["results"] == []


@pytest.mark.asyncio
async def test_validate_invalid_action(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    # Move a non-existent unit
    result = await call(
        mcp,
        "validate_actions",
        {
            "api_key": alice_key,
            "actions": [{"type": "MOVE", "unit_id": 9999, "to": {"x": 0, "y": 0}}],
        },
    )

    assert result["all_valid"] is False
    assert len(result["results"]) == 1
    assert result["results"][0]["valid"] is False


@pytest.mark.asyncio
async def test_validate_bad_action_format(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp,
        "validate_actions",
        {
            "api_key": alice_key,
            "actions": [{"type": "UNKNOWN_ACTION"}],
        },
    )

    assert "error" in result


# ---------------------------------------------------------------------------
# Turn snapshots are saved on resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_snapshots_saved_on_resolve(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]
    game_id = game_data["game_id"]

    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})
    await call(mcp, "submit_actions", {"api_key": bob_key, "actions": []})

    # Check that snapshots were created
    async with async_session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(TurnSnapshot).where(TurnSnapshot.game_id == game_id)
        )
        snapshots = list(result.scalars().all())

    assert len(snapshots) == 2  # one per player
    players_with_snapshots = {s.player_id for s in snapshots}
    assert players_with_snapshots == {"alice", "bob"}
    assert all(s.turn_number == 0 for s in snapshots)


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_resolves_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    game_id = game_data["game_id"]

    # Alice submits but bob does not
    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})

    # Manually set turn_started_at to 11 minutes ago to simulate timeout
    async with async_session_factory() as session:
        past = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=11)
        await session.execute(
            update(Game).where(Game.id == game_id).values(turn_started_at=past)
        )
        await session.commit()

    # Alice checks is_my_turn — should trigger timeout resolution
    result = await call(mcp, "is_my_turn", {"api_key": alice_key})

    # Turn should have advanced
    assert result["turn"] == 1 or result.get("turn_just_resolved") is True


# ---------------------------------------------------------------------------
# Multiple turns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_turns(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Turn 0
    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})
    result = await call(mcp, "submit_actions", {"api_key": bob_key, "actions": []})
    assert result["new_turn"] == 1

    # Turn 1
    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})
    result = await call(mcp, "submit_actions", {"api_key": bob_key, "actions": []})
    assert result["new_turn"] == 2

    # Verify state advanced
    state = await call(mcp, "get_game_state", {"api_key": alice_key})
    assert state["turn"] == 2
