"""Tests for the player API key authentication service (Phase 3)."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.auth import (
    AuthContext,
    AuthError,
    authenticate,
    create_player_key,
    expire_keys_for_game,
    generate_api_key,
)
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import Game, PlayerApiKey
from backend.src.database.repository import GameRepository


@pytest_asyncio.fixture
async def db_session():
    """Create an async DB session with cleanup for test-created rows."""
    await init_db()

    async with async_session_factory() as session:
        yield session
        await session.rollback()
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("auth_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("auth_%")))
        await session.commit()


async def _create_game(session, suffix: str) -> str:
    repo = GameRepository(session)
    game_id = f"auth_{suffix}_{int(time.time() * 1000000)}"
    await repo.create_game(game_id=game_id, players=["alice", "bob"])
    return game_id


# --- generate_api_key ---


def test_generate_api_key_format():
    key = generate_api_key()
    assert key.startswith("fx_")
    # 32 bytes → 64 hex chars + 3 prefix chars = 67
    assert len(key) == 67


def test_generate_api_key_uniqueness():
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100


# --- create_player_key ---


@pytest.mark.asyncio
async def test_create_player_key_returns_plaintext(db_session):
    game_id = await _create_game(db_session, "create")
    key = await create_player_key(db_session, game_id, "alice")
    assert key.startswith("fx_")
    assert len(key) == 67


@pytest.mark.asyncio
async def test_create_player_key_game_not_found(db_session):
    with pytest.raises(AuthError, match="not found"):
        await create_player_key(db_session, "auth_nonexistent", "alice")


@pytest.mark.asyncio
async def test_create_player_key_game_ended(db_session):
    game_id = await _create_game(db_session, "ended")
    repo = GameRepository(db_session)
    await repo.end_game(game_id, winner="alice")
    await db_session.flush()

    with pytest.raises(AuthError, match="has ended"):
        await create_player_key(db_session, game_id, "alice")


# --- authenticate ---


@pytest.mark.asyncio
async def test_authenticate_valid_key(db_session):
    game_id = await _create_game(db_session, "authvalid")
    key = await create_player_key(db_session, game_id, "alice")

    ctx = await authenticate(db_session, key)
    assert isinstance(ctx, AuthContext)
    assert ctx.game_id == game_id
    assert ctx.player_id == "alice"


@pytest.mark.asyncio
async def test_authenticate_empty_key(db_session):
    with pytest.raises(AuthError, match="required"):
        await authenticate(db_session, "")


@pytest.mark.asyncio
async def test_authenticate_invalid_key(db_session):
    with pytest.raises(AuthError, match="Invalid or expired"):
        await authenticate(db_session, "fx_bogus")


@pytest.mark.asyncio
async def test_authenticate_expired_key(db_session):
    game_id = await _create_game(db_session, "authexpired")
    # Create a key with a TTL of 0 seconds (already expired).
    key = await create_player_key(
        db_session, game_id, "alice", ttl=timedelta(seconds=0)
    )

    with pytest.raises(AuthError) as exc_info:
        await authenticate(db_session, key)
    assert exc_info.value.expired is True


@pytest.mark.asyncio
async def test_authenticate_key_for_ended_game(db_session):
    game_id = await _create_game(db_session, "authgameend")
    key = await create_player_key(db_session, game_id, "alice")

    # End the game after issuing the key.
    repo = GameRepository(db_session)
    await repo.end_game(game_id, winner="bob")
    await db_session.flush()

    with pytest.raises(AuthError, match="has ended"):
        await authenticate(db_session, key)


# --- expire_keys_for_game ---


@pytest.mark.asyncio
async def test_expire_keys_for_game(db_session):
    game_id = await _create_game(db_session, "expire")
    key_alice = await create_player_key(db_session, game_id, "alice")
    key_bob = await create_player_key(db_session, game_id, "bob")

    expired_count = await expire_keys_for_game(db_session, game_id)
    assert expired_count == 2

    # Both keys should now be invalid.
    with pytest.raises(AuthError):
        await authenticate(db_session, key_alice)
    with pytest.raises(AuthError):
        await authenticate(db_session, key_bob)


@pytest.mark.asyncio
async def test_expire_keys_does_not_affect_other_games(db_session):
    game_a = await _create_game(db_session, "expireA")
    game_b = await _create_game(db_session, "expireB")
    key_a = await create_player_key(db_session, game_a, "alice")
    key_b = await create_player_key(db_session, game_b, "alice")

    await expire_keys_for_game(db_session, game_a)

    # Game A's key is dead, game B's is still valid.
    with pytest.raises(AuthError):
        await authenticate(db_session, key_a)

    ctx = await authenticate(db_session, key_b)
    assert ctx.game_id == game_b
