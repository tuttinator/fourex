"""Tests for Phase 4 (backend) gameplay-tracer surface.

Covers the two new bits the frontend move-and-end-turn slice depends on:

1. ``GET /games/{game_id}/units/{unit_id}/valid-moves`` — server-backed
   valid-move list for highlighting a selected unit's reachable tiles.
   Reuses ``rules.get_valid_moves`` so the client and the server-side
   validator in ``resolve_turn`` can't drift.
2. ``turn.resolved`` WebSocket emission after ``resolve_turn()`` commits.
   The frontend uses this to invalidate its game-state query and clear
   the local action queue.
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

_GAME_PREFIX = "tracer"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def _clean_tracer_rows() -> None:
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
    """Use the legacy auth-free create-and-start path to seed test games."""
    resp = client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": players, "seed": 42},
    )
    assert resp.status_code == 200


async def _first_unit_id_for(game_id: str, player_id: str) -> int:
    async with async_session_factory() as session:
        controller = get_persistent_game_controller(session)
        state = await controller.get_game_state(game_id)
        assert state is not None
        for unit in state.units.values():
            if unit.owner == player_id:
                return unit.id
        raise AssertionError(f"no units for {player_id} in {game_id}")


class TestValidMovesEndpoint:
    def test_missing_api_key_rejected(self, client: TestClient) -> None:
        """No bearer header → 401 (surface matches the rest of gameplay)."""
        resp = client.get("/api/v1/games/anything/units/1/valid-moves")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_game_key_rejected(
        self, client: TestClient, _clean_tracer_rows: None
    ) -> None:
        """Key minted for game A is forbidden on game B's valid-moves."""
        game_a = _game_id("wrong_a")
        game_b = _game_id("wrong_b")
        _start_game(client, game_a, ["alice", "bob"])
        _start_game(client, game_b, ["alice", "bob"])
        key_a = await _mint_key(game_a, "alice")

        resp = client.get(
            f"/api/v1/games/{game_b}/units/1/valid-moves",
            headers=_auth(key_a),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_moves_for_own_unit(
        self, client: TestClient, _clean_tracer_rows: None
    ) -> None:
        """Valid-moves for a friendly unit returns a non-empty tile list.

        Starting units are placed on passable terrain inside a margin, so a
        worker (2 moves) or scout (3 moves) on turn 1 has at least one
        legal neighbour.
        """
        game_id = _game_id("happy")
        _start_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")
        unit_id = await _first_unit_id_for(game_id, "alice")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/{unit_id}/valid-moves",
            headers=_auth(key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game_id
        assert data["unit_id"] == unit_id
        assert data["moves_left"] >= 1
        assert isinstance(data["moves"], list)
        assert len(data["moves"]) >= 1
        sample = data["moves"][0]
        # Shape contract — the frontend highlighter keys on (x, y) and
        # renders terrain/resource hints on hover.
        for field in ("x", "y", "terrain", "distance"):
            assert field in sample

    @pytest.mark.asyncio
    async def test_enemy_unit_returns_404(
        self, client: TestClient, _clean_tracer_rows: None
    ) -> None:
        """Querying an opponent's unit with your own key 404s.

        The endpoint deliberately does not distinguish "unit not found"
        from "unit belongs to another player" so enemy unit IDs can't be
        enumerated via this surface.
        """
        game_id = _game_id("enemy")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")
        bob_unit = await _first_unit_id_for(game_id, "bob")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/{bob_unit}/valid-moves",
            headers=_auth(alice_key),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unknown_unit_returns_404(
        self, client: TestClient, _clean_tracer_rows: None
    ) -> None:
        game_id = _game_id("nounit")
        _start_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")

        resp = client.get(
            f"/api/v1/games/{game_id}/units/9999999/valid-moves",
            headers=_auth(key),
        )
        assert resp.status_code == 404


class TestTurnResolvedBroadcast:
    @pytest.mark.asyncio
    async def test_turn_resolved_emitted_after_all_submit(
        self, client: TestClient, _clean_tracer_rows: None
    ) -> None:
        """When the last player submits, the controller broadcasts turn.resolved.

        Mirrors the Phase 3 pattern: a subscriber on ``/events`` with a
        valid key receives the namespaced event and can invalidate its
        cached state. The legacy ``turn_end`` event is also emitted but
        this slice only asserts the new dot-namespaced name the frontend
        tracer subscribes to.
        """
        game_id = _game_id("resolved")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")

        with client.websocket_connect(
            f"/api/v1/events?game_id={game_id}&api_key={alice_key}"
        ) as ws:
            ws.receive_json()  # welcome frame

            # Both players submit an empty batch — the controller processes
            # the turn as soon as every seated player has submitted.
            async with async_session_factory() as session:
                controller = get_persistent_game_controller(session)
                await controller.submit_player_actions(game_id, "alice", [])
                await controller.submit_player_actions(game_id, "bob", [])
                await session.commit()

            # The controller fires turn_start, per-player action frames,
            # turn_end, and turn.resolved in that order. Walk forward
            # until we see the namespaced event the tracer cares about.
            seen_types: list[str] = []
            for _ in range(10):
                frame = ws.receive_json()
                seen_types.append(frame["type"])
                if frame["type"] == "turn.resolved":
                    assert frame["game_id"] == game_id
                    assert frame["turn"] >= 1
                    break
            else:  # pragma: no cover - defensive
                raise AssertionError(
                    f"turn.resolved not seen in first 10 frames; saw {seen_types}"
                )

    @pytest.mark.asyncio
    async def test_batch_actions_submit_atomically(
        self, client: TestClient, _clean_tracer_rows: None
    ) -> None:
        """``POST /actions`` accepts a multi-action queue in one request.

        The Phase 4 End Turn flow depends on "submit the whole queue in
        one call" — the endpoint's contract is that every action in the
        list applies against the same turn, so a partial apply is not
        possible. Empty batches are allowed (the frontend can ship a
        no-op turn).
        """
        game_id = _game_id("batch")
        _start_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")
        unit_id = await _first_unit_id_for(game_id, "alice")

        # Query a legal move so we don't need to replicate map-gen here.
        moves_resp = client.get(
            f"/api/v1/games/{game_id}/units/{unit_id}/valid-moves",
            headers=_auth(alice_key),
        )
        assert moves_resp.status_code == 200
        destinations = moves_resp.json()["moves"]
        assert destinations, "starting worker should have at least one legal move"
        target = destinations[0]

        batch = [
            {
                "type": "MOVE",
                "unit_id": unit_id,
                "to": {"x": target["x"], "y": target["y"]},
            }
        ]
        resp = client.post(
            f"/api/v1/actions?game_id={game_id}",
            json=batch,
            headers=_auth(alice_key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "actions_submitted"
        assert data["count"] == str(len(batch))
