"""Tests for the Auth.js JWT verifier (Phase 1 of human-frontend-parity)."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest

from backend.src.config import settings
from backend.src.identity import (
    JwtAuthError,
    UserIdentityContext,
    verify_auth_jwt,
)

ALG = "HS256"


def _mint(
    payload: dict[str, Any],
    *,
    secret: str | None = None,
    algorithm: str = ALG,
) -> str:
    return jwt.encode(payload, secret or settings.auth_secret, algorithm=algorithm)


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base: dict[str, Any] = {
        "sub": "42",
        "email": "caleb@mokotahi.com",
        "iat": now,
        "exp": now + 3600,
    }
    base.update(overrides)
    return base


def test_verify_valid_token_returns_context() -> None:
    token = _mint(_valid_payload())
    ctx = verify_auth_jwt(token)
    assert isinstance(ctx, UserIdentityContext)
    assert ctx.user_identity_id == 42
    assert ctx.email == "caleb@mokotahi.com"


def test_verify_allows_missing_email_claim() -> None:
    payload = _valid_payload()
    payload.pop("email")
    token = _mint(payload)
    ctx = verify_auth_jwt(token)
    assert ctx.user_identity_id == 42
    assert ctx.email is None


def test_verify_rejects_non_string_email_claim() -> None:
    token = _mint(_valid_payload(email=12345))
    with pytest.raises(JwtAuthError, match="email"):
        verify_auth_jwt(token)


def test_verify_rejects_empty_token() -> None:
    with pytest.raises(JwtAuthError, match="required"):
        verify_auth_jwt("")


def test_verify_rejects_tampered_signature() -> None:
    token = _mint(_valid_payload())
    header, payload_b64, _ = token.split(".")
    tampered = f"{header}.{payload_b64}.AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    with pytest.raises(JwtAuthError, match="signature"):
        verify_auth_jwt(tampered)


def test_verify_rejects_wrong_secret() -> None:
    token = _mint(
        _valid_payload(),
        secret="definitely-not-the-real-secret-but-long-enough-to-be-fine",
    )
    with pytest.raises(JwtAuthError, match="signature"):
        verify_auth_jwt(token)


def test_verify_rejects_expired_token() -> None:
    now = int(time.time())
    token = _mint(_valid_payload(iat=now - 7200, exp=now - 3600))
    with pytest.raises(JwtAuthError, match="expired") as excinfo:
        verify_auth_jwt(token)
    assert excinfo.value.expired is True


def test_verify_rejects_missing_exp() -> None:
    payload = _valid_payload()
    payload.pop("exp")
    token = _mint(payload)
    with pytest.raises(JwtAuthError, match="invalid"):
        verify_auth_jwt(token)


def test_verify_rejects_missing_sub() -> None:
    payload = _valid_payload()
    payload.pop("sub")
    token = _mint(payload)
    with pytest.raises(JwtAuthError, match="invalid"):
        verify_auth_jwt(token)


def test_verify_rejects_non_integer_sub() -> None:
    token = _mint(_valid_payload(sub="not-a-number"))
    with pytest.raises(JwtAuthError, match="integer"):
        verify_auth_jwt(token)


def test_verify_rejects_empty_sub() -> None:
    token = _mint(_valid_payload(sub=""))
    with pytest.raises(JwtAuthError, match=r"sub"):
        verify_auth_jwt(token)


def test_verify_rejects_wrong_algorithm() -> None:
    # Mint with HS512 while verifier only accepts HS256.
    token = jwt.encode(_valid_payload(), settings.auth_secret, algorithm="HS512")
    with pytest.raises(JwtAuthError, match="invalid"):
        verify_auth_jwt(token)


def test_verify_rejects_malformed_token() -> None:
    with pytest.raises(JwtAuthError, match="invalid"):
        verify_auth_jwt("not.a.jwt")


def test_verify_respects_configured_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_issuer", "parley.quest")

    good = _mint(_valid_payload(iss="parley.quest"))
    ctx = verify_auth_jwt(good)
    assert ctx.user_identity_id == 42

    bad = _mint(_valid_payload(iss="evil.example"))
    with pytest.raises(JwtAuthError, match="invalid"):
        verify_auth_jwt(bad)
