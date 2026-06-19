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
    assert "/track/" in msgs[0].payload["body"]
    assert msgs[0].idempotency_key == f"cust-picked_up-{o.id}"


async def test_delivered_notifies_customer(db_session):
    from datetime import datetime, timezone

    from app.dispatch.models import RiderLocation

    r, rider, o, batch, c = await _seed(db_session, status="picked_up")

    # Tracker must be live (recent GPS ping) before a stop can be delivered.
    db_session.add(RiderLocation(
        rider_id=rider.id, restaurant_id=r.id, latitude=25.1, longitude=55.2,
        ts=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    await handle_delivered(db_session, restaurant_id=r.id, rider=rider, order_id=o.id)
    await db_session.commit()

    msgs = await _cust_msgs(db_session, c.phone)
    keys = {m.idempotency_key for m in msgs}
    assert f"cust-delivered-{o.id}" in keys
    delivered = next(m for m in msgs if m.idempotency_key == f"cust-delivered-{o.id}")
    assert "delivered" in delivered.payload["body"].lower()


async def test_picked_falls_back_to_current_batch_on_stale_id(db_session):
    """A stale/None batch_id (reassigned batch, test send) must still advance the
    rider's CURRENT planned batch — not silently do nothing."""
    r, rider, o, batch, c = await _seed(db_session, status="assigned")

    # batch_id=None simulates a malformed/stale payload (e.g. "picked:test").
    await handle_orders_picked(db_session, restaurant_id=r.id, rider=rider,
                               batch_id=None, trigger_msg_id="wamid.x")
    await db_session.commit()

    await db_session.refresh(o)
    assert o.status == "picked_up"  # fell back to the current planned batch
    msgs = await _cust_msgs(db_session, c.phone)
    assert any("picked up" in m.payload["body"].lower() for m in msgs)


async def test_picked_resends_current_stop_when_already_in_progress(db_session):
    """If the rider already picked up (batch in progress) and re-taps Orders
    Picked — e.g. the first stop message was lost — re-send the current stop
    rather than telling them there's nothing to do."""
    r, rider, o, batch, c = await _seed(db_session, status="picked_up")
    batch.status = "picked_up"  # in-progress, no longer 'planned'
    await db_session.commit()

    await handle_orders_picked(db_session, restaurant_id=r.id, rider=rider,
                               batch_id=None, trigger_msg_id="wamid.resend1")
    await db_session.commit()

    rider_msgs = await _cust_msgs(db_session, rider.phone)
    assert any("next stop" in m.payload["body"].lower() for m in rider_msgs)


async def test_picked_with_no_batch_tells_rider(db_session):
    """Tapping with no active batch replies instead of a silent no-op."""
    r = await _restaurant(db_session)
    rider = await _rider(db_session, r)
    await db_session.commit()

    await handle_orders_picked(db_session, restaurant_id=r.id, rider=rider,
                               batch_id=999, trigger_msg_id="wamid.y")
    await db_session.commit()

    rider_msgs = await _cust_msgs(db_session, rider.phone)
    assert any("no active batch" in m.payload["body"].lower() for m in rider_msgs)


async def _restaurant(db_session):
    from app.identity.models import Restaurant
    r = Restaurant(name="R", phone="+9710000099", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    return r


async def _rider(db_session, r):
    rider = Rider(restaurant_id=r.id, name="X", phone="+971500000099",
                  status="available", performance={})
    db_session.add(rider)
    await db_session.flush()
    return rider


async def test_notify_is_idempotent(db_session):
    r, rider, o, batch, c = await _seed(db_session, status="picked_up")

    await _notify_customer_status(db_session, restaurant_id=r.id, order=o, status_key="picked_up")
    await db_session.commit()
    await _notify_customer_status(db_session, restaurant_id=r.id, order=o, status_key="picked_up")
    await db_session.commit()

    msgs = [m for m in await _cust_msgs(db_session, c.phone)
            if m.idempotency_key == f"cust-picked_up-{o.id}"]
    assert len(msgs) == 1  # second call deduped, no duplicate ping


async def test_delivered_blocked_until_tracker_started(db_session):
    """Rider can't mark a stop delivered until live tracking is on. Without a
    recent GPS ping, handle_delivered must NOT advance and must re-send the
    Start-live-tracker button."""
    r, rider, o, batch, c = await _seed(db_session, status="picked_up")

    await handle_delivered(db_session, restaurant_id=r.id, rider=rider, order_id=o.id,
                           trigger_msg_id="wamid.try1")
    await db_session.commit()

    await db_session.refresh(o)
    assert o.status == "picked_up"  # NOT advanced to delivered
    # customer was NOT told delivered
    cust = await _cust_msgs(db_session, c.phone)
    assert not any(m.idempotency_key == f"cust-delivered-{o.id}" for m in cust)
    # rider got the Start-live-tracker button re-prompt
    rider_msgs = await _cust_msgs(db_session, rider.phone)
    assert any("start live tracker" in (m.payload.get("button_label", "").lower())
               for m in rider_msgs)
