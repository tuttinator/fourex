"""Tests for the identity upsert endpoint called by the Next.js Auth.js adapter."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import UserIdentity
from backend.src.main import app

SERVICE_SECRET_HEADER = "X-Identity-Service-Secret"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def service_headers() -> dict[str, str]:
    return {SERVICE_SECRET_HEADER: settings.identity_service_secret}


@pytest_asyncio.fixture(autouse=True)
async def _clean_identities() -> None:
    await init_db()
    async with async_session_factory() as session:
        await session.execute(
            delete(UserIdentity).where(UserIdentity.email.like("%@identitytest.example.com"))
        )
        await session.commit()
    yield
    async with async_session_factory() as session:
        await session.execute(
            delete(UserIdentity).where(UserIdentity.email.like("%@identitytest.example.com"))
        )
        await session.commit()


class TestUpsertIdentityEndpoint:
    def test_rejects_missing_secret(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/identities/upsert",
            json={"email": "alice@identitytest.example.com"},
        )
        assert resp.status_code == 401

    def test_rejects_wrong_secret(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/identities/upsert",
            json={"email": "alice@identitytest.example.com"},
            headers={SERVICE_SECRET_HEADER: "nope"},
        )
        assert resp.status_code == 401

    def test_rejects_invalid_email(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            "/api/v1/identities/upsert",
            json={"email": "not-an-email"},
            headers=service_headers,
        )
        assert resp.status_code == 422

    def test_creates_identity_on_first_verify(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            "/api/v1/identities/upsert",
            json={"email": "alice@identitytest.example.com"},
            headers=service_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["id"], int)
        assert data["email"] == "alice@identitytest.example.com"

    def test_idempotent_on_repeated_verify(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        first = client.post(
            "/api/v1/identities/upsert",
            json={"email": "bob@identitytest.example.com"},
            headers=service_headers,
        )
        second = client.post(
            "/api/v1/identities/upsert",
            json={"email": "bob@identitytest.example.com"},
            headers=service_headers,
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

    def test_normalises_email_case_and_whitespace(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        canonical = client.post(
            "/api/v1/identities/upsert",
            json={"email": "Carol@identitytest.example.com"},
            headers=service_headers,
        )
        mixed = client.post(
            "/api/v1/identities/upsert",
            json={"email": "CAROL@identitytest.example.com"},
            headers=service_headers,
        )
        assert canonical.status_code == 200
        assert mixed.status_code == 200
        assert canonical.json()["id"] == mixed.json()["id"]
        assert canonical.json()["email"] == "carol@identitytest.example.com"
