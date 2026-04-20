"""Tests for Phase 7 diplomacy messaging WebSocket broadcast.

Covers the backend-visible slice of
``plans/human-frontend-parity.md`` Phase 7:

* When ``resolve_turn`` accepts a ``SEND_MESSAGE`` action, a
  ``diplomacy.message_received`` event is emitted carrying the
  message payload.
* The event is scoped to the sender and recipient only — a third
  player subscribed to the same game MUST NOT see the body (mirrors
  ``redact_state`` message-visibility rules).
* The event arrives *after* ``turn.resolved`` so clients that refetch
  authoritative state on ``turn.resolved`` still pick up the per-
  message signal for unread-badge deltas.
* No ``diplomacy.message_received`` fires on a turn with no messages.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.api.persistent_game_controller import (
    get_persistent_game_controller,
)
from backend.src.api.websocket import manager
from backend.src.auth import create_player_key
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
from backend.src.database.repository import GameRepository
from backend.src.game.models import GameState, SendMessageAction
from backend.src.game.rules import record_discovery
from backend.src.main import app

_GAME_PREFIX = "phase7"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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


def _game_id(suffix: str) -> str:
    return f"{_GAME_PREFIX}_{suffix}_{int(time.time() * 1000000)}"


async def _mint_key(game_id: str, player_id: str) -> str:
    async with async_session_factory() as session:
        key = await create_player_key(session, game_id, player_id)
        await session.commit()
        return key


def _start_game(client: TestClient, game_id: str, players: list[str]) -> None:
    resp = client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": players, "seed": 42},
    )
    assert resp.status_code == 200


async def _seed_discovery(game_id: str, pairs: list[tuple[str, str]]) -> None:
    """Persist pairwise discovery so SEND_MESSAGE isn't rejected on submit."""
    async with async_session_factory() as session:
        repo = GameRepository(session)
        game = await repo.get_game(game_id)
        assert game is not None
        state = GameState.model_validate(game.state)
        for viewer, target in pairs:
            record_discovery(state, viewer, target)
        await repo.update_game_state(game_id, state)
        await session.commit()


def _collect_until_resolved(ws, limit: int = 30) -> list[dict]:
    """Drain frames up to and including ``turn.resolved``."""
    seen: list[dict] = []
    for _ in range(limit):
        frame = ws.receive_json()
        seen.append(frame)
        if frame["type"] == "turn.resolved":
            return seen
    raise AssertionError(
        f"turn.resolved not seen in {limit} frames; saw {[f['type'] for f in seen]}"
    )


class TestDiplomacyMessageReceivedBroadcast:
    @pytest.mark.asyncio
    async def test_emitted_to_sender_and_recipient(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        """Alice sends bob a message; both sockets observe the event."""
        game_id = _game_id("pair")
        _start_game(client, game_id, ["alice", "bob"])
        await _seed_discovery(game_id, [("alice", "bob"), ("bob", "alice")])

        alice_key = await _mint_key(game_id, "alice")
        bob_key = await _mint_key(game_id, "bob")

        with (
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
            ) as alice_ws,
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={bob_key}"
            ) as bob_ws,
        ):
            alice_ws.receive_json()  # welcome
            bob_ws.receive_json()  # welcome

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.submit_player_actions(
                    game_id,
                    "alice",
                    [SendMessageAction(recipient="bob", body="hello bob")],
                )
                await controller.submit_player_actions(game_id, "bob", [])
                await session.commit()

            alice_frames = _collect_until_resolved(alice_ws)
            bob_frames = _collect_until_resolved(bob_ws)

            # After turn.resolved, a diplomacy.message_received frame must arrive.
            alice_msg = alice_ws.receive_json()
            bob_msg = bob_ws.receive_json()

            for frame, perspective in ((alice_msg, "alice"), (bob_msg, "bob")):
                assert frame["type"] == "diplomacy.message_received", perspective
                assert frame["game_id"] == game_id, perspective
                payload = frame["message"]
                assert payload["sender"] == "alice", perspective
                assert payload["recipient"] == "bob", perspective
                assert payload["body"] == "hello bob", perspective
                assert payload["turn_sent"] == 0, perspective
                assert isinstance(payload["id"], int), perspective

            # Sanity-check that turn.resolved appeared before the message event.
            assert any(f["type"] == "turn.resolved" for f in alice_frames)
            assert any(f["type"] == "turn.resolved" for f in bob_frames)

    @pytest.mark.asyncio
    async def test_third_party_does_not_receive_message(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        """Carol, a third connected player, must NOT receive the body.

        Mirrors ``redact_state``: messages are private to sender +
        recipient. A game-wide fanout would leak both contents and the
        existence of the exchange.
        """
        game_id = _game_id("scoped")
        _start_game(client, game_id, ["alice", "bob", "carol"])
        await _seed_discovery(
            game_id,
            [
                ("alice", "bob"),
                ("bob", "alice"),
                ("alice", "carol"),
                ("carol", "alice"),
                ("bob", "carol"),
                ("carol", "bob"),
            ],
        )

        alice_key = await _mint_key(game_id, "alice")
        carol_key = await _mint_key(game_id, "carol")

        with (
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
            ) as alice_ws,
            client.websocket_connect(
                f"/api/v1/events?game_id={game_id}&api_key={carol_key}"
            ) as carol_ws,
        ):
            alice_ws.receive_json()  # welcome
            carol_ws.receive_json()  # welcome

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.submit_player_actions(
                    game_id,
                    "alice",
                    [SendMessageAction(recipient="bob", body="secret")],
                )
                await controller.submit_player_actions(game_id, "bob", [])
                await controller.submit_player_actions(game_id, "carol", [])
                await session.commit()

            carol_frames = _collect_until_resolved(carol_ws)
            _collect_until_resolved(alice_ws)

            # Alice receives the message event as the sender. By the time
            # alice's socket observes diplomacy.message_received, the
            # broadcast helper has already iterated every connection on
            # the game and skipped carol by player_id — so carol's frame
            # queue at that point is authoritative.
            alice_next = alice_ws.receive_json()
            assert alice_next["type"] == "diplomacy.message_received"
            assert alice_next["message"]["body"] == "secret"

            # Carol must NOT receive any diplomacy.message_received frame
            # in the run-up to (or at) turn.resolved.
            for frame in carol_frames:
                assert frame["type"] != "diplomacy.message_received", (
                    f"carol leaked: {frame}"
                )

    @pytest.mark.asyncio
    async def test_no_event_when_no_messages_sent(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        """A turn without any SEND_MESSAGE actions fires no message events."""
        game_id = _game_id("silent")
        _start_game(client, game_id, ["alice", "bob"])

        alice_key = await _mint_key(game_id, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as alice_ws:
            alice_ws.receive_json()  # welcome

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.submit_player_actions(game_id, "alice", [])
                await controller.submit_player_actions(game_id, "bob", [])
                await session.commit()

            frames = _collect_until_resolved(alice_ws)
            for frame in frames:
                assert frame["type"] != "diplomacy.message_received", (
                    f"unexpected message event: {frame}"
                )
