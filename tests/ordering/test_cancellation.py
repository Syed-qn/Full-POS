import hashlib
from decimal import Decimal

import pytest

from sqlalchemy import select

from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order
from app.ordering.service import cancel_order


async def _seed_order(db_session, status: str, restaurant_id: int) -> Order:
    customer = Customer(
        restaurant_id=restaurant_id, phone="+971501230098", name="Cancel Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant_id, customer_id=customer.id,
        order_number="R1-CAN1", status=status,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()
    return order


def test_is_excluded_for_resale_helper():
    """AND gate: barred ONLY when phone + door/apartment + building + pin ALL match."""
    from app.ordering.service import _compute_exclusion_hash, is_excluded_for_resale

    h = _compute_exclusion_hash("+971501230099", "101", "Tower A", 25.2048, 55.2708)
    full = dict(phone="+971501230099", room_apartment="101", building="Tower A", lat=25.2048, lon=55.2708)
    assert is_excluded_for_resale(h, **full) is True
    # Case-insensitive on door/building.
    assert is_excluded_for_resale(h, **{**full, "room_apartment": "101", "building": "tower a"}) is True
    # Any single field differing → NOT excluded (AND, not OR).
    assert is_excluded_for_resale(h, **{**full, "phone": "+971500000000"}) is False
    assert is_excluded_for_resale(h, **{**full, "room_apartment": "102"}) is False
    assert is_excluded_for_resale(h, **{**full, "building": "Tower B"}) is False
    assert is_excluded_for_resale(h, **{**full, "lat": 25.30}) is False
    # Missing buyer address (new customer at offer time) → can't AND-match → not excluded.
    assert is_excluded_for_resale(h, phone="+971501230099") is False
    assert is_excluded_for_resale(None, phone="x") is False


async def test_cancel_before_preparing_transitions_to_cancelled(db_session, restaurant):
    order = await _seed_order(db_session, OrderStatus.CONFIRMED, restaurant.id)
    await cancel_order(db_session, order=order, actor="customer", reason="Changed mind")
    await db_session.commit()
    await db_session.refresh(order)
    assert order.status == OrderStatus.CANCELLED
    assert order.cancellation_reason == "Changed mind"


async def test_cancel_during_preparing_creates_resale_copy(db_session, restaurant):
    """Cancellation after cooking started creates an on_resale copy with exclusion hash."""
    order = await _seed_order(db_session, OrderStatus.PREPARING, restaurant.id)
    original_id = order.id

    await cancel_order(db_session, order=order, actor="customer", reason="Duplicate order")
    await db_session.commit()

    orders = (await db_session.execute(select(Order))).scalars().all()
    resale_order = next((o for o in orders if o.resale_of_order_id == original_id), None)

    assert resale_order is not None
    assert resale_order.status == OrderStatus.ON_RESALE
    assert resale_order.exclusion_hash is not None
    await db_session.refresh(order)
    assert order.status == OrderStatus.ON_RESALE


async def test_exclusion_hash_encodes_phone_and_address(db_session, restaurant):
    """Exclusion hash is SHA-256 of phone + receiver + address_id (spec: same phone/person/address blocked)."""
    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501230097", name="Hash Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    from app.ordering.models import CustomerAddress
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="10", building="A", receiver_name="Hash Test", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-HASH1", status=OrderStatus.PREPARING,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id,
    )
    db_session.add(order)
    await db_session.commit()

    await cancel_order(db_session, order=order, actor="customer", reason="Test")
    await db_session.commit()

    resale = (await db_session.execute(
        select(Order).where(Order.resale_of_order_id == order.id)
    )).scalar_one()

    from app.ordering.service import _compute_exclusion_hash
    expected_hash = _compute_exclusion_hash(
        "+971501230097", "10", "A", 25.21, 55.27
    )
    assert resale.exclusion_hash == expected_hash


