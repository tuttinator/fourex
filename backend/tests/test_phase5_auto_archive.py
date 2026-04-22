"""Phase 5 spectated-agents: auto-archive sweep.

Covers the Phase 5 acceptance criteria in ``plans/spectated-agents.md``:

- Stale ``waiting`` lobbies older than the threshold are archived with
  ``archived_reason='stale_waiting'`` and retain ``status='waiting'``.
- Dormant ``active`` games (no ``turn_started_at`` progress within the
  threshold) transition to ``status='ended'`` with
  ``end_reason='abandoned'`` and are archived with
  ``archived_reason='stale_active'``.
- Fresh games are not swept.
- The sweep is idempotent: running it twice does not re-stamp
  ``archived_at``.
- Snapshots taken prior to archival remain queryable via the
  existing turn-history read path.
- Thresholds are configurable via function arguments (matching the
  settings override path used by the mise task).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, update

from backend.src.api.archive_sweep import archive_stale_games, run_sweep_once
from backend.src.database.connection import async_session_factory, init_db
from backend.src.database.models import Game, PlayerApiKey, TurnSnapshot
from backend.src.database.repository import GameRepository
from backend.src.game.models import GameState


@pytest_asyncio.fixture
async def _clean_sweep_rows() -> None:
    await init_db()
    async with async_session_factory() as session:
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("sweep_%"))
        )
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("sweep_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("sweep_%")))
        await session.commit()
    yield
    async with async_session_factory() as session:
        await session.execute(
            delete(TurnSnapshot).where(TurnSnapshot.game_id.like("sweep_%"))
        )
        await session.execute(
            delete(PlayerApiKey).where(PlayerApiKey.game_id.like("sweep_%"))
        )
        await session.execute(delete(Game).where(Game.id.like("sweep_%")))
        await session.commit()


def _game_id(suffix: str) -> str:
    return f"sweep_{suffix}_{int(time.time() * 1000000)}"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed_waiting(
    game_id: str, *, created_days_ago: int
) -> None:
    """Insert a waiting lobby with a back-dated ``created_at``."""
    async with async_session_factory() as session:
        repo = GameRepository(session)
        await repo.create_game(
            game_id=game_id,
            players=[],
            seed=42,
            status="waiting",
            creator="alice",
        )
        backdate = _utcnow() - timedelta(days=created_days_ago)
        await session.execute(
            update(Game).where(Game.id == game_id).values(created_at=backdate)
        )
        await session.commit()


async def _seed_active(
    game_id: str, *, turn_started_days_ago: int
) -> None:
    """Insert an active game with a back-dated ``turn_started_at``."""
    async with async_session_factory() as session:
        repo = GameRepository(session)
        await repo.create_game(
            game_id=game_id,
            players=["alice", "bob"],
            seed=42,
            status="active",
            creator="alice",
        )
        state = GameState(
            rng_state=42,
            tiles=[],
            players=["alice", "bob"],
            map_width=20,
            map_height=20,
            max_turns=100,
        )
        await repo.update_game_state(game_id, state)
        backdate = _utcnow() - timedelta(days=turn_started_days_ago)
        await session.execute(
            update(Game)
            .where(Game.id == game_id)
            .values(turn_started_at=backdate)
        )
        await session.commit()


async def _get(game_id: str) -> Game:
    async with async_session_factory() as session:
        repo = GameRepository(session)
        row = await repo.get_game(game_id)
        assert row is not None
        return row


@pytest.mark.asyncio
async def test_stale_waiting_lobby_is_archived_with_reason(
    _clean_sweep_rows: None,
) -> None:
    game_id = _game_id("waiting_stale")
    await _seed_waiting(game_id, created_days_ago=10)

    summary = await run_sweep_once()

    row = await _get(game_id)
    assert row.archived_at is not None
    assert row.archived_reason == "stale_waiting"
    assert row.status == "waiting"  # status preserved for restore
    assert summary["waiting_archived"] >= 1


@pytest.mark.asyncio
async def test_fresh_waiting_lobby_is_not_archived(
    _clean_sweep_rows: None,
) -> None:
    game_id = _game_id("waiting_fresh")
    await _seed_waiting(game_id, created_days_ago=2)

    await run_sweep_once()

    row = await _get(game_id)
    assert row.archived_at is None
    assert row.archived_reason is None


@pytest.mark.asyncio
async def test_dormant_active_game_is_ended_and_archived(
    _clean_sweep_rows: None,
) -> None:
    game_id = _game_id("active_stale")
    await _seed_active(game_id, turn_started_days_ago=20)

    summary = await run_sweep_once()

    row = await _get(game_id)
    assert row.status == "ended"
    assert row.end_reason == "abandoned"
    assert row.winner is None
    assert row.archived_at is not None
    assert row.archived_reason == "stale_active"
    assert summary["active_archived"] >= 1


@pytest.mark.asyncio
async def test_fresh_active_game_is_not_archived(
    _clean_sweep_rows: None,
) -> None:
    game_id = _game_id("active_fresh")
    await _seed_active(game_id, turn_started_days_ago=3)

    await run_sweep_once()

    row = await _get(game_id)
    assert row.status == "active"
    assert row.archived_at is None
    assert row.end_reason is None


@pytest.mark.asyncio
async def test_sweep_is_idempotent(_clean_sweep_rows: None) -> None:
    game_id = _game_id("idem")
    await _seed_waiting(game_id, created_days_ago=10)

    first_summary = await run_sweep_once()
    first_row = await _get(game_id)
    assert first_row.archived_at is not None
    first_archived_at = first_row.archived_at

    second_summary = await run_sweep_once()
    second_row = await _get(game_id)
    # ``archived_at`` stays pinned to the first sweep's timestamp — the
    # repo.archive_game WHERE clause filters out already-archived rows.
    assert second_row.archived_at == first_archived_at
    # And the second pass doesn't double-count this row.
    assert second_summary["waiting_archived"] < first_summary["waiting_archived"] + 1


@pytest.mark.asyncio
async def test_thresholds_are_configurable(_clean_sweep_rows: None) -> None:
    """The sweep function accepts per-call overrides (mirrors the settings
    path used by the in-process loop and the mise task)."""
    stale_id = _game_id("configurable_stale")
    fresh_id = _game_id("configurable_fresh")
    await _seed_waiting(stale_id, created_days_ago=4)
    await _seed_waiting(fresh_id, created_days_ago=1)

    async with async_session_factory() as session:
        # 3-day threshold: the 4-day-old lobby is stale, the 1-day isn't.
        await archive_stale_games(
            session,
            waiting_threshold_days=3,
            active_threshold_days=14,
        )
        await session.commit()

    stale_row = await _get(stale_id)
    fresh_row = await _get(fresh_id)
    assert stale_row.archived_reason == "stale_waiting"
    assert fresh_row.archived_at is None


@pytest.mark.asyncio
async def test_turn_snapshots_remain_queryable_after_sweep(
    _clean_sweep_rows: None,
) -> None:
    game_id = _game_id("snapshots_survive")
    await _seed_active(game_id, turn_started_days_ago=20)

    # Seed a turn snapshot before the sweep runs.
    async with async_session_factory() as session:
        repo = GameRepository(session)
        await repo.upsert_turn_snapshot(
            game_id=game_id,
            player_id="alice",
            turn_number=1,
            state_json={"turn": 1, "players": ["alice", "bob"]},
        )
        await session.commit()

    await run_sweep_once()

    async with async_session_factory() as session:
        repo = GameRepository(session)
        snap = await repo.get_turn_snapshot(game_id, "alice", 1)
        assert snap is not None
        assert snap.state_json == {"turn": 1, "players": ["alice", "bob"]}


@pytest.mark.asyncio
async def test_active_game_without_turn_started_at_is_skipped(
    _clean_sweep_rows: None,
) -> None:
    """A legacy active row with ``turn_started_at IS NULL`` shouldn't be
    archived: there's no timestamp to compare against the threshold."""
    game_id = _game_id("active_no_ts")
    async with async_session_factory() as session:
        repo = GameRepository(session)
        await repo.create_game(
            game_id=game_id,
            players=["alice", "bob"],
            seed=42,
            status="active",
            creator="alice",
        )
        # Explicitly leave ``turn_started_at`` null.
        await session.commit()

    await run_sweep_once()

    row = await _get(game_id)
    assert row.archived_at is None
    assert row.status == "active"
