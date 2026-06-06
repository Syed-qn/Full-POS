import pytest

from app.identity.models import Restaurant


@pytest.fixture
async def restaurant(db_session) -> Restaurant:
    """Seed a minimal restaurant row for opt-out FK references.

    Dynamic-PK: tests reference ``restaurant.id`` and never hardcode an id.
    """
    row = Restaurant(
        name="Marketing Test Restaurant",
        phone="+97149998888",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(row)
    await db_session.flush()
    return row
