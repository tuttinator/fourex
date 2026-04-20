"""Tests for Phase 6 turn-submission visibility.

Covers the two backend surfaces the frontend's per-opponent
"deciding" vs "submitted" panel depends on:

1. ``turn.submitted`` WebSocket broadcast emitted by both REST
   (``PersistentGameController.submit_player_actions``) and MCP
   (``submit_actions`` tool) paths immediately after upserting the
   player's ``turn_actions`` row. The payload carries the full roster
   of players who have submitted so far so the UI can trust the
   snapshot rather than replaying deltas.

2. ``GET /games/{id}/turn-submissions`` — hydration surface for the
   same roster so a page refresh doesn't lose visibility.
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
from backend.src.main import app

_GAME_PREFIX = "phase6"


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


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _start_game(client: TestClient, game_id: str, players: list[str]) -> None:
    resp = client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": players, "seed": 42},
    )
    assert resp.status_code == 200


def _collect_frames_until(ws, target_type: str, limit: int = 15) -> list[dict]:
    """Drain WS frames until we see ``target_type`` or exhaust the budget."""
    seen: list[dict] = []
    for _ in range(limit):
        frame = ws.receive_json()
        seen.append(frame)
        if frame["type"] == target_type:
            return seen
    raise AssertionError(
        f"{target_type} not seen in {limit} frames; saw {[f['type'] for f in seen]}"
    )


class TestTurnSubmittedBroadcast:
    @pytest.mark.asyncio
    async def test_emitted_on_first_submission(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        """When one player of two submits, a single turn.submitted fires.

        turn.resolved must NOT fire yet — the turn is still waiting on
        bob. The submitted_players snapshot lists only alice.
        """
        game_id = _game_id("first")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as ws:
            ws.receive_json()  # welcome

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.submit_player_actions(game_id, "alice", [])
                await session.commit()

            frames = _collect_frames_until(ws, "turn.submitted", limit=5)
            submitted = frames[-1]
            assert submitted["type"] == "turn.submitted"
            assert submitted["game_id"] == game_id
            assert submitted["player_id"] == "alice"
            assert submitted["turn"] >= 0
            assert submitted["submitted_players"] == ["alice"]

    @pytest.mark.asyncio
    async def test_emitted_before_turn_resolved_on_last_submission(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        """The second player's submit emits turn.submitted then turn.resolved.

        Order matters: the frontend relies on turn.submitted arriving
        first so the "bob submitted" indicator lights up before the
        whole turn collapses on turn.resolved.
        """
        game_id = _game_id("order")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as ws:
            ws.receive_json()  # welcome

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.submit_player_actions(game_id, "alice", [])
                await controller.submit_player_actions(game_id, "bob", [])
                await session.commit()

            # Drain until turn.resolved and assert turn.submitted appeared
            # at least once for bob before it.
            seen_types: list[str] = []
            bob_submitted_index: int | None = None
            resolved_index: int | None = None
            for i in range(20):
                frame = ws.receive_json()
                seen_types.append(frame["type"])
                if (
                    frame["type"] == "turn.submitted"
                    and frame.get("player_id") == "bob"
                    and bob_submitted_index is None
                ):
                    bob_submitted_index = i
                    assert set(frame["submitted_players"]) == {"alice", "bob"}
                if frame["type"] == "turn.resolved":
                    resolved_index = i
                    break
            assert bob_submitted_index is not None, (
                f"bob's turn.submitted missing; saw {seen_types}"
            )
            assert resolved_index is not None, (
                f"turn.resolved never fired; saw {seen_types}"
            )
            assert bob_submitted_index < resolved_index, (
                f"expected turn.submitted before turn.resolved; saw {seen_types}"
            )

    @pytest.mark.asyncio
    async def test_resubmission_emits_again_with_same_snapshot(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        """Resubmitting the same player's batch re-fires turn.submitted.

        upsert_turn_action keeps the set idempotent, so the roster
        snapshot stays stable — but the event still fires so connected
        clients can refresh any "last submitted at" detail.
        """
        game_id = _game_id("resub")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as ws:
            ws.receive_json()  # welcome

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.submit_player_actions(game_id, "alice", [])
                await session.commit()

            first = _collect_frames_until(ws, "turn.submitted", limit=5)[-1]
            assert first["submitted_players"] == ["alice"]

            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.submit_player_actions(game_id, "alice", [])
                await session.commit()

            second = _collect_frames_until(ws, "turn.submitted", limit=5)[-1]
            assert second["player_id"] == "alice"
            assert second["submitted_players"] == ["alice"]


class TestTurnSubmissionsEndpoint:
    def test_missing_api_key_rejected(self, client: TestClient) -> None:
        resp = client.get("/api/v1/games/anything/turn-submissions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_game_key_rejected(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_a = _game_id("wg_a")
        game_b = _game_id("wg_b")
        _start_game(client, game_a, ["alice", "bob"])
        _start_game(client, game_b, ["alice", "bob"])
        key_a = await _mint_key(game_a, "alice")

        resp = client.get(
            f"/api/v1/games/{game_b}/turn-submissions",
            headers=_auth(key_a),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_roster_before_any_submission(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("empty")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")

        resp = client.get(
            f"/api/v1/games/{game_id}/turn-submissions",
            headers=_auth(alice_key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game_id
        assert data["turn"] >= 0
        assert set(data["players"]) == {"alice", "bob"}
        assert data["submitted_players"] == []

    @pytest.mark.asyncio
    async def test_roster_reflects_one_submission(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("one")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")

        async with async_session_factory() as session:
            controller = get_persistent_game_controller(session)
            await controller.submit_player_actions(game_id, "alice", [])
            await session.commit()

        resp = client.get(
            f"/api/v1/games/{game_id}/turn-submissions",
            headers=_auth(alice_key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["submitted_players"] == ["alice"]

    @pytest.mark.asyncio
    async def test_roster_resets_on_new_turn(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        """After both players submit and the turn advances, the roster is empty.

        The endpoint keys off ``state.turn`` so once resolve_turn bumps
        the turn counter, previous turn's submissions no longer appear.
        """
        game_id = _game_id("reset")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")

        async with async_session_factory() as session:
            controller = get_persistent_game_controller(session)
            await controller.submit_player_actions(game_id, "alice", [])
            await controller.submit_player_actions(game_id, "bob", [])
            await session.commit()

        resp = client.get(
            f"/api/v1/games/{game_id}/turn-submissions",
            headers=_auth(alice_key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["turn"] >= 1  # advanced past the 0th turn
        assert data["submitted_players"] == []
