"""Tests for the ``/api/v1/me`` endpoint (Phase 3 of map system overhaul)."""

from __future__ import annotations

import time

import jwt
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import UserIdentity
from backend.src.database.repository import GameRepository
from backend.src.main import app

ALG = "HS256"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest_asyncio.fixture(autouse=True)
async def _clean_identities() -> None:
    await init_db()
    async with async_session_factory() as session:
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@metest.example.com")
            )
        )
        await session.commit()
    yield
    async with async_session_factory() as session:
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@metest.example.com")
            )
        )
        await session.commit()


def _mint_jwt(user_identity_id: int, email: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_identity_id),
        "email": email,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, settings.auth_secret, algorithm=ALG)


async def _seed_identity(email: str, *, is_admin: bool = False) -> int:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        identity = await repo.upsert_user_identity_by_email(email)
        identity.is_admin = is_admin
        await session.commit()
        return identity.id


class TestMeEndpoint:
    def test_requires_jwt(self, client: TestClient) -> None:
        resp = client.get("/api/v1/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_identity_with_is_admin_false(
        self, client: TestClient
    ) -> None:
        identity_id = await _seed_identity("regular@metest.example.com")
        token = _mint_jwt(identity_id, "regular@metest.example.com")
        resp = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == identity_id
        assert body["email"] == "regular@metest.example.com"
        assert body["is_admin"] is False

    @pytest.mark.asyncio
    async def test_returns_is_admin_true(self, client: TestClient) -> None:
        identity_id = await _seed_identity(
            "admin@metest.example.com", is_admin=True
        )
        token = _mint_jwt(identity_id, "admin@metest.example.com")
        resp = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is True

    def test_returns_404_when_identity_missing(self, client: TestClient) -> None:
        # Mint a JWT for a user_identity_id that doesn't exist.
        token = _mint_jwt(999_999_999, "ghost@metest.example.com")
        resp = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 404
