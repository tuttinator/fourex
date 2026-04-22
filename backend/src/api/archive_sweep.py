"""Phase 5 (spectated-agents): auto-archive sweep.

Single implementation used by both the in-process background loop (started
from the FastAPI lifespan) and the on-demand ``mise run db-archive-stale``
task. Thresholds come from ``settings`` so operators can tune them per
deployment without code changes.

Rules:

- ``status='waiting'`` AND ``created_at < now - waiting_days`` → archive
  with ``archived_reason='stale_waiting'``. Status is left as ``waiting``
  so that an unarchive restores the lobby verbatim.
- ``status='active'`` AND ``turn_started_at < now - active_days`` →
  transition to ``status='ended'`` with ``end_reason='abandoned'`` (no
  winner), then archive with ``archived_reason='stale_active'``.

Idempotent: already-archived rows are filtered out of the scan, and the
repo's archive path is itself guarded on ``archived_at IS NULL``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database.connection import async_session_factory
from ..database.models import Game
from ..database.repository import GameRepository

logger = logging.getLogger(__name__)


async def archive_stale_games(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    waiting_threshold_days: int | None = None,
    active_threshold_days: int | None = None,
) -> dict[str, int]:
    """Archive stale waiting lobbies and dormant active games.

    Returns a summary dict with counts: ``waiting_archived``,
    ``active_archived``, ``total``. Callers are responsible for
    committing the session.
    """
    current = now or datetime.now(UTC).replace(tzinfo=None)
    wait_days = (
        waiting_threshold_days
        if waiting_threshold_days is not None
        else settings.archive_stale_waiting_days
    )
    act_days = (
        active_threshold_days
        if active_threshold_days is not None
        else settings.archive_stale_active_days
    )
    wait_cutoff = current - timedelta(days=wait_days)
    act_cutoff = current - timedelta(days=act_days)

    repo = GameRepository(session)

    waiting_stmt = select(Game).where(
        and_(
            Game.status == "waiting",
            Game.archived_at.is_(None),
            Game.created_at < wait_cutoff,
        )
    )
    waiting_rows = list((await session.execute(waiting_stmt)).scalars().all())
    for row in waiting_rows:
        await repo.archive_game(row.id, reason="stale_waiting")

    active_stmt = select(Game).where(
        and_(
            Game.status == "active",
            Game.archived_at.is_(None),
            Game.turn_started_at.is_not(None),
            Game.turn_started_at < act_cutoff,
        )
    )
    active_rows = list((await session.execute(active_stmt)).scalars().all())
    for row in active_rows:
        await repo.end_game(
            row.id,
            winner=None,
            victory_type="abandoned",
            end_reason="abandoned",
        )
        await repo.archive_game(row.id, reason="stale_active")

    return {
        "waiting_archived": len(waiting_rows),
        "active_archived": len(active_rows),
        "total": len(waiting_rows) + len(active_rows),
    }


async def run_sweep_once() -> dict[str, int]:
    """Run the sweep in its own session and commit.

    Used by the ``mise run db-archive-stale`` task and by the
    background loop. Rolls back and re-raises on failure so the caller
    can surface the error; the loop in ``archive_sweep_loop`` wraps
    this to keep ticking despite transient failures.
    """
    async with async_session_factory() as session:
        try:
            summary = await archive_stale_games(session)
            await session.commit()
            return summary
        except Exception:
            await session.rollback()
            raise


async def archive_sweep_loop(interval_seconds: int | None = None) -> None:
    """Long-running background loop that sweeps on a fixed cadence.

    The first sweep runs *after* the first sleep, not immediately on
    startup. This keeps FastAPI boot cheap and avoids a thundering-herd
    where every process restart triggers a DB pass.
    """
    interval = interval_seconds or settings.archive_sweep_interval_seconds
    logger.info("archive_sweep_loop starting (interval=%ds)", interval)
    try:
        while True:
            await asyncio.sleep(interval)
            try:
                summary = await run_sweep_once()
                if summary["total"] > 0:
                    logger.info(
                        "archive_sweep archived %s games (waiting=%s, active=%s)",
                        summary["total"],
                        summary["waiting_archived"],
                        summary["active_archived"],
                    )
            except Exception:
                logger.exception("archive_sweep iteration failed")
    except asyncio.CancelledError:
        logger.info("archive_sweep_loop cancelled")
        raise
