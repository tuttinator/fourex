"""
Player API key authentication service.

Transport-agnostic layer used by both MCP tools and REST endpoints.
Generates cryptographically random API keys, stores SHA-256 hashes,
and validates incoming keys to resolve (game_id, player_id).
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

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
) -> str:
    """Generate and persist a new API key for a player in a game.

    Returns the plaintext key. Only the SHA-256 hash is stored.
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


async def expire_keys_for_game(session: AsyncSession, game_id: str) -> int:
    """Expire all API keys for a game (e.g. when the game ends).

    Returns the number of keys expired.
    """
    repo = GameRepository(session)
    return await repo.expire_player_api_keys(game_id=game_id)
