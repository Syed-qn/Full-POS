import pytest

from app.identity.models import Restaurant


@pytest.fixture(autouse=True)
async def restaurant(db_session) -> Restaurant:
    """Seed a restaurant with id=1 so ordering tests can reference restaurant_id=1.

    Ordering tests (per plan) hardcode restaurant_id=1; the FK to restaurants.id
    must be satisfied. id is set explicitly because the per-test rollback does not
    reset the sequence, so a plain insert would not reliably land on id=1.
    """
    row = Restaurant(
        id=1,
        name="Test Restaurant",
        phone="+97141234567",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(row)
    await db_session.flush()
    return row
