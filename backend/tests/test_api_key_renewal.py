"""Tests for the API-key renewal endpoint (Phase 1 of human-frontend-parity)."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.auth import create_player_key
from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import Game, PlayerApiKey, UserIdentity
from backend.src.database.repository import GameRepository
from backend.src.main import app

ALG = "HS256"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture
async def _clean_renewal_rows() -> None:
    await init_db()
    async with async_session_factory() as session:
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("renew_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("renew_%")))
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@renewal.example.com")
            )
        )
        await session.commit()
    yield
    async with async_session_factory() as session:
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("renew_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("renew_%")))
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@renewal.example.com")
            )
        )
        await session.commit()


def _mint_jwt(user_identity_id: int, *, email: str | None = None) -> str:
    now = int(time.time())
    payload: dict = {"sub": str(user_identity_id), "iat": now, "exp": now + 3600}
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, settings.auth_secret, algorithm=ALG)


async def _seed_game_with_human_key(
    game_id: str, player_id: str, email: str
) -> tuple[int, str]:
    """Create a game + UserIdentity + PlayerApiKey attributed to that identity.

    Returns ``(user_identity_id, plaintext_key)``.
    """
    async with async_session_factory() as session:
        repo = GameRepository(session)
        await repo.create_game(game_id=game_id, players=[player_id, "opponent"])
        identity = await repo.upsert_user_identity_by_email(email)
        plaintext = await create_player_key(session, game_id, player_id)
        row = await repo.get_player_api_key(game_id, player_id)
        assert row is not None
        row.user_identity_id = identity.id
        await session.commit()
        return identity.id, plaintext


def _game_id(suffix: str) -> str:
    return f"renew_{suffix}_{int(time.time() * 1000000)}"


class TestApiKeyRenewalEndpoint:
    def test_requires_bearer_token(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        resp = client.post("/api/v1/games/renew_nojwt/api-key/renew")
        assert resp.status_code == 401

    def test_rejects_invalid_jwt(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        resp = client.post(
            "/api/v1/games/renew_badjwt/api-key/renew",
            headers={"Authorization": "Bearer not.a.jwt"},
        )
        assert resp.status_code == 401

    def test_rejects_expired_jwt(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        now = int(time.time())
        expired = jwt.encode(
            {"sub": "1", "iat": now - 7200, "exp": now - 3600},
            settings.auth_secret,
            algorithm=ALG,
        )
        resp = client.post(
            "/api/v1/games/renew_expiredjwt/api-key/renew",
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401

    def test_rejects_wrong_secret(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        now = int(time.time())
        bogus = jwt.encode(
            {"sub": "1", "iat": now, "exp": now + 3600},
            "not-the-real-secret-but-long-enough-for-hs256-ok",
            algorithm=ALG,
        )
        resp = client.post(
            "/api/v1/games/renew_wrongsig/api-key/renew",
            headers={"Authorization": f"Bearer {bogus}"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_game_not_found_returns_404(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        token = _mint_jwt(user_identity_id=1)
        resp = client.post(
            "/api/v1/games/renew_missing_game/api-key/renew",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_key_for_user_returns_404(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        game_id = _game_id("nokey")
        _uid, _plain = await _seed_game_with_human_key(
            game_id, "alice", "alice@renewal.example.com"
        )

        # Different user with no seat in the game.
        async with async_session_factory() as session:
            repo = GameRepository(session)
            stranger = await repo.upsert_user_identity_by_email(
                "stranger@renewal.example.com"
            )
            stranger_id = stranger.id
            await session.commit()

        token = _mint_jwt(user_identity_id=stranger_id)
        resp = client.post(
            f"/api/v1/games/{game_id}/api-key/renew",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_mcp_key_cannot_be_renewed(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        # A game with an MCP-minted key (user_identity_id is null) should not
        # resolve to the signed-in user.
        game_id = _game_id("mcponly")
        async with async_session_factory() as session:
            repo = GameRepository(session)
            await repo.create_game(game_id=game_id, players=["agent", "opponent"])
            await create_player_key(session, game_id, "agent")  # no user_identity_id
            identity = await repo.upsert_user_identity_by_email(
                "human@renewal.example.com"
            )
            human_id = identity.id
            await session.commit()

        token = _mint_jwt(user_identity_id=human_id)
        resp = client.post(
            f"/api/v1/games/{game_id}/api-key/renew",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_renews_and_returns_fresh_key(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        game_id = _game_id("happy")
        uid, old_key = await _seed_game_with_human_key(
            game_id, "alice", "alice@renewal.example.com"
        )

        token = _mint_jwt(user_identity_id=uid)
        resp = client.post(
            f"/api/v1/games/{game_id}/api-key/renew",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_id"] == game_id
        assert data["player_id"] == "alice"
        assert data["api_key"].startswith("fx_")
        assert data["api_key"] != old_key

        # Old key no longer matches the stored hash; new key does.
        async with async_session_factory() as session:
            repo = GameRepository(session)
            row = await repo.get_player_api_key(game_id, "alice")
            assert row is not None
            assert (
                row.key_hash
                == hashlib.sha256(data["api_key"].encode("utf-8")).hexdigest()
            )
            assert (
                row.key_hash
                != hashlib.sha256(old_key.encode("utf-8")).hexdigest()
            )
            # Expiry refreshed into the future.
            assert row.expires_at is not None
            assert row.expires_at > datetime.now(UTC).replace(tzinfo=None)
            # Identity attribution preserved.
            assert row.user_identity_id == uid

    @pytest.mark.asyncio
    async def test_renew_extends_expiry_window(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        game_id = _game_id("extend")
        uid, _old = await _seed_game_with_human_key(
            game_id, "bob", "bob@renewal.example.com"
        )

        # Force the existing expires_at to be near-term to prove it got extended.
        near_term = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
        async with async_session_factory() as session:
            repo = GameRepository(session)
            row = await repo.get_player_api_key(game_id, "bob")
            assert row is not None
            row.expires_at = near_term
            await session.commit()

        token = _mint_jwt(user_identity_id=uid)
        resp = client.post(
            f"/api/v1/games/{game_id}/api-key/renew",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        async with async_session_factory() as session:
            repo = GameRepository(session)
            row = await repo.get_player_api_key(game_id, "bob")
            assert row is not None
            # Default TTL is 24h; window must now be > 23h from now.
            assert row.expires_at is not None
            assert row.expires_at - datetime.now(UTC).replace(tzinfo=None) > timedelta(
                hours=23
            )

    @pytest.mark.asyncio
    async def test_ended_game_returns_410(
        self, client: TestClient, _clean_renewal_rows: None
    ) -> None:
        game_id = _game_id("ended")
        uid, _plain = await _seed_game_with_human_key(
            game_id, "alice", "alice@renewal.example.com"
        )
        async with async_session_factory() as session:
            repo = GameRepository(session)
            await repo.end_game(game_id, winner="alice")
            await session.commit()

        token = _mint_jwt(user_identity_id=uid)
        resp = client.post(
            f"/api/v1/games/{game_id}/api-key/renew",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 410
