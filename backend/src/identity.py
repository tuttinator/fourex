"""
Auth.js JWT verification for lobby-lifecycle endpoints.

The Next.js frontend issues JWTs via Auth.js and forwards them on
lobby-lifecycle calls (create game, join game). FastAPI verifies them here
to extract the `UserIdentity` the request is acting as.

Design:
- Shared secret (``settings.auth_secret``) between Next.js and FastAPI.
  Rotating requires a coordinated redeploy of both services.
- Tokens are HS256 JWS — Auth.js must be configured with a custom
  ``jwt.encode`` / ``jwt.decode`` producing HS256 JWS. The default
  Auth.js encoding is JWE (A256CBC-HS512) which PyJWT cannot read;
  Phase 1's frontend slice will wire the HS256 override.
- Claims expected:
    * ``sub`` (required) — the ``UserIdentity.id`` as a string.
    * ``email`` (optional) — the verified email; informational.
    * ``exp`` (required) — standard expiry.
"""

from dataclasses import dataclass
from typing import Any

import jwt
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidSignatureError,
    InvalidTokenError,
    PyJWTError,
)

from .config import settings

_JWT_ALGORITHM = "HS256"


class JwtAuthError(Exception):
    """Raised when an Auth.js JWT fails verification."""

    def __init__(self, message: str, *, expired: bool = False) -> None:
        super().__init__(message)
        self.expired = expired


@dataclass(frozen=True)
class UserIdentityContext:
    """Resolved identity from a verified Auth.js JWT."""

    user_identity_id: int
    email: str | None


def _decode_options() -> dict[str, Any]:
    return {
        "require": ["exp", "sub"],
        "verify_signature": True,
        "verify_exp": True,
    }


def verify_auth_jwt(token: str) -> UserIdentityContext:
    """Verify an Auth.js JWT and return the bound user identity.

    Raises JwtAuthError on missing/expired/tampered/malformed tokens.
    """
    if not token:
        raise JwtAuthError("JWT is required")

    kwargs: dict[str, Any] = {
        "algorithms": [_JWT_ALGORITHM],
        "options": _decode_options(),
    }
    if settings.auth_jwt_issuer:
        kwargs["issuer"] = settings.auth_jwt_issuer

    try:
        payload = jwt.decode(token, settings.auth_secret, **kwargs)
    except ExpiredSignatureError as exc:
        raise JwtAuthError("JWT has expired", expired=True) from exc
    except InvalidSignatureError as exc:
        raise JwtAuthError("JWT signature is invalid") from exc
    except InvalidTokenError as exc:
        raise JwtAuthError(f"JWT is invalid: {exc}") from exc
    except PyJWTError as exc:  # pragma: no cover — safety net
        raise JwtAuthError(f"JWT verification failed: {exc}") from exc

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise JwtAuthError("JWT is missing required `sub` claim")
    try:
        user_identity_id = int(sub)
    except ValueError as exc:
        raise JwtAuthError("JWT `sub` claim must be an integer id") from exc

    email = payload.get("email")
    if email is not None and not isinstance(email, str):
        raise JwtAuthError("JWT `email` claim must be a string")

    return UserIdentityContext(user_identity_id=user_identity_id, email=email)
