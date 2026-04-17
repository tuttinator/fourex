"""Tests for Phase 4 structured memory MCP tools."""

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


async def advance_turn(mcp: Any, alice_key: str, bob_key: str) -> None:
    """Advance the game by one turn by submitting empty actions for both players."""
    await call(mcp, "submit_actions", {"api_key": alice_key, "actions": []})
    await call(mcp, "submit_actions", {"api_key": bob_key, "actions": []})


# ---------------------------------------------------------------------------
# Strategic goals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategic_goals_round_trip(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    goals = [
        {"goal": "expand_north", "priority": 1, "status": "active", "since_turn": 0},
        {"goal": "defend_capital", "priority": 2, "status": "active", "since_turn": 0},
    ]
    write_result = await call(
        mcp,
        "write_strategic_goals",
        {"api_key": alice_key, "goals": goals},
    )
    assert "error" not in write_result
    assert write_result["goal_count"] == 2
    assert write_result["turn"] == 0

    read_result = await call(mcp, "read_strategic_goals", {"api_key": alice_key})
    assert "error" not in read_result
    assert read_result["goals"] == goals
    assert read_result["turn"] == 0


@pytest.mark.asyncio
async def test_strategic_goals_returns_latest_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    turn0_goals = [{"goal": "scout", "priority": 1}]
    await call(
        mcp, "write_strategic_goals", {"api_key": alice_key, "goals": turn0_goals}
    )
    await advance_turn(mcp, alice_key, bob_key)

    turn1_goals = [{"goal": "build_city", "priority": 1}]
    await call(
        mcp, "write_strategic_goals", {"api_key": alice_key, "goals": turn1_goals}
    )

    read_result = await call(mcp, "read_strategic_goals", {"api_key": alice_key})
    assert read_result["goals"] == turn1_goals
    assert read_result["turn"] == 1


@pytest.mark.asyncio
async def test_strategic_goals_falls_back_to_prior_turn(db_session, mcp):
    """If the current turn has no goals, fall back to the most recent turn with goals."""
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    goals = [{"goal": "scout", "priority": 1}]
    await call(mcp, "write_strategic_goals", {"api_key": alice_key, "goals": goals})
    await advance_turn(mcp, alice_key, bob_key)
    # Don't write on turn 1.

    read_result = await call(mcp, "read_strategic_goals", {"api_key": alice_key})
    assert read_result["goals"] == goals
    assert read_result["turn"] == 0