async def test_resale_offer_matcher_filters_by_exclusion(db_session, restaurant):
    """Matcher filters buyers against exclusion_hash per spec §1 and chat (post-cook cancel exclusion for same phone/person/address)."""
    from decimal import Decimal
    from app.ordering.models import Customer, CustomerAddress, Order
    from app.ordering.service import is_excluded_for_resale, get_available_resale_orders

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501230099", name="Resale Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id,
        room_apartment="Test Apt", building="Test Bldg",
        receiver_name="Resale Test", latitude=25.2048, longitude=55.2708,
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-RESALE", status="preparing",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id,
    )
    db_session.add(order)
    await db_session.flush()

    resale = await cancel_order(db_session, order=order, actor="customer", reason="cooked")
    await db_session.commit()

    # Same buyer — phone + door + building + pin ALL match → excluded (AND gate).
    assert is_excluded_for_resale(
        resale.exclusion_hash, phone="+971501230099",
        room_apartment="Test Apt", building="Test Bldg", lat=25.2048, lon=55.2708,
    )
    # Same phone but DIFFERENT door → allowed (not all four match).
    assert not is_excluded_for_resale(
        resale.exclusion_hash, phone="+971501230099",
        room_apartment="Other Apt", building="Test Bldg", lat=25.2048, lon=55.2708,
    )

    # Matcher: a new buyer (no address at offer time) → can't AND-match → sees the resale.
    available_new = await get_available_resale_orders(
        db_session, restaurant.id, "+971501230100"
    )
    assert any(r.id == resale.id for r in available_new)

    # Matcher with the SAME buyer's full address → excluded (resale not offered to them).
    available_ex = await get_available_resale_orders(
        db_session, restaurant.id, "+971501230099",
        room_apartment="Test Apt", building="Test Bldg", lat=25.2048, lon=55.2708,
    )
    assert not any(r.id == resale.id for r in available_ex)


async def test_customer_cancel_picked_up_blocked(db_session, restaurant):
    """Customers cannot cancel once the rider has the order — restaurant still can."""
    from app.ordering.fsm import IllegalTransitionError

    order = await _seed_order(db_session, OrderStatus.PICKED_UP, restaurant.id)
    with pytest.raises(IllegalTransitionError):
        await cancel_order(db_session, order=order, actor="customer", reason="changed mind")


async def test_manager_cancel_picked_up_allowed(db_session, restaurant):
    order = await _seed_order(db_session, OrderStatus.PICKED_UP, restaurant.id)
    await cancel_order(db_session, order=order, actor="manager", reason="customer unreachable")
    await db_session.refresh(order)
    assert order.status == OrderStatus.CANCELLED


async def test_resale_only_on_customer_cancel_not_restaurant(db_session, restaurant):
    """Resale fires ONLY when the CUSTOMER cancels cooking food. A restaurant/manager
    cancel of a preparing order → plain cancelled, no resale copy."""
    async def _prep_order(phone: str, num: str) -> Order:
        c = Customer(restaurant_id=restaurant.id, phone=phone, name="C",
                     usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"))
        db_session.add(c)
        await db_session.flush()
        o = Order(restaurant_id=restaurant.id, customer_id=c.id, order_number=num,
                  status=OrderStatus.PREPARING, priority="normal", weather_delay_disclosed=False,
                  delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("22.00"), total=Decimal("22.00"))
        db_session.add(o)
        await db_session.commit()
        return o

    # Restaurant cancels a preparing order → cancelled, NO resale.
    o1 = await _prep_order("+971501230081", "R1-MGR")
    r1 = await cancel_order(db_session, order=o1, actor="manager", reason="out of stock")
    await db_session.commit()
    assert r1 is None
    await db_session.refresh(o1)
    assert o1.status == OrderStatus.CANCELLED
    assert await db_session.scalar(
        select(Order).where(Order.resale_of_order_id == o1.id)
    ) is None

    # Customer cancels a preparing order → on_resale + resale copy.
    o2 = await _prep_order("+971501230082", "R1-CUST")
    r2 = await cancel_order(db_session, order=o2, actor="customer", reason="changed mind")
    await db_session.commit()
    assert r2 is not None
    await db_session.refresh(o2)
    assert o2.status == OrderStatus.ON_RESALE
