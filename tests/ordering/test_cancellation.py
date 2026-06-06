import hashlib
from decimal import Decimal

from sqlalchemy import select

from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order
from app.ordering.service import cancel_order


async def _seed_order(db_session, status: str) -> Order:
    customer = Customer(
        restaurant_id=1, phone="+971501230098", name="Cancel Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-CAN1", status=status,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def test_cancel_before_preparing_transitions_to_cancelled(db_session):
    order = await _seed_order(db_session, OrderStatus.CONFIRMED)
    await cancel_order(db_session, order=order, actor="customer", reason="Changed mind")
    await db_session.commit()
    await db_session.refresh(order)
    assert order.status == OrderStatus.CANCELLED
    assert order.cancellation_reason == "Changed mind"


async def test_cancel_during_preparing_creates_resale_copy(db_session):
    """Cancellation after cooking started creates an on_resale copy with exclusion hash."""
    order = await _seed_order(db_session, OrderStatus.PREPARING)
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


async def test_exclusion_hash_encodes_phone_and_address(db_session):
    """Exclusion hash is SHA-256 of phone + address_id so same customer is blocked from resale."""
    customer = Customer(
        restaurant_id=1, phone="+971501230097", name="Hash Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    from app.ordering.models import CustomerAddress
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="10", building="A", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=1, customer_id=customer.id,
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

    expected_hash = hashlib.sha256(
        f"+971501230097:{addr.id}".encode()
    ).hexdigest()
    assert resale.exclusion_hash == expected_hash
