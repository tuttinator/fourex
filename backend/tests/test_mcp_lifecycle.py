"""Tests for Phase 4 MCP game lifecycle tools."""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    PlayerApiKey,
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
    # call_tool returns (list[ContentBlock], raw_return_value)
    # The raw dict is the second element of the tuple
    if isinstance(result, tuple):
        return result[1]  # type: ignore[return-value]
    # Fallback: parse from TextContent
    return json.loads(result[0].text)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# create_game
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_game_success(db_session, mcp):
    data = await call(mcp, "create_game", {"players": ["alice", "bob"]})

    assert "game_id" in data
    assert data["players"] == ["alice", "bob"]
    assert "alice" in data["api_keys"]
    assert "bob" in data["api_keys"]
    assert data["api_keys"]["alice"].startswith("fx_")
    assert data["api_keys"]["bob"].startswith("fx_")
    assert data["seed"] == 42
    assert data["max_turns"] == 100


@pytest.mark.asyncio
async def test_create_game_custom_params(db_session, mcp):
    data = await call(
        mcp,
        "create_game",
        {
            "players": ["p1", "p2", "p3"],
            "seed": 123,
            "max_turns": 50,
            "map_width": 15,
            "map_height": 15,
        },
    )

    assert len(data["players"]) == 3
    assert data["seed"] == 123
    assert data["max_turns"] == 50
    assert data["map_size"] == {"width": 15, "height": 15}


@pytest.mark.asyncio
async def test_create_game_too_few_players(db_session, mcp):
    data = await call(mcp, "create_game", {"players": ["lonely"]})
    assert "error" in data


@pytest.mark.asyncio
async def test_create_game_duplicate_players(db_session, mcp):
    data = await call(mcp, "create_game", {"players": ["alice", "alice"]})
    assert "error" in data


# ---------------------------------------------------------------------------
# join_game
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_game_success(db_session, mcp):
    game_data = await call(mcp, "create_game", {"players": ["alice", "bob"]})
    game_id = game_data["game_id"]

    join_data = await call(
        mcp, "join_game", {"game_id": game_id, "player_name": "charlie"}
    )

    assert join_data["game_id"] == game_id
    assert join_data["player"] == "charlie"
    assert join_data["api_key"].startswith("fx_")


@pytest.mark.asyncio
async def test_join_game_not_found(db_session, mcp):
    data = await call(
        mcp, "join_game", {"game_id": "game_nonexistent", "player_name": "alice"}
    )
    assert "error" in data


@pytest.mark.asyncio
async def test_join_game_duplicate_player(db_session, mcp):
    game_data = await call(mcp, "create_game", {"players": ["alice", "bob"]})
    game_id = game_data["game_id"]

    data = await call(mcp, "join_game", {"game_id": game_id, "player_name": "alice"})
    assert "error" in data


# ---------------------------------------------------------------------------
# get_game_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_game_info_success(db_session, mcp):
    game_data = await call(
        mcp, "create_game", {"players": ["alice", "bob"], "max_turns": 75}
    )
    game_id = game_data["game_id"]

    info = await call(mcp, "get_game_info", {"game_id": game_id})

    assert info["game_id"] == game_id
    assert info["players"] == ["alice", "bob"]
    assert info["status"] == "created"
    assert info["max_turns"] == 75
    assert info["turn"] == 0


@pytest.mark.asyncio
async def test_get_game_info_not_found(db_session, mcp):
    data = await call(mcp, "get_game_info", {"game_id": "game_nonexistent"})
    assert "error" in data


# ---------------------------------------------------------------------------
# join_game updates game info
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# whoami
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whoami_returns_identity_for_creator_key(db_session, mcp):
    game_data = await call(mcp, "create_game", {"players": ["alice", "bob"]})
    game_id = game_data["game_id"]
    alice_key = game_data["api_keys"]["alice"]

    info = await call(mcp, "whoami", {"api_key": alice_key})
    assert info["game_id"] == game_id
    assert info["player_id"] == "alice"
    assert info["slot_index"] == 0


@pytest.mark.asyncio
async def test_whoami_returns_slot_index_for_joined_player(db_session, mcp):
    game_data = await call(mcp, "create_game", {"players": ["alice", "bob"]})
    game_id = game_data["game_id"]

    join_data = await call(
        mcp, "join_game", {"game_id": game_id, "player_name": "charlie"}
    )

    info = await call(mcp, "whoami", {"api_key": join_data["api_key"]})
    assert info["game_id"] == game_id
    assert info["player_id"] == "charlie"
    assert info["slot_index"] == 2


@pytest.mark.asyncio
async def test_whoami_invalid_key_errors(db_session, mcp):
    info = await call(mcp, "whoami", {"api_key": "fx_not_a_real_key"})
    assert "error" in info


@pytest.mark.asyncio
async def test_whoami_missing_key_errors(db_session, mcp):
    info = await call(mcp, "whoami", {"api_key": ""})
    assert "error" in info


@pytest.mark.asyncio
async def test_join_game_visible_in_info(db_session, mcp):
    game_data = await call(mcp, "create_game", {"players": ["alice", "bob"]})
    game_id = game_data["game_id"]

    await call(mcp, "join_game", {"game_id": game_id, "player_name": "charlie"})

    info = await call(mcp, "get_game_info", {"game_id": game_id})
    assert "charlie" in info["players"]
    assert len(info["players"]) == 3