@pytest.mark.asyncio
async def test_strategic_goals_empty_when_none_written(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    read_result = await call(mcp, "read_strategic_goals", {"api_key": alice_key})
    assert read_result["goals"] == []
    assert read_result["turn"] is None


@pytest.mark.asyncio
async def test_strategic_goals_overwrite_same_turn(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    first = [{"goal": "scout"}]
    second = [{"goal": "defend"}, {"goal": "expand"}]

    await call(mcp, "write_strategic_goals", {"api_key": alice_key, "goals": first})
    await call(mcp, "write_strategic_goals", {"api_key": alice_key, "goals": second})

    read_result = await call(mcp, "read_strategic_goals", {"api_key": alice_key})
    assert read_result["goals"] == second


# ---------------------------------------------------------------------------
# Opponent models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opponent_model_round_trip(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    model = {"stance": "aggressive", "unit_count": 5, "threat_level": "high"}
    write_result = await call(
        mcp,
        "write_opponent_model",
        {"api_key": alice_key, "opponent_id": "bob", "model": model},
    )
    assert "error" not in write_result
    assert write_result["opponent_id"] == "bob"
    assert write_result["turn"] == 0

    read_result = await call(mcp, "read_opponent_models", {"api_key": alice_key})
    assert "error" not in read_result
    assert "bob" in read_result["opponents"]
    assert read_result["opponents"]["bob"]["model"] == model
    assert read_result["opponents"]["bob"]["turn"] == 0


@pytest.mark.asyncio
async def test_opponent_model_latest_per_opponent(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    old_model = {"stance": "defensive", "unit_count": 2}
    await call(
        mcp,
        "write_opponent_model",
        {"api_key": alice_key, "opponent_id": "bob", "model": old_model},
    )

    await advance_turn(mcp, alice_key, bob_key)

    new_model = {"stance": "aggressive", "unit_count": 7}
    await call(
        mcp,
        "write_opponent_model",
        {"api_key": alice_key, "opponent_id": "bob", "model": new_model},
    )

    read_result = await call(mcp, "read_opponent_models", {"api_key": alice_key})
    assert read_result["opponents"]["bob"]["model"] == new_model
    assert read_result["opponents"]["bob"]["turn"] == 1


@pytest.mark.asyncio
async def test_opponent_model_preserves_other_opponents_on_same_turn(db_session, mcp):
    """Writing one opponent's model should not wipe another opponent's entry on the same turn."""
    game_data = await call(
        mcp, "create_game", {"players": ["alice", "bob", "carol"]}
    )
    alice_key = game_data["api_keys"]["alice"]

    await call(
        mcp,
        "write_opponent_model",
        {"api_key": alice_key, "opponent_id": "bob", "model": {"stance": "hostile"}},
    )
    await call(
        mcp,
        "write_opponent_model",
        {"api_key": alice_key, "opponent_id": "carol", "model": {"stance": "friendly"}},
    )

    read_result = await call(mcp, "read_opponent_models", {"api_key": alice_key})
    assert read_result["opponents"]["bob"]["model"] == {"stance": "hostile"}
    assert read_result["opponents"]["carol"]["model"] == {"stance": "friendly"}


@pytest.mark.asyncio
async def test_opponent_model_rejects_self(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp,
        "write_opponent_model",
        {"api_key": alice_key, "opponent_id": "alice", "model": {"stance": "ok"}},
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_opponent_models_empty_when_none_written(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    read_result = await call(mcp, "read_opponent_models", {"api_key": alice_key})
    assert read_result["opponents"] == {}


# ---------------------------------------------------------------------------
# Turn notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_notes_round_trip(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    await call(
        mcp, "write_turn_notes", {"api_key": alice_key, "notes": "Scouted north coast."}
    )

    read_result = await call(mcp, "read_turn_notes", {"api_key": alice_key})
    assert "error" not in read_result
    assert read_result["entries"] == [
        {"turn_number": 0, "notes": "Scouted north coast."}
    ]


@pytest.mark.asyncio
async def test_turn_notes_lookback_orders_newest_first(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    await call(mcp, "write_turn_notes", {"api_key": alice_key, "notes": "Turn 0 obs"})
    await advance_turn(mcp, alice_key, bob_key)
    await call(mcp, "write_turn_notes", {"api_key": alice_key, "notes": "Turn 1 obs"})
    await advance_turn(mcp, alice_key, bob_key)
    await call(mcp, "write_turn_notes", {"api_key": alice_key, "notes": "Turn 2 obs"})

    # lookback=2 -> newest two entries
    read_result = await call(
        mcp, "read_turn_notes", {"api_key": alice_key, "lookback": 2}
    )
    assert read_result["entries"] == [
        {"turn_number": 2, "notes": "Turn 2 obs"},
        {"turn_number": 1, "notes": "Turn 1 obs"},
    ]


@pytest.mark.asyncio
async def test_turn_notes_lookback_default(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    await call(mcp, "write_turn_notes", {"api_key": alice_key, "notes": "only entry"})
    read_result = await call(mcp, "read_turn_notes", {"api_key": alice_key})
    assert read_result["lookback"] == 5
    assert len(read_result["entries"]) == 1


@pytest.mark.asyncio
async def test_turn_notes_rejects_oversized(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    big = "x" * 4001
    result = await call(mcp, "write_turn_notes", {"api_key": alice_key, "notes": big})
    assert "error" in result


@pytest.mark.asyncio
async def test_turn_notes_rejects_nonpositive_lookback(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    result = await call(
        mcp, "read_turn_notes", {"api_key": alice_key, "lookback": 0}
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# Per-game isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_memory_is_game_scoped(db_session, mcp):
    """Memory written in game A must not appear in game B for the same player name."""
    game_a = await create_two_player_game(mcp)
    game_b = await create_two_player_game(mcp)
    assert game_a["game_id"] != game_b["game_id"]

    alice_a = game_a["api_keys"]["alice"]
    alice_b = game_b["api_keys"]["alice"]

    await call(
        mcp,
        "write_strategic_goals",
        {"api_key": alice_a, "goals": [{"goal": "only in game A"}]},
    )
    await call(
        mcp,
        "write_opponent_model",
        {"api_key": alice_a, "opponent_id": "bob", "model": {"seen_in": "A"}},
    )
    await call(mcp, "write_turn_notes", {"api_key": alice_a, "notes": "game A notes"})

    goals_b = await call(mcp, "read_strategic_goals", {"api_key": alice_b})
    assert goals_b["goals"] == []
    assert goals_b["turn"] is None

    models_b = await call(mcp, "read_opponent_models", {"api_key": alice_b})
    assert models_b["opponents"] == {}

    notes_b = await call(mcp, "read_turn_notes", {"api_key": alice_b})
    assert notes_b["entries"] == []


@pytest.mark.asyncio
async def test_structured_memory_privacy_between_players(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]
    bob_key = game_data["api_keys"]["bob"]

    await call(
        mcp,
        "write_strategic_goals",
        {"api_key": alice_key, "goals": [{"goal": "alice only"}]},
    )

    bob_goals = await call(mcp, "read_strategic_goals", {"api_key": bob_key})
    assert bob_goals["goals"] == []


# ---------------------------------------------------------------------------
# Backwards compatibility: scratchpad still works alongside structured data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scratchpad_coexists_with_structured_data(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    await call(
        mcp, "write_scratchpad", {"api_key": alice_key, "text": "freeform thoughts"}
    )
    await call(
        mcp,
        "write_strategic_goals",
        {"api_key": alice_key, "goals": [{"goal": "coexist"}]},
    )

    scratch = await call(mcp, "read_scratchpad", {"api_key": alice_key})
    assert scratch["text"] == "freeform thoughts"

    goals = await call(mcp, "read_strategic_goals", {"api_key": alice_key})
    assert goals["goals"] == [{"goal": "coexist"}]


# ---------------------------------------------------------------------------
# Auth errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_memory_invalid_key(db_session, mcp):
    tools_with_no_body = [
        ("read_strategic_goals", {}),
        ("read_opponent_models", {}),
        ("read_turn_notes", {}),
    ]
    for tool, extra in tools_with_no_body:
        result = await call(mcp, tool, {"api_key": "fx_bad", **extra})
        assert "error" in result, f"{tool} should reject invalid keys"

    write_cases = [
        ("write_strategic_goals", {"goals": []}),
        (
            "write_opponent_model",
            {"opponent_id": "bob", "model": {"x": 1}},
        ),
        ("write_turn_notes", {"notes": "x"}),
    ]
    for tool, extra in write_cases:
        result = await call(mcp, tool, {"api_key": "fx_bad", **extra})
        assert "error" in result, f"{tool} should reject invalid keys"


@pytest.mark.asyncio
async def test_structured_memory_writes_blocked_on_ended_game(db_session, mcp):
    game_data = await create_two_player_game(mcp)
    alice_key = game_data["api_keys"]["alice"]

    async with async_session_factory() as session:
        from backend.src.database.repository import GameRepository

        repo = GameRepository(session)
        await repo.end_game(game_data["game_id"])
        await session.commit()

    assert "error" in await call(
        mcp, "write_strategic_goals", {"api_key": alice_key, "goals": []}
    )
    assert "error" in await call(
        mcp,
        "write_opponent_model",
        {"api_key": alice_key, "opponent_id": "bob", "model": {}},
    )
    assert "error" in await call(
        mcp, "write_turn_notes", {"api_key": alice_key, "notes": "x"}
    )
