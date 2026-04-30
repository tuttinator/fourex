"""Tests for the identity endpoints called by the Next.js Auth.js adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.src.config import settings
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import AuthVerificationToken, UserIdentity
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
            delete(UserIdentity).where(
                UserIdentity.email.like("%@identitytest.example.com")
            )
        )
        await session.execute(
            delete(AuthVerificationToken).where(
                AuthVerificationToken.identifier.like(
                    "%@identitytest.example.com"
                )
            )
        )
        await session.commit()
    yield
    async with async_session_factory() as session:
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.email.like("%@identitytest.example.com")
            )
        )
        await session.execute(
            delete(AuthVerificationToken).where(
                AuthVerificationToken.identifier.like(
                    "%@identitytest.example.com"
                )
            )
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

    def test_by_email_404_when_missing(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            "/api/v1/identities/by-email",
            params={"email": "missing@identitytest.example.com"},
            headers=service_headers,
        )
        assert resp.status_code == 404

    def test_by_email_returns_existing_identity(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        created = client.post(
            "/api/v1/identities/upsert",
            json={"email": "found@identitytest.example.com"},
            headers=service_headers,
        )
        lookup = client.get(
            "/api/v1/identities/by-email",
            params={"email": "found@identitytest.example.com"},
            headers=service_headers,
        )
        assert created.status_code == 200
        assert lookup.status_code == 200
        assert lookup.json()["id"] == created.json()["id"]

    def test_by_id_404_when_missing(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        resp = client.get(
            "/api/v1/identities/by-id",
            params={"id": 999_999_999},
            headers=service_headers,
        )
        assert resp.status_code == 404

    def test_by_id_returns_existing_identity(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        created = client.post(
            "/api/v1/identities/upsert",
            json={"email": "dan@identitytest.example.com"},
            headers=service_headers,
        )
        identity_id = created.json()["id"]
        lookup = client.get(
            "/api/v1/identities/by-id",
            params={"id": identity_id},
            headers=service_headers,
        )
        assert lookup.status_code == 200
        assert lookup.json() == {
            "id": identity_id,
            "email": "dan@identitytest.example.com",
            "is_admin": False,
        }

    def test_by_id_requires_secret(self, client: TestClient) -> None:
        resp = client.get(
            "/api/v1/identities/by-id",
            params={"id": 1},
        )
        assert resp.status_code == 401

    def test_create_and_consume_verification_token(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        expires = (datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=15)).isoformat()
        create = client.post(
            "/api/v1/identities/verification-tokens",
            json={
                "identifier": "link@identitytest.example.com",
                "token": "abc-123",
                "expires": expires,
            },
            headers=service_headers,
        )
        assert create.status_code == 200
        consume = client.post(
            "/api/v1/identities/verification-tokens/consume",
            json={
                "identifier": "link@identitytest.example.com",
                "token": "abc-123",
            },
            headers=service_headers,
        )
        assert consume.status_code == 200
        # Re-consuming the same (identifier, token) pair must fail — one-shot.
        second = client.post(
            "/api/v1/identities/verification-tokens/consume",
            json={
                "identifier": "link@identitytest.example.com",
                "token": "abc-123",
            },
            headers=service_headers,
        )
        assert second.status_code == 404

    def test_consume_missing_token_returns_404(
        self, client: TestClient, service_headers: dict[str, str]
    ) -> None:
        resp = client.post(
            "/api/v1/identities/verification-tokens/consume",
            json={
                "identifier": "nobody@identitytest.example.com",
                "token": "nope",
            },
            headers=service_headers,
        )
        assert resp.status_code == 404

    def test_verification_token_routes_require_secret(
        self, client: TestClient
    ) -> None:
        create = client.post(
            "/api/v1/identities/verification-tokens",
            json={
                "identifier": "x@identitytest.example.com",
                "token": "t",
                "expires": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            },
        )
        consume = client.post(
            "/api/v1/identities/verification-tokens/consume",
            json={"identifier": "x@identitytest.example.com", "token": "t"},
        )
        assert create.status_code == 401
        assert consume.status_code == 401

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


class TestAdminAllowlistSync:
    """Phase 3 (map system overhaul): is_admin re-syncs from env allowlist."""

    def test_upsert_sets_is_admin_when_email_in_allowlist(
        self,
        client: TestClient,
        service_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            settings, "admin_email_allowlist", ["admin@identitytest.example.com"]
        )
        resp = client.post(
            "/api/v1/identities/upsert",
            json={"email": "admin@identitytest.example.com"},
            headers=service_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is True

    def test_upsert_leaves_non_admin_when_email_absent(
        self,
        client: TestClient,
        service_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            settings, "admin_email_allowlist", ["someone-else@identitytest.example.com"]
        )
        resp = client.post(
            "/api/v1/identities/upsert",
            json={"email": "regular@identitytest.example.com"},
            headers=service_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is False

    def test_removing_email_from_allowlist_demotes_on_next_upsert(
        self,
        client: TestClient,
        service_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # First sign-in: in allowlist, becomes admin.
        monkeypatch.setattr(
            settings, "admin_email_allowlist", ["churn@identitytest.example.com"]
        )
        first = client.post(
            "/api/v1/identities/upsert",
            json={"email": "churn@identitytest.example.com"},
            headers=service_headers,
        )
        assert first.json()["is_admin"] is True

        # Second sign-in: allowlist no longer includes the email.
        monkeypatch.setattr(settings, "admin_email_allowlist", [])
        second = client.post(
            "/api/v1/identities/upsert",
            json={"email": "churn@identitytest.example.com"},
            headers=service_headers,
        )
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["is_admin"] is False

    def test_consume_verification_token_resyncs_is_admin(
        self,
        client: TestClient,
        service_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pre-create the identity as non-admin.
        client.post(
            "/api/v1/identities/upsert",
            json={"email": "verify@identitytest.example.com"},
            headers=service_headers,
        )

        # Add the email to the allowlist, then run a magic-link verify.
        monkeypatch.setattr(
            settings, "admin_email_allowlist", ["verify@identitytest.example.com"]
        )
        expires = (
            datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=15)
        ).isoformat()
        create = client.post(
            "/api/v1/identities/verification-tokens",
            json={
                "identifier": "verify@identitytest.example.com",
                "token": "tok-1",
                "expires": expires,
            },
            headers=service_headers,
        )
        assert create.status_code == 200
        consume = client.post(
            "/api/v1/identities/verification-tokens/consume",
            json={
                "identifier": "verify@identitytest.example.com",
                "token": "tok-1",
            },
            headers=service_headers,
        )
        assert consume.status_code == 200

        # Identity should now be admin.
        lookup = client.get(
            "/api/v1/identities/by-email",
            params={"email": "verify@identitytest.example.com"},
            headers=service_headers,
        )
        assert lookup.status_code == 200
        assert lookup.json()["is_admin"] is True
