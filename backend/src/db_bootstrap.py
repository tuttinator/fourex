"""
First-boot database bootstrap for the production container.

Historically this project used ``Base.metadata.create_all`` (via the
FastAPI lifespan's ``init_db``) to materialise tables; Alembic was only
adopted mid-project for incremental schema changes. As a result, the
earliest Alembic revisions assume baseline tables like ``games`` and
``player_actions`` already exist and jump straight to creating their
deltas (e.g. ``agent_memory`` with a foreign key to ``games.id``).

On a fresh production database there are no tables at all, so running
``alembic upgrade head`` blind crashes on the first FK reference. This
module implements the canonical "legacy bootstrap" pattern:

- If the ``alembic_version`` table does not exist, this is a first
  boot. Run ``create_all`` (producing the full current schema in one
  shot, consistent with historical local-dev behaviour) and then
  ``alembic stamp head`` to mark every migration as applied without
  re-running them.
- Otherwise the database is already managed by Alembic and we just
  run ``alembic upgrade head`` to apply any pending deltas.

The container entrypoint invokes ``python -m backend.src.db_bootstrap``
before starting the servers.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_BACKEND_DIR = Path(__file__).resolve().parent.parent  # .../backend


def _database_url() -> str:
    url = os.getenv("PARLEY_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit(
            "db_bootstrap: neither PARLEY_DATABASE_URL nor DATABASE_URL is set"
        )
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


async def _alembic_initialised(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT to_regclass('public.alembic_version')")
            )
            return result.scalar() is not None
    finally:
        await engine.dispose()


async def _create_all(url: str) -> None:
    # Imported lazily so ``-m backend.src.db_bootstrap`` doesn't pull the
    # full models graph in cases where all we need is ``upgrade``.
    from .database.models import Base

    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


def _alembic_config(url: str) -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def main() -> None:
    url = _database_url()

    # ``migrations/env.py`` does ``from src.database.models import Base`` and
    # the alembic.ini's ``prepend_sys_path = .`` assumes CWD is ``backend/``.
    # Run alembic commands from there so imports resolve regardless of where
    # this script was invoked from.
    os.chdir(_BACKEND_DIR)

    # Alembic commands spin up their own ``asyncio.run()`` inside env.py, so
    # the surrounding code must stay synchronous — a nested event loop would
    # raise ``RuntimeError: asyncio.run() cannot be called from a running
    # event loop``. The async helpers are each wrapped in their own
    # ``asyncio.run`` and completed before control returns to alembic.
    initialised = asyncio.run(_alembic_initialised(url))

    if initialised:
        print("[db_bootstrap] alembic_version exists — running upgrade head")
        command.upgrade(_alembic_config(url), "head")
        return

    print("[db_bootstrap] first boot — creating all tables + stamping head")
    asyncio.run(_create_all(url))
    command.stamp(_alembic_config(url), "head")
    print("[db_bootstrap] bootstrap complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surface any failure verbatim
        print(f"[db_bootstrap] failed: {exc}", file=sys.stderr)
        raise
