"""Schema-parity check between ``alembic upgrade head`` and ``Base.metadata.create_all``.

Phase 1 acceptance from ``plans/pure-migrations.md``: the alembic
baseline migration plus all subsequent deltas must produce a schema
equivalent to ``Base.metadata.create_all`` from ``models.py``. If the
two paths drift, migrations and models are no longer in sync and the
plan's "alembic is the sole schema owner" goal is broken.

The test:

1. Creates two throwaway Postgres databases side by side.
2. Populates one via ``alembic upgrade head`` (subprocess, because
   ``migrations/env.py`` calls ``asyncio.run`` internally and that
   cannot nest inside the pytest-asyncio loop).
3. Populates the other via ``Base.metadata.create_all``.
4. Reflects ``MetaData`` from each and compares tables, columns,
   indexes, unique constraints, and foreign keys.
5. Drops both databases, even on failure.

Differences deliberately ignored when comparing:

- The ``alembic_version`` bookkeeping table (only present on the
  migrated side).
- Constraint names (the plan calls out "modulo constraint naming"
  — ``auth_verification_tokens_pkey`` vs ``pk_auth_verification_tokens``
  are equivalent, and autogenerate picks different names than
  SQLAlchemy's declarative defaults).

Server defaults ARE compared: the model's timestamp columns use
``server_default=func.now()`` (not the client-side
``default=func.now()``), so ``create_all`` and the alembic chain
both emit ``DEFAULT now()`` in the DDL and the reflected
``server_default`` values line up.

Skips if no Postgres is reachable at the default dev URL — CI can
opt in by setting ``PARLEY_TEST_DATABASE_URL`` to a Postgres that
the worker has CREATE DATABASE on.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine

from backend.src.database.models import Base

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _admin_url() -> str:
    """Admin URL (postgres database) derived from the configured DB URL."""
    raw = (
        os.getenv("PARLEY_TEST_DATABASE_URL")
        or os.getenv("PARLEY_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql://caleb@localhost:5432/fourex"
    )
    if raw.startswith("postgresql+asyncpg://"):
        raw = "postgresql://" + raw[len("postgresql+asyncpg://") :]
    parsed = urlparse(raw)
    return urlunparse(parsed._replace(path="/postgres"))


def _db_url(db_name: str, driver: str = "postgresql+asyncpg") -> str:
    parsed = urlparse(_admin_url())
    return urlunparse(parsed._replace(scheme=driver, path=f"/{db_name}"))


async def _postgres_reachable() -> bool:
    try:
        conn = await asyncpg.connect(_admin_url())
    except (OSError, asyncpg.PostgresError):
        return False
    await conn.close()
    return True


@pytest_asyncio.fixture
async def two_fresh_dbs() -> AsyncIterator[tuple[str, str]]:
    """Create two empty databases, yield their names, drop them on teardown."""
    if not await _postgres_reachable():
        pytest.skip("Postgres not reachable — set PARLEY_TEST_DATABASE_URL to run")

    suffix = uuid.uuid4().hex[:8]
    alembic_db = f"fourex_alembic_{suffix}"
    createall_db = f"fourex_createall_{suffix}"

    admin = await asyncpg.connect(_admin_url())
    try:
        await admin.execute(f'CREATE DATABASE "{alembic_db}"')
        await admin.execute(f'CREATE DATABASE "{createall_db}"')
    finally:
        await admin.close()

    try:
        yield alembic_db, createall_db
    finally:
        admin = await asyncpg.connect(_admin_url())
        try:
            for db in (alembic_db, createall_db):
                # Disconnect any lingering sessions before drop.
                await admin.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = $1 AND pid <> pg_backend_pid()
                    """,
                    db,
                )
                await admin.execute(f'DROP DATABASE IF EXISTS "{db}"')
        finally:
            await admin.close()


def _run_alembic_upgrade(db_name: str) -> None:
    env = os.environ.copy()
    env["PARLEY_DATABASE_URL"] = _db_url(db_name)
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(_BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed:\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


async def _run_create_all(db_name: str) -> None:
    engine = create_async_engine(_db_url(db_name))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


async def _reflect(db_name: str) -> MetaData:
    engine = create_async_engine(_db_url(db_name))
    md = MetaData()
    try:
        async with engine.connect() as conn:
            await conn.run_sync(md.reflect)
    finally:
        await engine.dispose()
    return md


def _normalise_server_default(col) -> str | None:
    """Reflected ``server_default`` text, normalised to compare across paths.

    Postgres reflects ``DEFAULT now()`` as either ``now()`` or
    ``CURRENT_TIMESTAMP`` depending on driver quirks; equate them.
    """
    sd = col.server_default
    if sd is None:
        return None
    # ``DefaultClause.arg`` is a TextClause or SQL element.
    text = str(getattr(sd, "arg", sd)).strip().lower()
    if text in {"now()", "current_timestamp"}:
        return "now()"
    return text


def _summarise_table(table) -> dict:
    """Structural snapshot of a table — comparable across migration paths.

    Deliberately omits constraint names; see module docstring.
    """
    return {
        "columns": {
            col.name: {
                "type": str(col.type),
                "nullable": col.nullable,
                "primary_key": col.primary_key,
                "server_default": _normalise_server_default(col),
            }
            for col in table.columns
        },
        "primary_key": sorted(col.name for col in table.primary_key.columns),
        "indexes": sorted(
            (tuple(c.name for c in idx.columns), bool(idx.unique))
            for idx in table.indexes
        ),
        "unique_constraints": sorted(
            tuple(sorted(col.name for col in uq.columns))
            for uq in table.constraints
            if uq.__class__.__name__ == "UniqueConstraint"
        ),
        "foreign_keys": sorted(
            (fk.parent.name, fk.column.table.name, fk.column.name)
            for fk in table.foreign_keys
        ),
    }


@pytest.mark.asyncio
async def test_alembic_upgrade_matches_create_all(
    two_fresh_dbs: tuple[str, str],
) -> None:
    alembic_db, createall_db = two_fresh_dbs

    # Alembic must run in its own process — env.py opens its own event loop
    # via asyncio.run(run_async_migrations()), which cannot nest inside the
    # pytest-asyncio loop we're already in.
    await asyncio.to_thread(_run_alembic_upgrade, alembic_db)
    await _run_create_all(createall_db)

    md_alembic = await _reflect(alembic_db)
    md_createall = await _reflect(createall_db)

    alembic_tables = {
        name: t for name, t in md_alembic.tables.items() if name != "alembic_version"
    }
    createall_tables = dict(md_createall.tables)

    assert set(alembic_tables) == set(createall_tables), (
        "table set diverges between alembic and create_all: "
        f"only-alembic={sorted(set(alembic_tables) - set(createall_tables))}, "
        f"only-createall={sorted(set(createall_tables) - set(alembic_tables))}"
    )

    differences: list[str] = []
    for name in sorted(alembic_tables):
        a = _summarise_table(alembic_tables[name])
        c = _summarise_table(createall_tables[name])
        if a != c:
            differences.append(f"{name}:\n  alembic={a}\n  createall={c}")

    assert not differences, "schema drift:\n" + "\n".join(differences)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
