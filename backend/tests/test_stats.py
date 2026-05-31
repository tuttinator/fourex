"""Tests for the public landing-page stats aggregation.

Exercises ``GameRepository.count_active_agents`` and
``PersistentGameController.get_stats``. Mirrors the Phase 2 repository test
setup: a real DB via ``init_db()`` with prefix-scoped cleanup, and assertions
on *deltas* so the test is robust against rows left by other suites.
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.src.api.persistent_game_controller import PersistentGameController
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import Game, PlayerApiKey


@pytest_asyncio.fixture
async def db_session():
    """Async DB session that cleans up ``stats_%`` rows on teardown."""
    await init_db()
    async with async_session_factory() as session:
        yield session
        await session.rollback()
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("stats_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("stats_%")))
        await session.commit()


def _gid(suffix: str) -> str:
    return f"stats_{suffix}_{int(time.time() * 1_000_000)}"


@pytest.mark.asyncio
async def test_get_stats_counts_finished_and_active_seats(db_session):
    controller = PersistentGameController(db_session)
    repo = controller.repo

    before = await controller.get_stats()

    # Two active games → +5 seats in the field, +2 active, +2 total.
    await repo.create_game(
        game_id=_gid("active1"), players=["alice", "bob"], status="active"
    )
    await repo.create_game(
        game_id=_gid("active2"),
        players=["carol", "dave", "erin"],
        status="active",
    )
    # One finished game → +1 played, +1 total; its seats are NOT in the field.
    done = _gid("done")
    await repo.create_game(game_id=done, players=["frank", "grace"], status="active")
    await repo.end_game(done, winner="frank", victory_type="domination")
    # A waiting lobby → +1 total only.
    await repo.create_game(game_id=_gid("lobby"), players=["heidi"], status="waiting")
    await db_session.flush()

    after = await controller.get_stats()
    assert after["games_played"] - before["games_played"] == 1
    assert after["agents_in_field"] - before["agents_in_field"] == 5
    assert after["active_games"] - before["active_games"] == 2
    assert after["total_games"] - before["total_games"] == 4


@pytest.mark.asyncio
async def test_active_agents_excludes_archived(db_session):
    controller = PersistentGameController(db_session)
    repo = controller.repo

    before_field = await repo.count_active_agents()
    before_active = await repo.count_games(status="active")

    await repo.create_game(
        game_id=_gid("a3"), players=["ivan", "judy"], status="active"
    )
    arch = _gid("arch")
    await repo.create_game(game_id=arch, players=["mallory", "niaj"], status="active")
    await repo.archive_game(arch, reason="manual")
    await db_session.flush()

    # Archived active game contributes to neither field nor active count.
    assert await repo.count_active_agents() - before_field == 2
    assert await repo.count_games(status="active") - before_active == 1
