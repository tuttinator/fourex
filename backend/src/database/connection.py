"""
Database connection and session management.
"""

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

from .models import Base

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


async def init_db() -> None:
    """
    Initialize database tables.
    Creates all tables defined in models.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """
    Drop all database tables.
    WARNING: This will delete all data!
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def get_engine() -> AsyncEngine:
    """Get the database engine."""
    return engine


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
