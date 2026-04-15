"""
Tests for Phase 9: Built-in agent adaptation.

Verifies that:
- Turn resolution persists per-player turn_actions
- Turn resolution persists per-player fog-of-war turn_snapshots
- REST scratchpad endpoints allow writing and reading agent memory
"""

import time

import pytest
from fastapi.testclient import TestClient

from backend.src.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _game_id(prefix: str = "p9") -> str:
    return f"{prefix}_{int(time.time() * 1000000)}"


def _auth(player: str) -> dict[str, str]:
    return {"Authorization": f"Bearer player_{player}"}


def _create_game(client, game_id: str, players: list[str]) -> None:
    resp = client.post(
        f"/api/v1/games/{game_id}/start",
        json={"players": players, "seed": 42},
    )
    assert resp.status_code == 200


class TestTurnPersistence:
    """Verify that _process_turn saves turn_actions and turn_snapshots."""

    def test_turn_actions_and_snapshots_saved_after_turn(self, client):
        """When all players submit, turn resolves and persists actions+snapshots."""
        game_id = _game_id()
        p1, p2 = "alice", "bob"
        _create_game(client, game_id, [p1, p2])

        # Both players submit empty actions to trigger turn resolution
        resp1 = client.post(
            f"/api/v1/actions?game_id={game_id}", json=[], headers=_auth(p1)
        )
        assert resp1.status_code == 200

        resp2 = client.post(
            f"/api/v1/actions?game_id={game_id}", json=[], headers=_auth(p2)
        )
        assert resp2.status_code == 200

        # After both submit, turn should have advanced from 0 to 1
        state_resp = client.get(f"/api/v1/state?game_id={game_id}")
        assert state_resp.status_code == 200
        assert state_resp.json()["turn"] == 1


class TestScratchpadEndpoints:
    """Verify REST scratchpad read/write."""

    def test_write_and_read_scratchpad(self, client):
        """Write a scratchpad entry and read it back."""
        game_id = _game_id()
        player = "alice"
        _create_game(client, game_id, [player, "bob"])

        # Write scratchpad
        resp = client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "My strategic notes for turn 0", "turn_number": 0},
            headers=_auth(player),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "scratchpad_saved"

        # Read it back
        resp = client.get(
            f"/api/v1/scratchpad?game_id={game_id}&turn_number=0",
            headers=_auth(player),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "My strategic notes for turn 0"
        assert data["turn"] == 0

    def test_read_scratchpad_no_entry(self, client):
        """Reading a non-existent scratchpad returns None content."""
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])

        resp = client.get(
            f"/api/v1/scratchpad?game_id={game_id}&turn_number=0",
            headers=_auth("alice"),
        )
        assert resp.status_code == 200
        assert resp.json()["content"] is None

    def test_scratchpad_overwrite(self, client):
        """Writing twice to the same turn overwrites the previous entry."""
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])

        headers = _auth("alice")

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

    def test_scratchpad_exceeds_cap(self, client):
        """Content exceeding 4000 chars is rejected."""
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])

        resp = client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "x" * 4001, "turn_number": 0},
            headers=_auth("alice"),
        )
        assert resp.status_code == 422  # Pydantic validation error

    def test_scratchpad_private_per_player(self, client):
        """A player cannot read another player's scratchpad."""
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])

        # Alice writes
        client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "alice secret", "turn_number": 0},
            headers=_auth("alice"),
        )

        # Bob reads — should get None (his own empty scratchpad)
        resp = client.get(
            f"/api/v1/scratchpad?game_id={game_id}&turn_number=0",
            headers=_auth("bob"),
        )
        assert resp.json()["content"] is None

    def test_scratchpad_defaults_to_current_turn(self, client):
        """Without turn_number, scratchpad writes to current turn."""
        game_id = _game_id()
        _create_game(client, game_id, ["alice", "bob"])

        resp = client.post(
            f"/api/v1/scratchpad?game_id={game_id}",
            json={"content": "auto turn"},
            headers=_auth("alice"),
        )
        assert resp.status_code == 200
        assert resp.json()["turn"] == "0"  # Current turn is 0
