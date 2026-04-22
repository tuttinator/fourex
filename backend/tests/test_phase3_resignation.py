"""Phase 3 spectated-agents: resignation.

Covers the Phase 3 acceptance criteria for ``plans/spectated-agents.md``:
``ResignAction`` flows through REST ``POST /actions`` and the MCP
``resign_game`` tool; in a 2-player game the remaining seat wins and
the game ends with ``end_reason='resignation'``; in a 3+ player game
the resigner's assets are razed and play continues.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.src.auth import create_player_key
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.repository import GameRepository
from backend.src.game.models import GameState
from backend.src.main import app
from backend.src.mcp_server.server import create_mcp_server


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def _init_db() -> None:
    await init_db()


def _game_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000000)}"


async def _mint_key(game_id: str, player_id: str) -> str:
    async with async_session_factory() as session:
        key = await create_player_key(session, game_id, player_id)
        await session.commit()
        return key


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


async def _get_game_row(game_id: str) -> Any:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        return await repo.get_game(game_id)


@pytest.mark.asyncio
async def test_two_player_resignation_ends_game_via_rest(
    client: TestClient, _init_db: None
) -> None:
    game_id = _game_id("resign_2p")
    client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": ["alice", "bob"], "seed": 42},
    )
    alice_key = await _mint_key(game_id, "alice")

    response = client.post(
        f"/api/v1/actions?game_id={game_id}",
        json=[{"type": "RESIGN"}],
        headers=_auth_headers(alice_key),
    )
    assert response.status_code == 200

    game = await _get_game_row(game_id)
    assert game is not None
    assert game.status == "ended"
    assert game.winner == "bob"
    assert game.victory_type == "resignation"
    assert game.end_reason == "resignation"
    assert game.resigned_by == "alice"
    assert game.resigned_at is not None
    assert game.ended_at is not None

    # Resigner's assets are razed via the standard eliminate_player path.
    state = GameState.model_validate(game.state)
    assert "alice" in state.eliminated_players
    assert all(city.owner != "alice" for city in state.cities.values())
    assert all(unit.owner != "alice" for unit in state.units.values())


@pytest.mark.asyncio
async def test_resignation_is_rejected_for_unseated_caller(
    client: TestClient, _init_db: None
) -> None:
    game_id = _game_id("resign_unseated")
    client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": ["alice", "bob"], "seed": 42},
    )

    # Mint a key for a player_id that isn't in ``game.players``. The
    # auth layer binds the key to ``charlie`` but the game has only
    # alice+bob — submit should 400 without mutating the game.
    stranger_key = await _mint_key(game_id, "charlie")

    response = client.post(
        f"/api/v1/actions?game_id={game_id}",
        json=[{"type": "RESIGN"}],
        headers=_auth_headers(stranger_key),
    )
    assert response.status_code == 400

    game = await _get_game_row(game_id)
    assert game is not None
    assert game.status in {"active", "created"}
    assert game.end_reason is None


@pytest.mark.asyncio
async def test_three_player_resignation_eliminates_without_ending_game(
    client: TestClient, _init_db: None
) -> None:
    game_id = _game_id("resign_3p")
    client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": ["alice", "bob", "carol"], "seed": 42},
    )
    alice_key = await _mint_key(game_id, "alice")

    response = client.post(
        f"/api/v1/actions?game_id={game_id}",
        json=[{"type": "RESIGN"}],
        headers=_auth_headers(alice_key),
    )
    assert response.status_code == 200

    game = await _get_game_row(game_id)
    assert game is not None
    # 3-player: play continues, so the row is still not ended.
    assert game.status == "active"
    assert game.winner is None
    assert game.end_reason is None
    assert game.resigned_by is None

    state = GameState.model_validate(game.state)
    assert "alice" in state.eliminated_players
    assert "bob" not in state.eliminated_players
    assert "carol" not in state.eliminated_players
    assert all(city.owner != "alice" for city in state.cities.values())
    assert all(unit.owner != "alice" for unit in state.units.values())


# --- MCP surface ----------------------------------------------------------


async def _call_mcp(mcp: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(tool, args)
    if isinstance(result, tuple):
        return result[1]  # type: ignore[return-value]
    return json.loads(result[0].text)  # type: ignore[union-attr]


@pytest.fixture
def mcp():
    return create_mcp_server()


@pytest.mark.asyncio
async def test_mcp_resign_game_ends_two_player_match(_init_db: None, mcp) -> None:
    game = await _call_mcp(mcp, "create_game", {"players": ["alice", "bob"]})
    alice_key = game["api_keys"]["alice"]

    summary = await _call_mcp(mcp, "resign_game", {"api_key": alice_key})
    assert summary["resigned"] is True
    assert summary["game_ended"] is True
    assert summary["winner"] == "bob"
    assert summary["remaining_players"] == ["bob"]

    row = await _get_game_row(game["game_id"])
    assert row is not None
    assert row.status == "ended"
    assert row.winner == "bob"
    assert row.end_reason == "resignation"
    assert row.resigned_by == "alice"


@pytest.mark.asyncio
async def test_mcp_resign_game_rejects_after_game_has_ended(
    _init_db: None, mcp
) -> None:
    game = await _call_mcp(mcp, "create_game", {"players": ["alice", "bob"]})
    alice_key = game["api_keys"]["alice"]
    bob_key = game["api_keys"]["bob"]

    first = await _call_mcp(mcp, "resign_game", {"api_key": alice_key})
    assert first["game_ended"] is True

    # Bob tries to resign a game that's already ended.
    second = await _call_mcp(mcp, "resign_game", {"api_key": bob_key})
    assert "error" in second
