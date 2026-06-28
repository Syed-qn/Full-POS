import pytest

from app.identity.models import Restaurant
from app.ordering.models import Customer


@pytest.fixture
async def seed_restaurant_customer(db_session) -> tuple[int, int]:
    r = Restaurant(
        name="Coupon Test Restaurant",
        phone="+97140000002",
        password_hash="x",
        lat=25.2,
        lng=55.2,
    )
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500000002", name="Coupon Cust")
    db_session.add(c)
    await db_session.flush()
    return r.id, c.id
