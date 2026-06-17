"""Proactive customer notifications on delivery progress (rider_flow).

The customer should be told "on the way" when the rider picks up and "delivered"
when the rider completes — without the customer having to ask. Pushes are
idempotent per (order, status).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.dispatch.models import Batch, BatchOrder
from app.dispatch.rider_flow import (
    _notify_customer_status,
    handle_delivered,
    handle_orders_picked,
)
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order
from app.outbox.models import OutboxMessage


async def _seed(db_session, status="assigned"):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id, name="X", phone="+971500000010", status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    c = Customer(
        restaurant_id=r.id, phone="+971501112233", name="C",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    o = Order(
        restaurant_id=r.id, customer_id=c.id, order_number="O1", status=status,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("10.00"), total=Decimal("10.00"),
        rider_id=rider.id, sla_deadline=datetime.now(timezone.utc) + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="planned", route={"stops": []})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=1))
    await db_session.commit()
    return r, rider, o, batch, c


async def _cust_msgs(db_session, phone):
    return (
        await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.to_phone == phone)
        )
    ).all()


async def test_pickup_notifies_customer_on_the_way(db_session):
    r, rider, o, batch, c = await _seed(db_session, status="assigned")

    await handle_orders_picked(db_session, restaurant_id=r.id, rider=rider, batch_id=batch.id)
    await db_session.commit()

    msgs = await _cust_msgs(db_session, c.phone)
    assert len(msgs) == 1
    assert "picked up" in msgs[0].payload["body"].lower()
    assert msgs[0].idempotency_key == f"cust-picked_up-{o.id}"


async def test_delivered_notifies_customer(db_session):
    r, rider, o, batch, c = await _seed(db_session, status="picked_up")

    await handle_delivered(db_session, restaurant_id=r.id, rider=rider, order_id=o.id)
    await db_session.commit()

    msgs = await _cust_msgs(db_session, c.phone)
    keys = {m.idempotency_key for m in msgs}
    assert f"cust-delivered-{o.id}" in keys
    delivered = next(m for m in msgs if m.idempotency_key == f"cust-delivered-{o.id}")
    assert "delivered" in delivered.payload["body"].lower()


async def test_notify_is_idempotent(db_session):
    r, rider, o, batch, c = await _seed(db_session, status="picked_up")

    await _notify_customer_status(db_session, restaurant_id=r.id, order=o, status_key="picked_up")
    await db_session.commit()
    await _notify_customer_status(db_session, restaurant_id=r.id, order=o, status_key="picked_up")
    await db_session.commit()

    msgs = [m for m in await _cust_msgs(db_session, c.phone)
            if m.idempotency_key == f"cust-picked_up-{o.id}"]
    assert len(msgs) == 1  # second call deduped, no duplicate ping
