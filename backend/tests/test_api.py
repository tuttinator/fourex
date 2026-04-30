"""
Tests for FastAPI endpoints.

After Phase 2 of the human-frontend-parity plan the legacy ``player_*``
bearer-token shortcut is gone: every gameplay/diplomacy endpoint requires
a real per-game ``PlayerApiKey``. These tests mint that key directly
against the DB after setting the game up via the legacy
``POST /games/{id}/start`` flow (which itself is auth-free and creates
the game eagerly for test convenience).
"""

import time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from backend.src.auth import create_player_key
from backend.src.database.connection import async_session_factory, init_db
from backend.src.main import app


@pytest.fixture
def client() -> TestClient:
    """Test client fixture."""
    return TestClient(app)


@pytest_asyncio.fixture
async def _init_db() -> None:
    await init_db()


async def _mint_key(game_id: str, player_id: str) -> str:
    async with async_session_factory() as session:
        key = await create_player_key(session, game_id, player_id)
        await session.commit()
        return key


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestGameEndpoints:
    """Test game-related API endpoints."""

    def _game_id(self, prefix: str) -> str:
        return f"{prefix}_{int(time.time() * 1000000)}"

    def test_start_game(self, client):
        """Legacy create-and-start flow — auth-free for test convenience."""
        game_id = self._game_id("test_game")
        response = client.post(
            f"/api/v1/games/{game_id}/start",
            json={"players": ["player_1", "player_2"], "seed": 42},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "game_created"
        assert data["game_id"] == game_id

    def test_list_games(self, client):
        game_id = self._game_id("test_game")
        client.post(
            f"/api/v1/games/{game_id}/start",
            json={"players": ["player_1", "player_2"], "seed": 42},
        )

        response = client.get("/api/v1/games")
        assert response.status_code == 200
        data = response.json()
        assert "games" in data
        game_ids = [g["game_id"] for g in data["games"]]
        assert game_id in game_ids

    @pytest.mark.asyncio
    async def test_get_game_state(self, client, _init_db):
        game_id = self._game_id("test_game")
        client.post(
            f"/api/v1/games/{game_id}/start",
            json={"players": ["alice", "bob"], "seed": 42},
        )
        key = await _mint_key(game_id, "alice")

        response = client.get(
            f"/api/v1/state?game_id={game_id}",
            headers=_auth_headers(key),
        )
        assert response.status_code == 200
        data = response.json()
        assert "turn" in data
        assert "players" in data
        assert "tiles" in data

    @pytest.mark.asyncio
    async def test_get_game_state_as_player_redacts(self, client, _init_db):
        """``?as_player=`` redacts the response for an unauthenticated observer.

        Covers the spectator perspective switcher: a god-mode caller (or
        an unseated lobby creator) asks for ``as_player=alice`` and gets
        a fog-of-war view filtered to alice's units/cities. With only
        starter units on a fresh map, the redacted tile count must be
        strictly less than the full ``map_width * map_height`` god-mode
        response.
        """
        game_id = self._game_id("test_game")
        client.post(
            f"/api/v1/games/{game_id}/start",
            json={"players": ["alice", "bob"], "seed": 42},
        )

        god_resp = client.get(f"/api/v1/state?game_id={game_id}")
        assert god_resp.status_code == 200
        god_data = god_resp.json()
        full_tile_count = god_data["map_width"] * god_data["map_height"]
        assert len(god_data["tiles"]) == full_tile_count

        alice_resp = client.get(
            f"/api/v1/state?game_id={game_id}&as_player=alice"
        )
        assert alice_resp.status_code == 200
        alice_data = alice_resp.json()
        assert len(alice_data["tiles"]) < full_tile_count
        # Every visible unit is alice's (bob's units are out of sight on
        # turn 0 with default starter spacing).
        for unit in alice_data["units"].values():
            assert unit["owner"] == "alice"

    @pytest.mark.asyncio
    async def test_get_game_state_as_player_unknown_rejected(
        self, client, _init_db
    ):
        """Unknown ``as_player`` is a 400, not a silent god-mode fallthrough."""
        game_id = self._game_id("test_game")
        client.post(
            f"/api/v1/games/{game_id}/start",
            json={"players": ["alice", "bob"], "seed": 42},
        )
        resp = client.get(
            f"/api/v1/state?game_id={game_id}&as_player=mallory"
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_submit_actions(self, client, _init_db):
        game_id = self._game_id("test_game")
        client.post(
            f"/api/v1/games/{game_id}/start",
            json={"players": ["alice", "bob"], "seed": 42},
        )
        key = await _mint_key(game_id, "alice")

        response = client.post(
            f"/api/v1/actions?game_id={game_id}",
            json=[],
            headers=_auth_headers(key),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "actions_submitted"
        assert data["count"] == "0"

    @pytest.mark.asyncio
    async def test_submit_prompt_log(self, client, _init_db):
        game_id = self._game_id("test_game")
        client.post(
            f"/api/v1/games/{game_id}/start",
            json={"players": ["alice", "bob"], "seed": 42},
        )
        key = await _mint_key(game_id, "alice")

        prompt_data = {
            "player": "alice",
            "prompt": "What should I do?",
            "response": "Move scout north",
            "tokens_in": 10,
            "tokens_out": 5,
            "latency_ms": 150,
        }

        response = client.post(
            f"/api/v1/prompts?game_id={game_id}",
            json=prompt_data,
            headers=_auth_headers(key),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "prompt_logged"


class TestAuthentication:
    """Test authentication and authorization after the Phase 2 unification."""

    def test_missing_auth_header_on_state(self, client):
        """GET /state allows unauthenticated observation — returns 404 for missing game."""
        response = client.get("/api/v1/state")
        assert response.status_code == 404

    def test_invalid_key_rejected_on_actions(self, client):
        """POST /actions requires a valid API key; bogus bearer → 401."""
        headers = {"Authorization": "Bearer fx_bogus_not_a_real_key"}
        response = client.post(
            "/api/v1/actions?game_id=any", json=[], headers=headers
        )
        assert response.status_code == 401

    def test_missing_auth_on_actions(self, client):
        """POST /actions with no Authorization header → 401."""
        response = client.post("/api/v1/actions?game_id=any", json=[])
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_key_for_wrong_game_rejected(self, client, _init_db):
        """A key minted for one game is rejected on calls targeting another."""
        game_a = f"crossgame_a_{int(time.time() * 1000000)}"
        game_b = f"crossgame_b_{int(time.time() * 1000000)}"
        client.post(
            f"/api/v1/games/{game_a}/start",
            json={"players": ["alice", "bob"], "seed": 42},
        )
        client.post(
            f"/api/v1/games/{game_b}/start",
            json={"players": ["alice", "bob"], "seed": 42},
        )
        key_for_a = await _mint_key(game_a, "alice")

        resp = client.post(
            f"/api/v1/actions?game_id={game_b}",
            json=[],
            headers=_auth_headers(key_for_a),
        )
        assert resp.status_code == 403

    def test_legacy_player_prefix_no_longer_works(self, client):
        """The ``Bearer player_<name>`` shortcut from Phase 0 is gone."""
        headers = {"Authorization": "Bearer player_alice"}
        response = client.post(
            "/api/v1/actions?game_id=any", json=[], headers=headers
        )
        assert response.status_code == 401


class TestErrorHandling:
    """Test error handling in API endpoints."""

    @pytest.mark.asyncio
    async def test_game_not_found(self, client, _init_db):
        key = "fx_does_not_matter"
        response = client.get(
            "/api/v1/state?game_id=nonexistent",
            headers=_auth_headers(key),
        )
        # GET /state uses optional auth: a bogus key degrades to unauthenticated
        # observation, so game lookup runs and returns 404.
        assert response.status_code == 404

    def test_duplicate_game_creation(self, client):
        game_id = f"duplicate_test_{int(time.time() * 1000000)}"
        game_data = {"players": ["player_1", "player_2"], "seed": 42}

        response1 = client.post(
            f"/api/v1/games/{game_id}/start", json=game_data
        )
        assert response1.status_code == 200

        response2 = client.post(
            f"/api/v1/games/{game_id}/start", json=game_data
        )
        assert response2.status_code == 400
        data = response2.json()
        assert "already exists" in data["detail"]

    def test_invalid_player_count(self, client):
        response = client.post(
            "/api/v1/games/invalid_count/start",
            json={"players": ["player_1"], "seed": 42},
        )
        assert response.status_code == 400
        data = response.json()
        assert "2-8 players" in data["detail"]

        response = client.post(
            "/api/v1/games/invalid_count_2/start",
            json={"players": [f"player_{i}" for i in range(10)], "seed": 42},
        )
        assert response.status_code == 400
        data = response.json()
        assert "2-8 players" in data["detail"]
