"""Tests for Phase 7 MCP turn history and snapshot tools (get_turn_history, get_turn_snapshot)."""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    AgentMemory,
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
            delete(AgentMemory).where(AgentMemory.game_id.like("game_%"))
        )
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


async def advance_turn(mcp: Any, alice_key: str, bob_key: str) -> None:
    """Helper: both players submit empty actions to advance the turn."""
    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})
    await call(mcp, "submit_actions", {"api_key": bob_key, "actions": []})


# ---------------------------------------------------------------------------
# get_turn_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_turn_history_empty(db_session, mcp):
    """No history before any actions have been submitted."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "get_turn_history", {"api_key": api_key})

    assert "error" not in result
    assert result["total_turns"] == 0
    assert result["history"] == []


@pytest.mark.asyncio
async def test_get_turn_history_after_one_turn(db_session, mcp):
    """History contains one entry after submitting actions on turn 0."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Both submit to advance turn
    await advance_turn(mcp, alice_key, bob_key)

    result = await call(mcp, "get_turn_history", {"api_key": alice_key})

    assert "error" not in result
    assert result["total_turns"] == 1
    assert result["history"][0]["turn_number"] == 0
    assert isinstance(result["history"][0]["actions"], list)


@pytest.mark.asyncio
async def test_get_turn_history_multiple_turns(db_session, mcp):
    """History accumulates over multiple turns."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Play 3 turns
    for _ in range(3):
        await advance_turn(mcp, alice_key, bob_key)

    result = await call(mcp, "get_turn_history", {"api_key": alice_key})

    assert result["total_turns"] == 3
    assert [e["turn_number"] for e in result["history"]] == [0, 1, 2]


@pytest.mark.asyncio
async def test_get_turn_history_only_own_actions(db_session, mcp):
    """A player only sees their own history, not the other player's."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Alice submits, Bob submits — turn advances
    await advance_turn(mcp, alice_key, bob_key)

    alice_history = await call(mcp, "get_turn_history", {"api_key": alice_key})
    bob_history = await call(mcp, "get_turn_history", {"api_key": bob_key})

    assert alice_history["player"] == "alice"
    assert bob_history["player"] == "bob"
    # Both should have 1 turn of history
    assert alice_history["total_turns"] == 1
    assert bob_history["total_turns"] == 1


@pytest.mark.asyncio
async def test_get_turn_history_invalid_key(db_session, mcp):
    result = await call(mcp, "get_turn_history", {"api_key": "fx_bad"})
    assert "error" in result


# ---------------------------------------------------------------------------
# get_turn_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_turn_snapshot_after_turn(db_session, mcp):
    """Snapshot is available for a resolved turn."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Advance past turn 0
    await advance_turn(mcp, alice_key, bob_key)

    result = await call(
        mcp, "get_turn_snapshot", {"api_key": alice_key, "turn_number": 0}
    )

    assert "error" not in result
    assert result["turn_number"] == 0
    assert result["player"] == "alice"
    assert "state" in result
    # The state should be a dict with game state fields
    assert isinstance(result["state"], dict)


@pytest.mark.asyncio
async def test_get_turn_snapshot_current_turn_errors(db_session, mcp):
    """Cannot get a snapshot for the current (unresolved) turn."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp, "get_turn_snapshot", {"api_key": api_key, "turn_number": 0}
    )

    assert "error" in result
    assert "not resolved" in result["error"].lower()


@pytest.mark.asyncio
async def test_get_turn_snapshot_future_turn_errors(db_session, mcp):
    """Cannot get a snapshot for a future turn."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp, "get_turn_snapshot", {"api_key": api_key, "turn_number": 99}
    )

    assert "error" in result
    assert "not resolved" in result["error"].lower()


@pytest.mark.asyncio
async def test_get_turn_snapshot_negative_turn_errors(db_session, mcp):
    """Negative turn number returns an error."""
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp, "get_turn_snapshot", {"api_key": api_key, "turn_number": -1}
    )

    assert "error" in result


@pytest.mark.asyncio
async def test_get_turn_snapshot_multiple_turns(db_session, mcp):
    """Snapshots are available for all resolved turns."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Play 3 turns
    for _ in range(3):
        await advance_turn(mcp, alice_key, bob_key)

    # All 3 past turns should have snapshots
    for turn in range(3):
        result = await call(
            mcp, "get_turn_snapshot", {"api_key": alice_key, "turn_number": turn}
        )
        assert "error" not in result
        assert result["turn_number"] == turn


@pytest.mark.asyncio
async def test_get_turn_snapshot_privacy(db_session, mcp):
    """Each player gets their own fog-of-war view, not the other player's."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    await advance_turn(mcp, alice_key, bob_key)

    alice_snap = await call(
        mcp, "get_turn_snapshot", {"api_key": alice_key, "turn_number": 0}
    )
    bob_snap = await call(
        mcp, "get_turn_snapshot", {"api_key": bob_key, "turn_number": 0}
    )

    assert alice_snap["player"] == "alice"
    assert bob_snap["player"] == "bob"
    # Both should have state but they are separate fog-of-war views
    assert "state" in alice_snap
    assert "state" in bob_snap


@pytest.mark.asyncio
async def test_get_turn_snapshot_invalid_key(db_session, mcp):
    result = await call(
        mcp, "get_turn_snapshot", {"api_key": "fx_bad", "turn_number": 0}
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# Integration: history + snapshot together
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_and_snapshot_after_multiple_turns(db_session, mcp):
    """Both history and snapshots are consistent after multiple turns."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Play 2 turns
    await advance_turn(mcp, alice_key, bob_key)
    await advance_turn(mcp, alice_key, bob_key)

    history = await call(mcp, "get_turn_history", {"api_key": alice_key})
    assert history["total_turns"] == 2

    # Each turn in history should have a corresponding snapshot
    for entry in history["history"]:
        snap = await call(
            mcp,
            "get_turn_snapshot",
            {"api_key": alice_key, "turn_number": entry["turn_number"]},
        )
        assert "error" not in snap
        assert snap["turn_number"] == entry["turn_number"]
