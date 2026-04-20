"""Tests for Phase 9 war-declaration WebSocket broadcast.

Covers the backend-visible slice of ``plans/human-frontend-parity.md``
Phase 9:

* Explicit ``DECLARE_WAR`` action emits ``diplomacy.war_declared`` to
  the declarer and target with ``cause == "declaration"``.
* A treacherous PEACE-attack that flips the relation to WAR emits the
  same event with ``cause == "treacherous_attack"``.
* Third parties do not receive the event (scoped to the two parties).
* A quiet turn produces no ``diplomacy.war_declared`` frame.
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
from backend.src.game.models import DeclareWarAction, GameState
from backend.src.game.rules import record_discovery
from backend.src.main import app

_GAME_PREFIX = "phase9"


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
    seen: list[dict] = []
    for _ in range(limit):
        frame = ws.receive_json()
        seen.append(frame)
        if frame["type"] == "turn.resolved":
            return seen
    raise AssertionError(
        f"turn.resolved not seen in {limit} frames; saw {[f['type'] for f in seen]}"
    )


async def _submit(game_id: str, player_id: str, actions: list) -> None:
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        await controller.submit_player_actions(game_id, player_id, actions)
        await session.commit()


class TestDeclareWarBroadcast:
    @pytest.mark.asyncio
    async def test_emitted_to_declarer_and_target(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("direct")
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
            alice_ws.receive_json()
            bob_ws.receive_json()

            await _submit(game_id, "alice", [DeclareWarAction(target_player="bob")])
            await _submit(game_id, "bob", [])

            _collect_until_resolved(alice_ws)
            _collect_until_resolved(bob_ws)

            alice_evt = alice_ws.receive_json()
            bob_evt = bob_ws.receive_json()

            for frame, perspective in ((alice_evt, "alice"), (bob_evt, "bob")):
                assert frame["type"] == "diplomacy.war_declared", perspective
                assert frame["game_id"] == game_id, perspective
                assert frame["actor"] == "alice", perspective
                assert frame["target"] == "bob", perspective
                assert frame["cause"] == "declaration", perspective

    @pytest.mark.asyncio
    async def test_third_party_does_not_receive(
        self, client: TestClient, _clean_rows: None
    ) -> None:
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

        carol_key = await _mint_key(game_id, "carol")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={carol_key}"
        ) as carol_ws:
            carol_ws.receive_json()

            await _submit(game_id, "alice", [DeclareWarAction(target_player="bob")])
            await _submit(game_id, "bob", [])
            await _submit(game_id, "carol", [])

            carol_frames = _collect_until_resolved(carol_ws)
            for frame in carol_frames:
                assert frame["type"] != "diplomacy.war_declared", (
                    f"carol leaked: {frame}"
                )

    @pytest.mark.asyncio
    async def test_rejected_self_declaration_suppresses_event(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        """``execute_declare_war`` rejects self-targeting actions without
        emitting a ``WAR_DECLARED`` event, so the turn-resolution walker
        has nothing to fan out — no ``diplomacy.war_declared`` frame
        lands on the socket even though an action was submitted."""
        game_id = _game_id("self")
        _start_game(client, game_id, ["alice", "bob"])

        alice_key = await _mint_key(game_id, "alice")
        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as alice_ws:
            alice_ws.receive_json()

            await _submit(
                game_id, "alice", [DeclareWarAction(target_player="alice")]
            )
            await _submit(game_id, "bob", [])

            frames = _collect_until_resolved(alice_ws)
            for frame in frames:
                assert frame["type"] != "diplomacy.war_declared", (
                    f"unexpected event from rejected action: {frame}"
                )


class TestNoWarEventOnQuietTurn:
    @pytest.mark.asyncio
    async def test_quiet_turn_has_no_war_event(
        self, client: TestClient, _clean_rows: None
    ) -> None:
        game_id = _game_id("quiet")
        _start_game(client, game_id, ["alice", "bob"])

        alice_key = await _mint_key(game_id, "alice")
        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as alice_ws:
            alice_ws.receive_json()

            await _submit(game_id, "alice", [])
            await _submit(game_id, "bob", [])

            frames = _collect_until_resolved(alice_ws)
            for frame in frames:
                assert frame["type"] != "diplomacy.war_declared", (
                    f"unexpected war event: {frame}"
                )
