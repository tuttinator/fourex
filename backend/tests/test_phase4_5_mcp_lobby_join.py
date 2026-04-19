"""Tests for Phase 4.5: MCP ``join_game`` unified with the controller's join path.

Phase 2 introduced JWT-gated lobby creation that lands games in ``waiting``
status. The MCP ``join_game`` tool used to hard-gate on ``status ==
"created"`` and ran a bespoke roster/unit/key path that diverged from
``PersistentGameController.join_game``. That blocked the PRD's "one game,
two front doors" promise: an MCP agent could not join a lobby a human had
just created through the browser.

Phase 4.5 unifies the two front doors:

1. MCP ``join_game`` delegates to ``PersistentGameController.join_game``
   for roster mutation, unit placement, and the ``lobby.player_joined``
   broadcast.
2. The controller's ``join_game`` accepts both ``waiting`` and ``created``
   statuses so the legacy MCP ``create_game`` flow keeps working.
3. MCP-origin keys still leave ``user_identity_id`` null; human-origin
   keys carry the attributing ``UserIdentity.id``.

This test file locks in the cross-front-door invariant end-to-end: human
creates via BFF → MCP agent calls ``join_game`` → both seats appear →
``lobby.player_joined`` fan-out observed by a subscribed WebSocket →
agent's key has no ``user_identity_id``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete
from starlette.websockets import WebSocketDisconnect

from backend.src.api.websocket import manager
from backend.src.auth import create_player_key
from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerAction,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
    UserIdentity,
)
from backend.src.database.repository import GameRepository
from backend.src.main import app
from backend.src.mcp_server.server import create_mcp_server

ALG = "HS256"
PREFIX = "phase45_"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def mcp() -> Any:
    return create_mcp_server()


async def _mcp_call(mcp: Any, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await mcp.call_tool(tool, args)
    if isinstance(result, tuple):
        return result[1]  # type: ignore[return-value]
    return json.loads(result[0].text)  # type: ignore[union-attr]


@pytest_asyncio.fixture
async def _clean_rows() -> None:
    await init_db()
    async with async_session_factory() as session:
        for model in (
            PlayerApiKey,
            GameSnapshot,
            TurnSnapshot,
            TurnAction,
            PlayerAction,
            GameTurn,
            Game,
        ):
            await session.execute(
                delete(model).where(model.game_id.like(f"{PREFIX}%"))
                if hasattr(model, "game_id")
                else delete(model).where(model.id.like(f"{PREFIX}%"))
            )
        await session.execute(
            delete(UserIdentity).where(UserIdentity.email.like("%@phase45.example.com"))
        )
        await session.commit()
    manager._by_game.clear()
    yield
    async with async_session_factory() as session:
        for model in (
            PlayerApiKey,
            GameSnapshot,
            TurnSnapshot,
            TurnAction,
            PlayerAction,
            GameTurn,
            Game,
        ):
            await session.execute(
                delete(model).where(model.game_id.like(f"{PREFIX}%"))
                if hasattr(model, "game_id")
                else delete(model).where(model.id.like(f"{PREFIX}%"))
            )
        await session.execute(
            delete(UserIdentity).where(UserIdentity.email.like("%@phase45.example.com"))
        )
        await session.commit()
    manager._by_game.clear()


def _mint_jwt(uid: int, *, email: str | None = None) -> str:
    now = int(time.time())
    payload: dict = {"sub": str(uid), "iat": now, "exp": now + 3600}
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, settings.auth_secret, algorithm=ALG)


async def _seed_identity(email: str) -> int:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        identity = await repo.upsert_user_identity_by_email(email)
        await session.commit()
        return identity.id


def _game_id(suffix: str) -> str:
    return f"{PREFIX}{suffix}_{int(time.time() * 1000000)}"


class TestMcpJoinWaitingLobby:
    """MCP join_game must accept ``waiting`` lobbies created via the BFF."""

    @pytest.mark.asyncio
    async def test_mcp_agent_joins_human_created_waiting_lobby(
        self, client: TestClient, mcp: Any, _clean_rows: None
    ) -> None:
        uid = await _seed_identity("creator@phase45.example.com")
        token = _mint_jwt(uid, email="creator@phase45.example.com")
        game_id = _game_id("waitjoin")

        # Human creates a lobby via the JWT-gated REST path → status "waiting".
        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["game"]["status"] == "waiting"

        # MCP agent joins the waiting lobby — used to error on the old
        # "can only join games in 'created' status" guard.
        result = await _mcp_call(
            mcp, "join_game", {"game_id": game_id, "player_name": "agent"}
        )
        assert "error" not in result, result
        assert result["player"] == "agent"
        assert result["api_key"].startswith("fx_")

        # Both seats appear in the roster.
        async with async_session_factory() as session:
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            assert game is not None
            assert "alice" in game.players
            assert "agent" in game.players

    @pytest.mark.asyncio
    async def test_mcp_join_fires_lobby_player_joined_broadcast(
        self, client: TestClient, mcp: Any, _clean_rows: None
    ) -> None:
        uid = await _seed_identity("creator2@phase45.example.com")
        token = _mint_jwt(uid, email="creator2@phase45.example.com")
        game_id = _game_id("wsfan")

        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        alice_key = resp.json()["api_key"]

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as ws:
            ws.receive_json()  # discard welcome frame

            result = await _mcp_call(
                mcp, "join_game", {"game_id": game_id, "player_name": "agent"}
            )
            assert "error" not in result, result

            event = ws.receive_json()
            assert event["type"] == "lobby.player_joined"
            assert event["player_id"] == "agent"
            assert "alice" in event["players"]
            assert "agent" in event["players"]

    @pytest.mark.asyncio
    async def test_mcp_minted_key_has_null_user_identity_id(
        self, client: TestClient, mcp: Any, _clean_rows: None
    ) -> None:
        uid = await _seed_identity("creator3@phase45.example.com")
        token = _mint_jwt(uid, email="creator3@phase45.example.com")
        game_id = _game_id("attrib")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        await _mcp_call(mcp, "join_game", {"game_id": game_id, "player_name": "agent"})

        async with async_session_factory() as session:
            repo = GameRepository(session)
            alice_row = await repo.get_player_api_key(game_id, "alice")
            agent_row = await repo.get_player_api_key(game_id, "agent")
            assert alice_row is not None
            assert agent_row is not None
            # Human-origin key is attributed; MCP-origin key is not.
            assert alice_row.user_identity_id == uid
            assert agent_row.user_identity_id is None


class TestMcpLegacyCreatedRegression:
    """No regression on the MCP-only ``create_game`` → ``join_game`` flow."""

    @pytest.mark.asyncio
    async def test_mcp_agent_can_still_join_legacy_created_game(
        self, mcp: Any, _clean_rows: None
    ) -> None:
        data = await _mcp_call(
            mcp, "create_game", {"players": ["alice", "bob"], "seed": 7}
        )
        game_id = data["game_id"]

        # The legacy path lands at ``status == "created"``. A third seat
        # should open up to 8 (not to player_slots which is 2 here).
        result = await _mcp_call(
            mcp, "join_game", {"game_id": game_id, "player_name": "charlie"}
        )
        assert "error" not in result, result
        assert result["player"] == "charlie"

        # Starting units were placed: alice's view should show her own
        # worker+scout, and once charlie joins the global state should
        # contain 6 units total (2 per player × 3 players).
        async with async_session_factory() as session:
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            assert game is not None
            assert "charlie" in game.players
            assert len(game.state["units"]) == 6

    @pytest.mark.asyncio
    async def test_mcp_join_rejects_ended_game(
        self, mcp: Any, _clean_rows: None
    ) -> None:
        data = await _mcp_call(
            mcp, "create_game", {"players": ["alice", "bob"], "seed": 7}
        )
        game_id = data["game_id"]

        async with async_session_factory() as session:
            repo = GameRepository(session)
            await repo.end_game(game_id, winner="alice", victory_type="score")
            await session.commit()

        result = await _mcp_call(
            mcp, "join_game", {"game_id": game_id, "player_name": "charlie"}
        )
        assert "error" in result


class TestMcpJoinDuplicatePlayer:
    @pytest.mark.asyncio
    async def test_duplicate_seat_rejected_on_waiting_lobby(
        self, client: TestClient, mcp: Any, _clean_rows: None
    ) -> None:
        uid = await _seed_identity("creator4@phase45.example.com")
        token = _mint_jwt(uid, email="creator4@phase45.example.com")
        game_id = _game_id("dup")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 3},
            headers={"Authorization": f"Bearer {token}"},
        )

        # First join succeeds.
        first = await _mcp_call(
            mcp, "join_game", {"game_id": game_id, "player_name": "agent"}
        )
        assert "error" not in first

        # Same name again is rejected by the unified controller path.
        second = await _mcp_call(
            mcp, "join_game", {"game_id": game_id, "player_name": "agent"}
        )
        assert "error" in second


class TestMcpJoinMissingCredentialsUnaffected:
    """Sanity: a WebSocket subscriber without a key still can't observe."""

    @pytest.mark.asyncio
    async def test_ws_without_key_on_waiting_lobby_is_unauthorized(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        uid = await _seed_identity("creator5@phase45.example.com")
        token = _mint_jwt(uid, email="creator5@phase45.example.com")
        game_id = _game_id("noauth")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/events?game_id={game_id}") as ws:
                ws.receive_text()


# Keep the ``create_player_key`` import live so callers know where MCP
# keys come from even if no test in this file calls it directly.
_ = create_player_key
