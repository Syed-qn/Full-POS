# tests/conftest.py
import os

os.environ["APP_DATABASE_URL"] = (
    "postgresql+asyncpg://app:app@localhost:5433/restaurant_test"
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db import Base
import app.audit.models  # noqa: F401
import app.identity.models  # noqa: F401


@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(os.environ["APP_DATABASE_URL"])
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine):
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        yield session
        await session.close()
        await trans.rollback()


from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import get_session  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
async def client(engine, db_session):
    app = create_app()

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
