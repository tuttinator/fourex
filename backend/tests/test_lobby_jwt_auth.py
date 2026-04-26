"""Tests for Phase 2 of human-frontend-parity: JWT-gated lobby lifecycle.

Covers the ``POST /games`` (create lobby) and ``POST /games/{id}/join``
endpoints as they now behave: Auth.js JWT required for authentication,
PlayerApiKey minted with ``user_identity_id`` populated, API key
returned to the caller, MCP-minted keys continue to leave
``user_identity_id`` null so the two front doors interoperate.
"""

from __future__ import annotations

import hashlib
import time

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.auth import create_player_key
from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import (
    Game,
    GameSnapshot,
    GameTurn,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
    UserIdentity,
)
from backend.src.database.repository import GameRepository
from backend.src.main import app

ALG = "HS256"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


async def _purge_lobby_rows() -> None:
    """Tear down every row a started lobby can leave behind.

    Deletion order matters: ``games`` is FK-referenced by snapshots,
    turns, and actions, so those have to go first. The order here also
    covers tests that flip a lobby to ``active`` (via ``/start``) which
    creates ``GameSnapshot`` / ``TurnSnapshot`` rows that the original
    PlayerApiKey-only sweep didn't know about.
    """
    async with async_session_factory() as session:
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("lobbyjwt_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("lobbyjwt_%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("lobbyjwt_%"))
        )
        await session.execute(
            delete(GameSnapshot).where(GameSnapshot.game_id.like("lobbyjwt_%"))
        )
        await session.execute(
            delete(GameTurn).where(GameTurn.game_id.like("lobbyjwt_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("lobbyjwt_%")))
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@lobbyjwt.example.com")
            )
        )
        await session.commit()


@pytest_asyncio.fixture
async def _clean_lobby_rows() -> None:
    await init_db()
    await _purge_lobby_rows()
    yield
    await _purge_lobby_rows()


def _mint_jwt(user_identity_id: int, *, email: str | None = None) -> str:
    now = int(time.time())
    payload: dict = {"sub": str(user_identity_id), "iat": now, "exp": now + 3600}
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
    return f"lobbyjwt_{suffix}_{int(time.time() * 1000000)}"


class TestCreateLobbyJwt:
    def test_requires_jwt(self, client: TestClient, _clean_lobby_rows: None) -> None:
        game_id = _game_id("nojwt")
        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
        )
        assert resp.status_code == 401

    def test_rejects_invalid_jwt(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        game_id = _game_id("badjwt")
        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": "Bearer not.a.jwt"},
        )
        assert resp.status_code == 401

    def test_rejects_expired_jwt(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        now = int(time.time())
        expired = jwt.encode(
            {"sub": "1", "iat": now - 7200, "exp": now - 3600},
            settings.auth_secret,
            algorithm=ALG,
        )
        game_id = _game_id("expired")
        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_happy_path_returns_game_and_api_key(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        uid = await _seed_identity("creator@lobbyjwt.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("happy")

        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["game"]["game_id"] == game_id
        assert data["game"]["creator"] == "alice"
        assert "alice" in data["game"]["players"]
        assert data["game"]["status"] == "waiting"
        assert data["api_key"].startswith("fx_")

        # PlayerApiKey row is attributed to the UserIdentity.
        async with async_session_factory() as session:
            repo = GameRepository(session)
            row = await repo.get_player_api_key(game_id, "alice")
            assert row is not None
            assert row.user_identity_id == uid
            assert (
                row.key_hash
                == hashlib.sha256(data["api_key"].encode("utf-8")).hexdigest()
            )

    @pytest.mark.asyncio
    async def test_created_key_authenticates_gameplay_calls(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        uid = await _seed_identity("creator2@lobbyjwt.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("useit")

        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        api_key = resp.json()["api_key"]

        # Using the freshly-minted key passes through the API-key dependency
        # on the state endpoint, so we get a redacted view back.
        resp = client.get(
            f"/api/v1/state?game_id={game_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200


class TestJoinGameJwt:
    @pytest.mark.asyncio
    async def test_requires_jwt(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        game_id = _game_id("joinnojwt")
        # Seed a lobby first so the 401 isn't masked by 404.
        await _seed_identity("creator3@lobbyjwt.example.com")
        async with async_session_factory() as session:
            repo = GameRepository(session)
            await repo.create_game(
                game_id=game_id, players=["alice"], player_slots=2, creator="alice"
            )
            await session.commit()

        resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_happy_path_joins_and_returns_key(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        creator_uid = await _seed_identity("creator4@lobbyjwt.example.com")
        creator_token = _mint_jwt(creator_uid)
        game_id = _game_id("joinhappy")

        # Alice creates the lobby.
        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert resp.status_code == 200

        # Bob joins.
        bob_uid = await _seed_identity("bob@lobbyjwt.example.com")
        bob_token = _mint_jwt(bob_uid)
        resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob"},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "bob" in data["game"]["players"]
        assert data["api_key"].startswith("fx_")

        async with async_session_factory() as session:
            repo = GameRepository(session)
            row = await repo.get_player_api_key(game_id, "bob")
            assert row is not None
            assert row.user_identity_id == bob_uid

    @pytest.mark.asyncio
    async def test_join_full_game_rejected(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        creator_uid = await _seed_identity("creator5@lobbyjwt.example.com")
        creator_token = _mint_jwt(creator_uid)
        game_id = _game_id("full")

        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        assert resp.status_code == 200

        bob_uid = await _seed_identity("bob2@lobbyjwt.example.com")
        client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob"},
            headers={"Authorization": f"Bearer {_mint_jwt(bob_uid)}"},
        )

        charlie_uid = await _seed_identity("charlie@lobbyjwt.example.com")
        resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "charlie"},
            headers={"Authorization": f"Bearer {_mint_jwt(charlie_uid)}"},
        )
        assert resp.status_code == 400


class TestMcpParity:
    """MCP-minted keys leave user_identity_id null; they remain a separate code path.

    This test locks in the invariant that a game can host one human and
    one MCP agent side by side with only the human's key carrying a
    user_identity_id.
    """

    @pytest.mark.asyncio
    async def test_human_and_mcp_keys_coexist(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        uid = await _seed_identity("mixed@lobbyjwt.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("mixed")

        # Human creates the lobby via the JWT path.
        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        human_key = resp.json()["api_key"]

        # Agent "joins" via the same path an MCP call would use —
        # create_player_key with no user_identity_id.
        async with async_session_factory() as session:
            repo = GameRepository(session)
            game = await repo.get_game(game_id)
            assert game is not None
            game.players = [*game.players, "agent"]
            await session.commit()
            await create_player_key(session, game_id, "agent")
            await session.commit()

        async with async_session_factory() as session:
            repo = GameRepository(session)
            human_row = await repo.get_player_api_key(game_id, "alice")
            agent_row = await repo.get_player_api_key(game_id, "agent")
            assert human_row is not None
            assert agent_row is not None
            assert human_row.user_identity_id == uid
            assert agent_row.user_identity_id is None

        # The human key still authenticates (we're not rotating it here).
        resp = client.get(
            f"/api/v1/state?game_id={game_id}",
            headers={"Authorization": f"Bearer {human_key}"},
        )
        assert resp.status_code == 200


class TestGameDetailKeyVisibility:
    """Phase 1: ``GET /games/{id}`` echoes the creator's bearer back as
    ``api_key`` while ``waiting``, so the lobby UI can render a
    copy-button affordance for an MCP agent. The field is gone for any
    other caller and gone the moment the game flips to ``active``.
    """

    @pytest.mark.asyncio
    async def test_creator_sees_own_api_key_while_waiting(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        uid = await _seed_identity("keyvis-creator@lobbyjwt.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("keyvis_creator")

        resp = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        api_key = resp.json()["api_key"]

        resp = client.get(
            f"/api/v1/games/{game_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["api_key"] == api_key

    @pytest.mark.asyncio
    async def test_anonymous_caller_does_not_see_key(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        uid = await _seed_identity("keyvis-anon@lobbyjwt.example.com")
        token = _mint_jwt(uid)
        game_id = _game_id("keyvis_anon")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = client.get(f"/api/v1/games/{game_id}")
        assert resp.status_code == 200
        assert resp.json().get("api_key") is None

    @pytest.mark.asyncio
    async def test_non_creator_seat_does_not_see_key(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        creator_uid = await _seed_identity("keyvis-c@lobbyjwt.example.com")
        creator_token = _mint_jwt(creator_uid)
        game_id = _game_id("keyvis_other")

        client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {creator_token}"},
        )

        bob_uid = await _seed_identity("keyvis-bob@lobbyjwt.example.com")
        join_resp = client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob"},
            headers={"Authorization": f"Bearer {_mint_jwt(bob_uid)}"},
        )
        assert join_resp.status_code == 200
        bob_key = join_resp.json()["api_key"]

        resp = client.get(
            f"/api/v1/games/{game_id}",
            headers={"Authorization": f"Bearer {bob_key}"},
        )
        assert resp.status_code == 200
        # Bob is a seated player but not the creator — no key for him.
        assert resp.json().get("api_key") is None

    @pytest.mark.asyncio
    async def test_key_disappears_once_game_active(
        self, client: TestClient, _clean_lobby_rows: None
    ) -> None:
        creator_uid = await _seed_identity("keyvis-start@lobbyjwt.example.com")
        creator_token = _mint_jwt(creator_uid)
        game_id = _game_id("keyvis_start")

        create = client.post(
            f"/api/v1/games?game_id={game_id}",
            json={"player_id": "alice", "player_slots": 2},
            headers={"Authorization": f"Bearer {creator_token}"},
        )
        api_key = create.json()["api_key"]

        bob_uid = await _seed_identity("keyvis-bob2@lobbyjwt.example.com")
        client.post(
            f"/api/v1/games/{game_id}/join",
            json={"player_id": "bob"},
            headers={"Authorization": f"Bearer {_mint_jwt(bob_uid)}"},
        )

        # Creator starts the game (lobby flow uses the per-game key).
        start_resp = client.post(
            f"/api/v1/games/{game_id}/start",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert start_resp.status_code == 200

        resp = client.get(
            f"/api/v1/games/{game_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "active"
        assert body.get("api_key") is None


def test_no_player_prefix_references_in_rest_module() -> None:
    """Regression: the Phase 0 ``player_*`` prefix check must be gone.

    Grep-level check so any accidental reintroduction fails a test rather
    than silently re-enabling the hack.
    """
    from backend.src.api import rest

    source_path = rest.__file__
    with open(source_path, encoding="utf-8") as fh:
        source = fh.read()

    # The marker strings from the old dependency; absence proves removal.
    assert 'startswith("player_")' not in source
    assert "token.credentials[7:]" not in source
