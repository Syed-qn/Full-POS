# src/app/db.py
from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache

from sqlalchemy import func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


@lru_cache
def get_engine():
    # NullPool: open a fresh asyncpg connection per checkout and close it on release.
    # Why not a pooled engine with pool_pre_ping=True? On Render the managed Postgres
    # drops idle connections, and the SAME cached async engine is shared by the web app
    # and the Celery workers (which run each task in their OWN event loop via
    # asyncio.run). A pooled connection bound to one event loop, then pre-pinged from
    # another, raises `MissingGreenlet: greenlet_spawn has not been called` and 500s the
    # request (e.g. login). NullPool sidesteps all of that: every checkout is a new
    # connection in the CURRENT loop, never stale, never cross-loop. Slightly more
    # connect overhead, negligible at this app's scale and far safer.
    return create_async_engine(get_settings().database_url, poolclass=NullPool)


@lru_cache
def get_session_factory():
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


# Convenience alias for Celery workers
async_session_factory = get_session_factory()
