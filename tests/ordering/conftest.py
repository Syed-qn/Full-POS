import pytest

from app.identity.models import Restaurant


@pytest.fixture
async def restaurant(db_session) -> Restaurant:
    """Seed a minimal restaurant row required for ordering FKs.

    Non-autouse and dynamic-PK: tests must take this fixture and reference
    ``restaurant.id`` rather than hardcoding ``restaurant_id=1``. Pinning the
    PK is a known footgun (the per-test rollback does not reset the sequence,
    and an HTTP signup in the same test would collide on restaurants_pkey).
    """
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
