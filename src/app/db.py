# src/app/db.py
import os
import sys
from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlparse

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


def _announce_db_target(url: str) -> None:
    """One line on stderr naming WHERE we are about to connect and WHY.

    Deploys fail with a bare "Connect call failed 127.0.0.1:5433" when the
    platform's database variable never reaches the container — the settings
    default then points at a localhost dev database that does not exist in the
    image. The traceback cannot distinguish "variable missing" from "variable
    wrong", which turns every failed deploy into guesswork. Credentials are
    never printed: host, port and database name only.
    """
    try:
        p = urlparse(url)
        # pydantic-settings loads .env into the SETTINGS object, not into the
        # process environment, so os.getenv misses a var that lives only in the
        # .env file and used to mislabel a real DB URL as "BUILT-IN DEFAULT (no
        # database env var set!)" — a false alarm. Compare the RESOLVED url to
        # the field default first; only if it matches is nothing configured.
        from app.config import Settings

        is_default = url == Settings.model_fields["database_url"].default
        if is_default:
            source = "BUILT-IN DEFAULT (no database env var set!)"
        elif os.getenv("APP_DATABASE_URL"):
            source = "APP_DATABASE_URL (env)"
        elif os.getenv("DATABASE_URL"):
            source = "DATABASE_URL (env)"
        else:
            # Not the default and not in the environment → it came from the .env file.
            source = "APP_DATABASE_URL/DATABASE_URL (.env file)"
        print(
            f"[db] connecting to host={p.hostname} port={p.port} "
            f"db={(p.path or '/').lstrip('/')} driver={p.scheme} source={source}",
            file=sys.stderr,
            flush=True,
        )
    except Exception:  # noqa: BLE001 — diagnostics must never break startup
        pass


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
    url = get_settings().database_url
    _announce_db_target(url)
    return create_async_engine(url, poolclass=NullPool)


@lru_cache
def get_session_factory():
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


# Convenience alias for Celery workers
async_session_factory = get_session_factory()
