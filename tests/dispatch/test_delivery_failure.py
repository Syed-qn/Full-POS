"""Failed-delivery reason: reuse the existing FSM `undeliverable` status (spec §3),
just record WHY on the order.

Service level: app.dispatch.delivery.mark_delivery_failed
Router level: POST /api/v1/orders/{order_id}/delivery-failed
"""

from decimal import Decimal

import pytest

from app.dispatch.delivery import mark_delivery_failed
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed(db_session, *, status="arriving"):
    r = Restaurant(name="R", phone="+9710000001", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="X",
        phone="+971500000011",
        status="on_delivery",
    )
    db_session.add(rider)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971501112244", name="C")
    db_session.add(c)
    await db_session.flush()
    o = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number="F1",
        status=status,
        rider_id=rider.id,
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
    )
    db_session.add(o)
    await db_session.commit()
    return r, rider, o


async def test_mark_delivery_failed_sets_reason_and_transitions(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    order = await mark_delivery_failed(
        db_session, restaurant_id=r.id, order_id=o.id, reason="customer unreachable"
    )
    await db_session.commit()
    await db_session.refresh(order)
    assert order.status == "undeliverable"
    assert order.delivery_failure_reason == "customer unreachable"


async def test_mark_delivery_failed_from_picked_up(db_session):
    r, rider, o = await _seed(db_session, status="picked_up")
    order = await mark_delivery_failed(
        db_session, restaurant_id=r.id, order_id=o.id, reason="wrong address"
    )
    await db_session.commit()
    await db_session.refresh(order)
    assert order.status == "undeliverable"
    assert order.delivery_failure_reason == "wrong address"


async def test_mark_delivery_failed_illegal_status_raises(db_session):
    r, rider, o = await _seed(db_session, status="preparing")
    with pytest.raises(ValueError):
        await mark_delivery_failed(
            db_session, restaurant_id=r.id, order_id=o.id, reason="too early"
        )


async def test_mark_delivery_failed_unknown_order_raises(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    with pytest.raises(ValueError):
        await mark_delivery_failed(
            db_session, restaurant_id=r.id, order_id=999999, reason="x"
        )


async def test_mark_delivery_failed_wrong_tenant_raises(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    with pytest.raises(ValueError):
        await mark_delivery_failed(
            db_session, restaurant_id=r.id + 999, order_id=o.id, reason="x"
        )
