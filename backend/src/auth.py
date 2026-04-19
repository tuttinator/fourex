"""
Player API key authentication service.

Transport-agnostic layer used by both MCP tools and REST endpoints.
Generates cryptographically random API keys, stores SHA-256 hashes,
and validates incoming keys to resolve (game_id, player_id).

The FastAPI dependencies at the bottom of this module wrap ``authenticate``
for use on gameplay/diplomacy REST endpoints. They are co-located with the
core verifier so a reviewer sees the complete API-key surface in one file,
mirroring the pattern in ``identity.py`` for JWT verification.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .database.connection import get_database_session
from .database.repository import GameRepository


class AuthError(Exception):
    """Raised when API key authentication fails."""

    def __init__(self, message: str, *, expired: bool = False):
        super().__init__(message)
        self.expired = expired


@dataclass(frozen=True)
class AuthContext:
    """Resolved identity from a validated API key."""

    game_id: str
    player_id: str


# Default key expiry: 24 hours from creation.
DEFAULT_KEY_TTL = timedelta(hours=24)

# Key prefix for easy identification in logs / headers.
_KEY_PREFIX = "fx_"
# 32 bytes of randomness → 64 hex chars + prefix = 67 chars total.
_KEY_BYTES = 32


def generate_api_key() -> str:
    """Generate a cryptographically random API key.

    Returns the plaintext key (shown once to the caller).
    """
    return f"{_KEY_PREFIX}{secrets.token_hex(_KEY_BYTES)}"


async def create_player_key(
    session: AsyncSession,
    game_id: str,
    player_id: str,
    ttl: timedelta = DEFAULT_KEY_TTL,
    user_identity_id: int | None = None,
) -> str:
    """Generate and persist a new API key for a player in a game.

    Returns the plaintext key. Only the SHA-256 hash is stored. When
    ``user_identity_id`` is provided (human Auth.js flow) the key row is
    attributed to that identity so it's renewable via the JWT-gated
    renewal endpoint; MCP-minted keys leave it ``None``.
    """
    repo = GameRepository(session)

    # Check the game exists
    game = await repo.get_game(game_id)
    if game is None:
        raise AuthError(f"Game {game_id} not found")

    if game.status == "ended":
        raise AuthError(f"Game {game_id} has ended")

    plaintext = generate_api_key()
    expires_at = datetime.now(UTC).replace(tzinfo=None) + ttl

    await repo.create_player_api_key(
        game_id=game_id,
        player_id=player_id,
        plaintext_key=plaintext,
        expires_at=expires_at,
        user_identity_id=user_identity_id,
    )

    return plaintext


async def authenticate(session: AsyncSession, api_key: str) -> AuthContext:
    """Validate an API key and return the resolved (game_id, player_id).

    Raises AuthError if the key is invalid, expired, or belongs to an ended game.
    """
    if not api_key:
        raise AuthError("API key is required")

    repo = GameRepository(session)
    now = datetime.now(UTC).replace(tzinfo=None)

    record = await repo.validate_player_api_key(api_key, now=now)
    if record is None:
        raise AuthError("Invalid or expired API key", expired=True)

    # Additionally check the game hasn't ended since the key was issued.
    game = await repo.get_game(record.game_id)
    if game is not None and game.status == "ended":
        raise AuthError(
            f"Game {record.game_id} has ended — this key is no longer valid",
            expired=True,
        )

    return AuthContext(game_id=record.game_id, player_id=record.player_id)


_bearer_required = HTTPBearer(auto_error=False)
_bearer_optional = HTTPBearer(auto_error=False)


def _route_game_id(request: Request) -> str | None:
    """Return the ``game_id`` the request targets, from path or query.

    Gameplay/diplomacy endpoints expose ``game_id`` as either a path
    parameter (``/games/{game_id}/...``) or a query parameter
    (``/state?game_id=...``). Extract whichever is present so the
    API-key dependency can enforce that the caller's key matches the
    game being addressed.
    """
    path_game_id = request.path_params.get("game_id")
    if path_game_id:
        return path_game_id
    return request.query_params.get("game_id")


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_required),
    session: AsyncSession = Depends(get_database_session),
) -> AuthContext:
    """FastAPI dependency: require a valid per-game API key.

    Returns the resolved ``AuthContext``. A missing, malformed, or
    expired key produces 401. If the URL targets a specific ``game_id``
    (path or query) that doesn't match the key's binding, returns 403 —
    the caller is authenticated, just not for this game.

    Shared by every gameplay/diplomacy REST endpoint. Orthogonal to the
    JWT dependency in ``identity.py`` that authorises lobby-lifecycle
    calls; gameplay keys are never used for lobby work and vice versa.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        auth = await authenticate(session, credentials.credentials)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    requested_game_id = _route_game_id(request)
    if requested_game_id and auth.game_id != requested_game_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key is not valid for this game",
        )
    return auth


async def require_api_key_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
    session: AsyncSession = Depends(get_database_session),
) -> AuthContext | None:
    """Variant of ``require_api_key`` that returns ``None`` when no
    credentials are supplied, instead of 401.

    Used by endpoints (notably ``GET /state``) that allow unauthenticated
    god-mode observation while still applying fog-of-war for authenticated
    players. Malformed or mismatched credentials still produce ``None``
    rather than an error — unauthenticated observation is an explicit
    affordance.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        auth = await authenticate(session, credentials.credentials)
    except AuthError:
        return None

    requested_game_id = _route_game_id(request)
    if requested_game_id and auth.game_id != requested_game_id:
        return None
    return auth


async def expire_keys_for_game(session: AsyncSession, game_id: str) -> int:
    """Expire all API keys for a game (e.g. when the game ends).

    Returns the number of keys expired.
    """
    repo = GameRepository(session)
    return await repo.expire_player_api_keys(game_id=game_id)
