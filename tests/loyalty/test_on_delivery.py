import copy
from decimal import Decimal


from app.dispatch.delivery import advance_delivery
from app.identity.models import DEFAULT_SETTINGS, Restaurant
from app.ordering.models import Customer, Order
from app.wallet import service as wallet


async def _seed_enabled(db_session):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s["loyalty"]["enabled"] = True
    s["loyalty"]["tiers"]["bronze"]["min_orders"] = 1  # easy bronze
    r = Restaurant(name="Deliv R", phone="+97140000088", password_hash="x", lat=25.2, lng=55.2, settings=s)
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500000088", name="C",
                 total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(c)
    await db_session.flush()
    return r, c


async def test_delivery_earns_and_tiers(db_session):
    r, c = await _seed_enabled(db_session)
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="D-1", status="arriving",
              subtotal=Decimal("100.00"), total=Decimal("100.00"))
    db_session.add(o)
    await db_session.flush()

    await advance_delivery(db_session, order_id=o.id, to_status="delivered")
    await db_session.flush()

    c2 = await db_session.get(Customer, c.id)
    assert c2.total_orders == 1           # stats refreshed
    assert c2.loyalty_tier == "bronze"    # tier assigned on delivery
    acc = await wallet.get_or_create_account(db_session, restaurant_id=r.id, customer_id=c.id)
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("5.00")  # 5% earn


async def test_delivery_loyalty_noop_when_disabled(db_session):
    r, c = await _seed_enabled(db_session)
    r.settings = {**r.settings, "loyalty": {**r.settings["loyalty"], "enabled": False}}
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="D-2", status="arriving",
              subtotal=Decimal("100.00"), total=Decimal("100.00"))
    db_session.add(o)
    await db_session.flush()
    await advance_delivery(db_session, order_id=o.id, to_status="delivered")
    c2 = await db_session.get(Customer, c.id)
    assert c2.loyalty_tier is None
    acc = await wallet.get_or_create_account(db_session, restaurant_id=r.id, customer_id=c.id)
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("0.00")
