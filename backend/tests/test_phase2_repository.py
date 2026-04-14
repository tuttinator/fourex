"""Integration tests for Phase 2 persistence tables and repository methods."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, inspect

from backend.src.database.connection import async_session_factory, engine, init_db
from backend.src.database.models import (
    AgentMemory,
    Game,
    PlayerApiKey,
    TurnAction,
    TurnSnapshot,
)
from backend.src.database.repository import GameRepository


@pytest_asyncio.fixture
async def db_session():
    """Create an async DB session with cleanup for test-created rows."""
    await init_db()

    async with async_session_factory() as session:
        yield session
        await session.rollback()
        await session.execute(
            delete(AgentMemory).where(AgentMemory.game_id.like("phase2_%"))
        )
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("phase2_%"))
        )
        await session.execute(
            delete(TurnAction).where(TurnAction.game_id.like("phase2_%"))
        )
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("phase2_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("phase2_%")))
        await session.commit()


async def _create_game(repo: GameRepository, suffix: str) -> str:
    game_id = f"phase2_{suffix}_{int(time.time() * 1000000)}"
    await repo.create_game(game_id=game_id, players=["alice", "bob"])
    return game_id


@pytest.mark.asyncio
async def test_phase2_tables_exist(db_session):
    """New Phase 2 tables should exist in the database metadata."""

    def _table_names(sync_conn):
        return set(inspect(sync_conn).get_table_names())

    async with engine.begin() as conn:
        table_names = await conn.run_sync(_table_names)

    assert "agent_memory" in table_names
    assert "turn_snapshots" in table_names
    assert "turn_actions" in table_names
    assert "player_api_keys" in table_names


@pytest.mark.asyncio
async def test_agent_memory_upsert_and_read(db_session):
    repo = GameRepository(db_session)
    game_id = await _create_game(repo, "memory")

    created = await repo.upsert_agent_memory(game_id, "alice", 3, "Scout north")
    assert created.scratchpad_text == "Scout north"

    updated = await repo.upsert_agent_memory(game_id, "alice", 3, "Defend city")
    assert updated.id == created.id
    assert updated.scratchpad_text == "Defend city"

    stored = await repo.get_agent_memory(game_id, "alice", 3)
    assert stored is not None
    assert stored.scratchpad_text == "Defend city"


@pytest.mark.asyncio
async def test_turn_snapshot_upsert_and_read(db_session):
    repo = GameRepository(db_session)
    game_id = await _create_game(repo, "snapshot")

    snapshot = {"turn": 5, "visible_tiles": 22}
    created = await repo.upsert_turn_snapshot(game_id, "alice", 5, snapshot)
    assert created.state_json == snapshot

    updated = await repo.upsert_turn_snapshot(
        game_id, "alice", 5, {"turn": 5, "visible_tiles": 23}
    )
    assert updated.id == created.id

    stored = await repo.get_turn_snapshot(game_id, "alice", 5)
    assert stored is not None
    assert stored.state_json["visible_tiles"] == 23


@pytest.mark.asyncio
async def test_turn_action_upsert_and_read(db_session):
    repo = GameRepository(db_session)
    game_id = await _create_game(repo, "action")

    actions = [{"type": "MOVE", "unit_id": 1, "to": {"x": 4, "y": 5}}]
    created = await repo.upsert_turn_action(game_id, "alice", 2, actions)
    assert created.actions_json == actions

    updated_actions = [{"type": "FOUND_CITY", "worker_id": 1}]
    updated = await repo.upsert_turn_action(game_id, "alice", 2, updated_actions)
    assert updated.id == created.id

    stored = await repo.get_turn_action(game_id, "alice", 2)
    assert stored is not None
    assert stored.actions_json == updated_actions


@pytest.mark.asyncio
async def test_player_api_key_create_validate_and_expire(db_session):
    repo = GameRepository(db_session)
    game_id = await _create_game(repo, "apikey")
    plaintext_key = "phase2-test-key"
    expires_at = datetime.utcnow() + timedelta(hours=1)

    created = await repo.create_player_api_key(
        game_id=game_id,
        player_id="alice",
        plaintext_key=plaintext_key,
        expires_at=expires_at,
    )
    assert created.key_hash != plaintext_key
    assert len(created.key_hash) == 64

    valid = await repo.validate_player_api_key(plaintext_key, now=datetime.utcnow())
    assert valid is not None
    assert valid.game_id == game_id
    assert valid.player_id == "alice"

    expired_count = await repo.expire_player_api_keys(
        game_id=game_id,
        player_id="alice",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )
    assert expired_count == 1

    invalid_after_expiry = await repo.validate_player_api_key(
        plaintext_key, now=datetime.utcnow()
    )
    assert invalid_after_expiry is None
