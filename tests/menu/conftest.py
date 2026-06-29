import pytest

from app.identity.models import Restaurant


@pytest.fixture
async def restaurant(db_session) -> Restaurant:
    row = Restaurant(
        name="Test Restaurant",
        phone="+97141234567",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(row)
    await db_session.flush()
    return row