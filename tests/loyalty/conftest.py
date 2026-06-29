import copy

import pytest

from app.identity.models import DEFAULT_SETTINGS, Restaurant
from app.ordering.models import Customer


@pytest.fixture
def loyalty_settings() -> dict:
    """A settings dict with loyalty ENABLED (defaults otherwise)."""
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s["loyalty"]["enabled"] = True
    return s


@pytest.fixture
async def seed_rc(db_session) -> tuple[int, int]:
    r = Restaurant(name="Loyalty R", phone="+97140000077", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500000077", name="Loyal Cust")
    db_session.add(c)
    await db_session.flush()
    return r.id, c.id
