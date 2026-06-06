import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.identity.models import Restaurant
from app.llm.factory import get_menu_extractor
from app.llm.fake import FakeExtractor


@pytest.fixture
async def restaurant(db_session) -> Restaurant:
    """Seed a minimal restaurant row for prediction FK references.

    Dynamic-PK: tests reference ``restaurant.id`` and never hardcode an id.
    """
    row = Restaurant(
        name="Predictions Test Restaurant",
        phone="+97149997777",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
async def client(engine, db_session):
    """Override the global client fixture to include the predictions router."""
    from app.main import create_app
    from app.predictions.router import router as predictions_router

    app = create_app()
    app.include_router(predictions_router)

    async def _override_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_menu_extractor] = lambda: FakeExtractor()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
