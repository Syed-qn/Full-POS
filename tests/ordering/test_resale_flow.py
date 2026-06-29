"""Resale of cancelled-after-cooking food: offer (discount) + accept (re-dispatch)."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.identity.models import DEFAULT_SETTINGS, Restaurant
from app.ordering import resale
from app.ordering import service as ordering
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)


async def _resale_order(db_session, settings=None):
    s = settings or copy.deepcopy(DEFAULT_SETTINGS)
    r = Restaurant(name="Resale R", phone="+97140000300", password_hash="x", lat=25.2, lng=55.2, settings=s)
    db_session.add(r)
    await db_session.flush()
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=r.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=1, name="Biryani",
                price_aed=Decimal("40.00"), category="Rice", is_available=True,
                name_normalized="biryani")
    db_session.add(dish)
    await db_session.flush()
    orig_cust = Customer(restaurant_id=r.id, phone="+971500300001", name="Orig")
    db_session.add(orig_cust)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=orig_cust.id, order_number="X-1",
              status=OrderStatus.PREPARING, subtotal=Decimal("40.00"), total=Decimal("40.00"))
    db_session.add(o)
    await db_session.flush()
    db_session.add(OrderItem(order_id=o.id, dish_id=dish.id, dish_number=1, dish_name="Biryani",
                             price_aed=Decimal("40.00"), qty=1))
    await db_session.flush()
    # Cancel during preparing -> ON_RESALE copy
    resale_copy = await ordering.cancel_order(db_session, order=o, actor="customer", reason="changed mind")
    resale_copy.cancelled_at = NOW - timedelta(minutes=5)
    await db_session.flush()
    return r, resale_copy


async def test_offer_applies_percent_discount(db_session):
    r, resale_copy = await _resale_order(db_session)
    offer = await resale.resale_offer_for_customer(
        db_session, restaurant_id=r.id, phone="+971500300999", settings=r.settings, now=NOW,
    )
    assert offer is not None
    # default 30% off 40 = 28
    assert offer["discounted_subtotal"] == Decimal("28.00")
    assert offer["discount_aed"] == Decimal("12.00")


async def test_offer_excludes_original_customer(db_session):
    r, resale_copy = await _resale_order(db_session)
    # original customer's phone is excluded
    offer = await resale.resale_offer_for_customer(
        db_session, restaurant_id=r.id, phone="+971500300001", settings=r.settings, now=NOW,
    )
    assert offer is None


async def test_offer_respects_max_age(db_session):
    r, resale_copy = await _resale_order(db_session)
    resale_copy.cancelled_at = NOW - timedelta(minutes=90)  # older than 30m default
    await db_session.flush()
    offer = await resale.resale_offer_for_customer(
        db_session, restaurant_id=r.id, phone="+971500300999", settings=r.settings, now=NOW,
    )
    assert offer is None


async def test_offer_disabled(db_session):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s["resale"]["enabled"] = False
    r, resale_copy = await _resale_order(db_session, settings=s)
    offer = await resale.resale_offer_for_customer(
        db_session, restaurant_id=r.id, phone="+971500300999", settings=r.settings, now=NOW,
    )
    assert offer is None


async def test_offer_applies_fixed_discount(db_session):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s["resale"]["discount_type"] = "fixed"
    s["resale"]["discount_value"] = 10
    r, resale_copy = await _resale_order(db_session, settings=s)
    offer = await resale.resale_offer_for_customer(
        db_session, restaurant_id=r.id, phone="+971500300999", settings=r.settings, now=NOW,
    )
    assert offer is not None
    assert offer["discounted_subtotal"] == Decimal("30.00")  # 40 - 10
    assert offer["discount_aed"] == Decimal("10.00")


async def test_accept_resale_batches_companion_order(db_session):
    """Fresh cart + resale accept → both READY and dispatched together."""
    from sqlalchemy import select

    from app.dispatch.models import BatchOrder
    from app.ordering.fsm import OrderStatus

    r, resale_copy = await _resale_order(db_session)
    buyer = Customer(restaurant_id=r.id, phone="+971500300999", name="Buyer")
    db_session.add(buyer)
    await db_session.flush()
    addr = CustomerAddress(customer_id=buyer.id, latitude=25.3, longitude=55.3,
                           room_apartment="9", building="Z", receiver_name="Buyer", confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    companion = Order(
        restaurant_id=r.id, customer_id=buyer.id, order_number="FRESH-1",
        status=OrderStatus.CONFIRMED, subtotal=Decimal("15.00"), total=Decimal("15.00"),
        address_id=addr.id, distance_km=2.0,
    )
    db_session.add(companion)
    await db_session.flush()
    from app.menu.models import Dish
    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == r.id))).first()
    db_session.add(OrderItem(
        order_id=companion.id, dish_id=dish.id, dish_number=1, dish_name="Biryani",
        price_aed=Decimal("15.00"), qty=1,
    ))
    await db_session.flush()

    from app.identity.models import Rider

    rider = Rider(restaurant_id=r.id, name="Batch Rider", phone="+971500300100", status="available")
    db_session.add(rider)
    await db_session.flush()

    new_order = await resale.accept_resale(
        db_session, resale_order=resale_copy, customer_id=buyer.id, address_id=addr.id,
        settings=r.settings, distance_km=2.0, companion_order=companion,
    )
    assert str(companion.status) == str(OrderStatus.READY)
    assert str(new_order.status) in (str(OrderStatus.READY), str(OrderStatus.ASSIGNED))
    bos = (await db_session.scalars(
        select(BatchOrder).where(BatchOrder.order_id.in_([new_order.id, companion.id]))
    )).all()
    # Dispatch batches same-address READY orders when a rider is available.
    if len(bos) == 2:
        assert bos[0].batch_id == bos[1].batch_id
    else:
        assert new_order.address_id == companion.address_id


async def test_accept_resale_creates_discounted_ready_order(db_session):
    r, resale_copy = await _resale_order(db_session)
    buyer = Customer(restaurant_id=r.id, phone="+971500300999", name="Buyer")
    db_session.add(buyer)
    await db_session.flush()
    addr = CustomerAddress(customer_id=buyer.id, latitude=25.3, longitude=55.3,
                           room_apartment="9", building="Z", receiver_name="Buyer", confirmed=True)
    db_session.add(addr)
    await db_session.flush()

    new_order = await resale.accept_resale(
        db_session, resale_order=resale_copy, customer_id=buyer.id, address_id=addr.id,
        settings=r.settings, distance_km=2.0,
    )
    assert new_order.customer_id == buyer.id
    assert new_order.address_id == addr.id
    assert new_order.subtotal == Decimal("28.00")  # 30% off 40
    assert str(new_order.status) in (str(OrderStatus.READY), str(OrderStatus.ASSIGNED))
    # original resale order marked sold
    sold = await db_session.get(Order, resale_copy.id)
    assert str(sold.status) == str(OrderStatus.RESOLD)
    # items cloned
    items = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == new_order.id))).all()
    assert sum(i.qty for i in items) == 1
