"""Tests for Phase 6 MCP agent memory tools (write_scratchpad, read_scratchpad)."""

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
        await session.execute(delete(GameTurn).where(GameTurn.game_id.like("game_%")))
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
# write_scratchpad
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_scratchpad_success(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp,
        "write_scratchpad",
        {"api_key": api_key, "text": "Focus on expansion this turn."},
    )

    assert "error" not in result
    assert result["player"] == "alice"
    assert result["turn"] == 0
    assert result["characters"] == len("Focus on expansion this turn.")


@pytest.mark.asyncio
async def test_write_scratchpad_overwrites_same_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    await call(mcp, "write_scratchpad", {"api_key": api_key, "text": "First draft."})
    await call(mcp, "write_scratchpad", {"api_key": api_key, "text": "Revised plan."})

    # Read back — should be the second write
    result = await call(mcp, "read_scratchpad", {"api_key": api_key})

    assert result["text"] == "Revised plan."


@pytest.mark.asyncio
async def test_write_scratchpad_exceeds_cap(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    long_text = "x" * 4001
    result = await call(
        mcp, "write_scratchpad", {"api_key": api_key, "text": long_text}
    )

    assert "error" in result
    assert "4,000" in result["error"] or "4000" in result["error"]


@pytest.mark.asyncio
async def test_write_scratchpad_exactly_at_cap(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    text = "x" * 4000
    result = await call(mcp, "write_scratchpad", {"api_key": api_key, "text": text})

    assert "error" not in result
    assert result["characters"] == 4000


@pytest.mark.asyncio
async def test_write_scratchpad_invalid_key(db_session, mcp):
    result = await call(mcp, "write_scratchpad", {"api_key": "fx_bad", "text": "test"})
    assert "error" in result


@pytest.mark.asyncio
async def test_write_scratchpad_ended_game(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    # End the game manually
    async with async_session_factory() as session:
        from backend.src.database.repository import GameRepository

        repo = GameRepository(session)
        await repo.end_game(game_data["game_id"])
        await session.commit()

    result = await call(
        mcp, "write_scratchpad", {"api_key": api_key, "text": "too late"}
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# read_scratchpad
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_scratchpad_current_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    await call(mcp, "write_scratchpad", {"api_key": api_key, "text": "My notes."})

    result = await call(mcp, "read_scratchpad", {"api_key": api_key})

    assert result["text"] == "My notes."
    assert result["turn"] == 0
    assert result["characters"] == len("My notes.")


@pytest.mark.asyncio
async def test_read_scratchpad_no_entry(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "read_scratchpad", {"api_key": api_key})

    assert result["text"] is None
    assert result["characters"] == 0


@pytest.mark.asyncio
async def test_read_scratchpad_past_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Write on turn 0
    await call(mcp, "write_scratchpad", {"api_key": alice_key, "text": "Turn 0 notes."})

    # Advance to turn 1
    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})
    await call(mcp, "submit_actions", {"api_key": bob_key, "actions": []})

    # Read back turn 0's scratchpad from turn 1
    result = await call(
        mcp, "read_scratchpad", {"api_key": alice_key, "turn_number": 0}
    )

    assert result["text"] == "Turn 0 notes."
    assert result["turn"] == 0


@pytest.mark.asyncio
async def test_read_scratchpad_future_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "read_scratchpad", {"api_key": api_key, "turn_number": 99})

    assert "error" in result


@pytest.mark.asyncio
async def test_read_scratchpad_negative_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    api_key = game_data["api_keys"]["alice"]

    result = await call(mcp, "read_scratchpad", {"api_key": api_key, "turn_number": -1})

    assert "error" in result


@pytest.mark.asyncio
async def test_read_scratchpad_invalid_key(db_session, mcp):
    result = await call(mcp, "read_scratchpad", {"api_key": "fx_bad"})
    assert "error" in result


# ---------------------------------------------------------------------------
# Privacy: players cannot read each other's scratchpads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scratchpad_privacy(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Alice writes
    await call(
        mcp,
        "write_scratchpad",
        {"api_key": alice_key, "text": "Alice's secret plan."},
    )

    # Bob reads his own scratchpad — should be empty, not Alice's
    result = await call(mcp, "read_scratchpad", {"api_key": bob_key})

    assert result["text"] is None
    assert result["characters"] == 0


# ---------------------------------------------------------------------------
# Write + advance + write: scratchpad per turn isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scratchpad_per_turn_isolation(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    # Write on turn 0
    await call(
        mcp,
        "write_scratchpad",
        {"api_key": alice_key, "text": "Turn 0 strategy."},
    )

    # Advance to turn 1
    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})
    await call(mcp, "submit_actions", {"api_key": bob_key, "actions": []})

    # Current turn (1) scratchpad should be empty
    result = await call(mcp, "read_scratchpad", {"api_key": alice_key})
    assert result["turn"] == 1
    assert result["text"] is None

    # Turn 0 scratchpad should still be there
    result = await call(
        mcp, "read_scratchpad", {"api_key": alice_key, "turn_number": 0}
    )
    assert result["text"] == "Turn 0 strategy."
