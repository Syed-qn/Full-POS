# tests/conftest.py
import os

os.environ["APP_DATABASE_URL"] = (
    "postgresql+asyncpg://app:app@localhost:5433/restaurant_test"
)

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
import app.audit.models  # noqa: F401


@pytest.fixture
async def engine():
    eng = create_async_engine(os.environ["APP_DATABASE_URL"])
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
