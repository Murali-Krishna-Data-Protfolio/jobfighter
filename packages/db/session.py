"""
Async DB engine/session setup.

DATABASE_URL selects the backend:
  - unset / not provided -> local SQLite file (sqlite+aiosqlite:///./jobfighter.db)
    so M2 is runnable with zero external infra (no Docker/Postgres needed
    for local dev — see packages/db/models.py's docstring on why the
    schema avoids Postgres-only types).
  - postgresql+asyncpg://... -> the production target per docs/architecture.md.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SQLITE_URL = f"sqlite+aiosqlite:///{(PROJECT_ROOT / 'jobfighter.db').as_posix()}"

DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_SQLITE_URL)

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — one session per request."""
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create tables if they don't exist. Used for local dev / tests where
    running a full Alembic migration is unnecessary overhead; production
    deploys run `alembic upgrade head` instead (see packages/db/migrations/)."""
    from packages.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
