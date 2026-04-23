"""
Database connection and session management.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Load environment variables from .env file.
# Try both CWD/.env and backend/.env to support running from project root
# (e.g. via the fourex-mcp entry point) or from backend/ directly.

_backend_dir = Path(__file__).resolve().parent.parent.parent
load_dotenv(_backend_dir / ".env")
load_dotenv()  # Also load CWD .env (won't overwrite existing vars)

# Database configuration.
# ``PARLEY_DATABASE_URL`` is the canonical production name (Railway's Postgres
# plugin is configured to inject it under that key). ``DATABASE_URL`` is kept
# as a backwards-compatible fallback for local ``.env`` files and existing
# CI setups — see ``plans/deployment-prd.md``.
DATABASE_URL = (
    os.getenv("PARLEY_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or "postgresql+asyncpg://fourex:fourex@localhost:5432/fourex"
)
# Railway's Postgres plugin emits a ``postgresql://`` URL; this project uses
# the asyncpg driver, so normalise the scheme so operators don't have to
# hand-edit the injected value.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+asyncpg://" + DATABASE_URL[len("postgres://") :]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+asyncpg://" + DATABASE_URL[len("postgresql://") :]

# Create async engine
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,  # Use NullPool for simplicity in development
    echo=os.getenv("SQL_DEBUG", "false").lower()
    == "true",  # Enable SQL logging if SQL_DEBUG=true
)

# Create session factory
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_database_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to get database session.
    Used with FastAPI dependency injection.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def _run_alembic(cmd: str) -> None:
    """Run ``alembic upgrade head`` or ``alembic downgrade base`` in-process.

    Imported lazily so modules that just need a session don't pay the
    alembic/mako import cost.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    if cmd == "upgrade":
        command.upgrade(cfg, "head")
    elif cmd == "downgrade":
        command.downgrade(cfg, "base")
    else:
        raise ValueError(f"unknown alembic command: {cmd!r}")


async def init_db() -> None:
    """Apply pending Alembic migrations up to ``head``.

    Replaces the historical ``Base.metadata.create_all`` path so every
    environment (prod, local dev, tests) creates its schema through the
    same mechanism. Alembic's ``command.upgrade`` is synchronous and
    calls ``asyncio.run`` internally via ``migrations/env.py`` — running
    it in a worker thread keeps it safe to ``await`` from an existing
    event loop (e.g. FastAPI lifespan, pytest-asyncio tests).
    """
    await asyncio.to_thread(_run_alembic, "upgrade")


async def drop_db() -> None:
    """Downgrade all the way to ``base`` — drops every migration-managed table.

    WARNING: This will delete all data. Used by ``manage_db.py reset``
    and the database init CLI; not used at runtime.
    """
    await asyncio.to_thread(_run_alembic, "downgrade")


async def get_engine() -> AsyncEngine:
    """Get the database engine."""
    return engine


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
