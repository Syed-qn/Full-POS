import pytest

from app.identity.models import Restaurant
from app.ordering.models import Customer


@pytest.fixture
async def seed_restaurant_customer(db_session) -> tuple[int, int]:
    """Insert a restaurant + customer; return (restaurant_id, customer_id).

    Dynamic PKs (no hardcoded ids) — the per-test rollback does not reset
    sequences, so reference the returned ids.
    """
    r = Restaurant(
        name="Wallet Test Restaurant",
        phone="+97140000001",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500000001", name="Wallet Cust")
    db_session.add(c)
    await db_session.flush()
    return r.id, c.id
