"""Tests for Phase 3 WebSocket authentication and lobby event emission.

Covers the two invariants Phase 3 of human-frontend-parity bakes in:

1. ``/events`` requires a valid per-game API key at connect time. Missing,
   invalid, and game-mismatched keys all produce a close code so the
   client can distinguish auth failure from transport failure.
2. ``lobby.player_joined`` / ``lobby.player_left`` / ``lobby.started`` are
   broadcast to every connection subscribed to the game as the controller
   transitions through the waiting-lobby lifecycle.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete
from starlette.websockets import WebSocketDisconnect

from backend.src.api.persistent_game_controller import (
    get_persistent_game_controller,
)
from backend.src.api.websocket import (
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_UNAUTHORIZED,
    manager,
)
from backend.src.auth import create_player_key
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerApiKey,
    PlayerAction,
    TurnAction,
    TurnSnapshot,
)
from backend.src.database.repository import GameRepository
from backend.src.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def _clean_ws_rows() -> None:
    await init_db()
    async with async_session_factory() as session:
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(PlayerAction).where(PlayerAction.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(GameTurn).where(GameTurn.game_id.like("wsevt_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("wsevt_%")))
        await session.commit()
    # Drop any stale in-memory connections from a prior test run.
    manager._by_game.clear()
    yield
    async with async_session_factory() as session:
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(PlayerAction).where(PlayerAction.game_id.like("wsevt_%"))
        )
        await session.execute(
            delete(GameTurn).where(GameTurn.game_id.like("wsevt_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("wsevt_%")))
        await session.commit()
    manager._by_game.clear()


def _game_id(suffix: str) -> str:
    return f"wsevt_{suffix}_{int(time.time() * 1000000)}"


async def _seed_waiting_game(game_id: str, creator: str = "alice") -> None:
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        await controller.create_lobby(
            game_id=game_id,
            player_slots=2,
            map_width=10,
            map_height=10,
            seed=42,
            creator=creator,
        )
        await controller.join_game(game_id, creator)
        await session.commit()


async def _mint_key(game_id: str, player_id: str) -> str:
    async with async_session_factory() as session:
        key = await create_player_key(session, game_id, player_id)
        await session.commit()
        return key


class TestWebSocketAuth:
    @pytest.mark.asyncio
    async def test_missing_api_key_closes_unauthorized(
        self, client: TestClient, _clean_ws_rows: None
    ) -> None:
        game_id = _game_id("nokey")
        await _seed_waiting_game(game_id)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(
                f"/api/v1/events?game_id={game_id}"
            ) as ws:
                ws.receive_text()
        assert excinfo.value.code == WS_CLOSE_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_invalid_api_key_closes_unauthorized(
        self, client: TestClient, _clean_ws_rows: None
    ) -> None:
        game_id = _game_id("badkey")
        await _seed_waiting_game(game_id)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key=fx_notreal"
            ) as ws:
                ws.receive_text()
        assert excinfo.value.code == WS_CLOSE_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_key_for_wrong_game_closes_forbidden(
        self, client: TestClient, _clean_ws_rows: None
    ) -> None:
        game_a = _game_id("a")
        game_b = _game_id("b")
        await _seed_waiting_game(game_a, creator="alice")
        await _seed_waiting_game(game_b, creator="bob")
        alice_key = await _mint_key(game_a, "alice")
        # Try to connect to game B with alice's key for game A.
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(
                f"/api/v1/events?game_id={game_b}&api_key={alice_key}"
            ) as ws:
                ws.receive_text()
        assert excinfo.value.code == WS_CLOSE_FORBIDDEN

    @pytest.mark.asyncio
    async def test_valid_key_accepts_and_sends_welcome(
        self, client: TestClient, _clean_ws_rows: None
    ) -> None:
        game_id = _game_id("ok")
        await _seed_waiting_game(game_id)
        alice_key = await _mint_key(game_id, "alice")
        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as ws:
            welcome = ws.receive_json()
            assert welcome["type"] == "connected"
            assert welcome["game_id"] == game_id
            assert welcome["player_id"] == "alice"


class TestLobbyEvents:
    @pytest.mark.asyncio
    async def test_player_joined_fan_out(
        self, client: TestClient, _clean_ws_rows: None
    ) -> None:
        game_id = _game_id("joinfan")
        await _seed_waiting_game(game_id, creator="alice")
        alice_key = await _mint_key(game_id, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as ws:
            ws.receive_json()  # discard welcome frame
            # Simulate bob joining — controller broadcasts lobby.player_joined.
            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.join_game(game_id, "bob")
                await session.commit()

            event = ws.receive_json()
            assert event["type"] == "lobby.player_joined"
            assert event["player_id"] == "bob"
            assert event["players"] == ["alice", "bob"]

    @pytest.mark.asyncio
    async def test_player_left_fan_out(
        self, client: TestClient, _clean_ws_rows: None
    ) -> None:
        game_id = _game_id("leavefan")
        await _seed_waiting_game(game_id, creator="alice")
        async with async_session_factory() as session:
            controller = get_persistent_game_controller(session)
            await controller.join_game(game_id, "bob")
            await session.commit()
        alice_key = await _mint_key(game_id, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as ws:
            ws.receive_json()  # welcome
            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.leave_game(game_id, "bob")
                await session.commit()
            event = ws.receive_json()
            assert event["type"] == "lobby.player_left"
            assert event["player_id"] == "bob"
            assert event["players"] == ["alice"]

    @pytest.mark.asyncio
    async def test_lobby_started_fan_out(
        self, client: TestClient, _clean_ws_rows: None
    ) -> None:
        game_id = _game_id("startfan")
        await _seed_waiting_game(game_id, creator="alice")
        async with async_session_factory() as session:
            controller = get_persistent_game_controller(session)
            await controller.join_game(game_id, "bob")
            await session.commit()
        alice_key = await _mint_key(game_id, "alice")
        bob_key = await _mint_key(game_id, "bob")

        with (
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
            ) as ws_a,
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={bob_key}"
            ) as ws_b,
        ):
            ws_a.receive_json()  # welcome
            ws_b.receive_json()  # welcome

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.start_game(game_id, "alice")
                await session.commit()

            # Both subscribers should see the started event.
            event_a = ws_a.receive_json()
            event_b = ws_b.receive_json()
            assert event_a["type"] == "lobby.started"
            assert event_b["type"] == "lobby.started"
            assert event_a["game_id"] == game_id


class TestCrossGameIsolation:
    @pytest.mark.asyncio
    async def test_events_do_not_leak_across_games(
        self, client: TestClient, _clean_ws_rows: None
    ) -> None:
        game_a = _game_id("iso_a")
        game_b = _game_id("iso_b")
        await _seed_waiting_game(game_a, creator="alice")
        await _seed_waiting_game(game_b, creator="bob")
        alice_key = await _mint_key(game_a, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_a}&api_key={alice_key}"
        ) as ws:
            ws.receive_json()  # welcome

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.join_game(game_b, "charlie")
                await session.commit()

            # Alice is subscribed to game_a; the charlie join in game_b
            # must not arrive on her socket. Force a round-trip via ping
            # to flush any buffered frames and assert the next frame is
            # the pong, not a stray lobby.player_joined.
            ws.send_json({"type": "ping", "timestamp": 1})
            reply = ws.receive_json()
            assert reply["type"] == "pong"
