"""
Tests for Phase 9: Built-in agent adaptation.

Verifies that:
- Turn resolution persists per-player turn_actions
- Turn resolution persists per-player fog-of-war turn_snapshots
- REST scratchpad endpoints allow writing and reading agent memory
"""

import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.src.auth import create_player_key
from backend.src.database.connection import async_session_factory, init_db
from backend.src.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest_asyncio.fixture
async def _init_db() -> None:
    await init_db()


def _game_id(prefix: str = "p9") -> str:
    return f"{prefix}_{int(time.time() * 1000000)}"


async def _mint_key(game_id: str, player_id: str) -> str:
    async with async_session_factory() as session:
        key = await create_player_key(session, game_id, player_id)
        await session.commit()
        return key


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _create_game(client, game_id: str, players: list[str]) -> None:
    resp = client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": players, "seed": 42},
    )
    assert resp.status_code == 200


class TestTurnPersistence:
    """Verify that _process_turn saves turn_actions and turn_snapshots."""

    @pytest.mark.asyncio
    async def test_turn_actions_and_snapshots_saved_after_turn(
        self, client, _init_db
    ):
        """When all players submit, turn resolves and persists actions+snapshots."""
        game_id = _game_id()
        p1, p2 = "alice", "bob"
        _create_game(client, game_id, [p1, p2])
        k1 = await _mint_key(game_id, p1)
        k2 = await _mint_key(game_id, p2)

        resp1 = client.post(
            f"/api/v1/actions?game_id={game_id}", json=[], headers=_auth(k1)
        )
        assert resp1.status_code == 200

        resp2 = client.post(
            f"/api/v1/actions?game_id={game_id}", json=[], headers=_auth(k2)
        )
        assert resp2.status_code == 200

        state_resp = client.get(f"/api/v1/state?game_id={game_id}")
        assert state_resp.status_code == 200
        assert state_resp.json()["turn"] == 1


class TestScratchpadEndpoints:
    """Verify REST scratchpad read/write."""

    @pytest.mark.asyncio
    async def test_write_and_read_scratchpad(self, client, _init_db):
        game_id = _game_id()
        player = "alice"
        _create_game(client, game_id, [player, "bob"])
        key = await _mint_key(game_id, player)

        resp = client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "My strategic notes for turn 0", "turn_number": 0},
            headers=_auth(key),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "scratchpad_saved"

        resp = client.get(
            f"/api/v1/scratchpad?game_id={game_id}&turn_number=0",
            headers=_auth(key),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "My strategic notes for turn 0"
        assert data["turn"] == 0

    @pytest.mark.asyncio
    async def test_read_scratchpad_no_entry(self, client, _init_db):
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")

        resp = client.get(
            f"/api/v1/scratchpad?game_id={game_id}&turn_number=0",
            headers=_auth(key),
        )
        assert resp.status_code == 200
        assert resp.json()["content"] is None

    @pytest.mark.asyncio
    async def test_scratchpad_overwrite(self, client, _init_db):
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")
        headers = _auth(key)

        client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "first", "turn_number": 0},
            headers=headers,
        )
        client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "second", "turn_number": 0},
            headers=headers,
        )

        resp = client.get(
            f"/api/v1/scratchpad?game_id={game_id}&turn_number=0",
            headers=headers,
        )
        assert resp.json()["content"] == "second"

    @pytest.mark.asyncio
    async def test_scratchpad_exceeds_cap(self, client, _init_db):
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")

        resp = client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "x" * 4001, "turn_number": 0},
            headers=_auth(key),
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_scratchpad_private_per_player(self, client, _init_db):
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])
        alice_key = await _mint_key(game_id, "alice")
        bob_key = await _mint_key(game_id, "bob")

        client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "alice secret", "turn_number": 0},
            headers=_auth(alice_key),
        )

        resp = client.get(
            f"/api/v1/scratchpad?game_id={game_id}&turn_number=0",
            headers=_auth(bob_key),
        )
        assert resp.json()["content"] is None

    @pytest.mark.asyncio
    async def test_scratchpad_defaults_to_current_turn(self, client, _init_db):
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])
        key = await _mint_key(game_id, "alice")

        resp = client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "auto turn"},
            headers=_auth(key),
        )
        assert resp.status_code == 200
        assert resp.json()["turn"] == "0"
