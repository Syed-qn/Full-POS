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
from app.whatsapp.port import OutboundMessageType


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


async def test_pickup_gates_stop_and_customer_notify_behind_gps(db_session):
    """Flow integrity: at pickup the rider gets ONLY the Start-live-tracker prompt
    (no customer location/details), and the customer gets nothing. The moment the
    rider's GPS goes live (first ping) the rider gets the stop + Delivered button
    and the customer gets the 'on the way' + Track link."""
    from app.dispatch.rider_flow import reveal_first_stop_on_tracking_live
    from app.dispatch.tracking_router import _notify_customers_tracking_live

    r, rider, o, batch, c = await _seed(db_session, status="assigned")

    await handle_orders_picked(db_session, restaurant_id=r.id, rider=rider, batch_id=batch.id)
    await db_session.commit()

    # At pickup: rider got the Start-live-tracker prompt but NOT the stop details.
    rider_msgs = await _cust_msgs(db_session, rider.phone)
    assert any("start live tracker" in (m.payload.get("button_label", "").lower())
               for m in rider_msgs)
    assert not any(m.idempotency_key == f"stop-{o.id}" for m in rider_msgs)
    # And the customer got nothing yet.
    assert await _cust_msgs(db_session, c.phone) == []

    # Rider's live location goes on (first GPS ping) → reveal stop + notify customer.
    await reveal_first_stop_on_tracking_live(db_session, restaurant_id=r.id, rider_id=rider.id)
    await _notify_customers_tracking_live(db_session, rider_id=rider.id)
    await db_session.commit()

    # Rider now has the stop (customer details + Delivered button).
    rider_msgs = await _cust_msgs(db_session, rider.phone)
    stop = next((m for m in rider_msgs if m.idempotency_key == f"stop-{o.id}"), None)
    assert stop is not None
    assert stop.payload["type"] == OutboundMessageType.BUTTONS

    # Customer now gets the 'on the way' + Track CTA button.
    msgs = await _cust_msgs(db_session, c.phone)
    assert len(msgs) == 1
    assert "picked up" in msgs[0].payload["body"].lower()
    assert msgs[0].payload["type"] == OutboundMessageType.CTA_URL
    assert "track my order" in msgs[0].payload["button_label"].lower()
    assert "/track/" in msgs[0].payload["url"]
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
    # (Customer 'on the way' notification is deferred to the first GPS ping now,
    #  so it is intentionally NOT asserted here — this test is about batch advance.)


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


async def test_preparing_notifies_customer(db_session):
    """When the kitchen starts preparing, the customer gets a proactive update."""
    from app.ordering.models import CustomerAddress
    from app.ordering.service import advance_kitchen_status

    r, rider, o, batch, c = await _seed(db_session, status="confirmed")
    addr = CustomerAddress(
        customer_id=c.id, latitude=25.2050, longitude=55.2710, confirmed=True
    )
    db_session.add(addr)
    await db_session.flush()
    o.address_id = addr.id
    await db_session.commit()

    await advance_kitchen_status(db_session, order=o)
    await db_session.commit()

    msgs = await _cust_msgs(db_session, c.phone)
    prep = next(
        (m for m in msgs if m.idempotency_key == f"cust-preparing-{o.id}"), None
    )
    assert prep is not None
    assert "preparing" in prep.payload["body"].lower()


async def test_near_door_notifies_customer_at_50m(db_session):
    """Rider within ~50 m of drop-off → customer gets the around-the-corner ping."""
    from datetime import datetime, timezone

    from app.dispatch.models import RiderLocation
    from app.dispatch.rider_flow import notify_customer_near_door_if_applicable
    from app.ordering.models import CustomerAddress

    r, rider, o, batch, c = await _seed(db_session, status="picked_up")
    drop_lat, drop_lon = 25.2050, 55.2710
    addr = CustomerAddress(
        customer_id=c.id, latitude=drop_lat, longitude=drop_lon, confirmed=True
    )
    db_session.add(addr)
    await db_session.flush()
    o.address_id = addr.id
    # ~44 m north of drop-off (0.0004° lat < 50 m at Dubai latitude).
    db_session.add(
        RiderLocation(
            rider_id=rider.id,
            restaurant_id=r.id,
            latitude=drop_lat + 0.0004,
            longitude=drop_lon,
            ts=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    await notify_customer_near_door_if_applicable(
        db_session, restaurant_id=r.id, rider=rider
    )
    await db_session.commit()

    msgs = await _cust_msgs(db_session, c.phone)
    near = next(
        (m for m in msgs if m.idempotency_key == f"cust-near_door-{o.id}"), None
    )
    assert near is not None
    assert "around the corner" in near.payload["body"].lower()


async def test_near_door_is_idempotent(db_session):
    from datetime import datetime, timezone

    from app.dispatch.models import RiderLocation
    from app.dispatch.rider_flow import notify_customer_near_door_if_applicable
    from app.ordering.models import CustomerAddress

    r, rider, o, batch, c = await _seed(db_session, status="picked_up")
    drop_lat, drop_lon = 25.2050, 55.2710
    addr = CustomerAddress(
        customer_id=c.id, latitude=drop_lat, longitude=drop_lon, confirmed=True
    )
    db_session.add(addr)
    await db_session.flush()
    o.address_id = addr.id
    db_session.add(
        RiderLocation(
            rider_id=rider.id,
            restaurant_id=r.id,
            latitude=drop_lat + 0.0004,
            longitude=drop_lon,
            ts=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    for _ in range(2):
        await notify_customer_near_door_if_applicable(
            db_session, restaurant_id=r.id, rider=rider
        )
        await db_session.commit()

    msgs = [
        m
        for m in await _cust_msgs(db_session, c.phone)
        if m.idempotency_key == f"cust-near_door-{o.id}"
    ]
    assert len(msgs) == 1


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


async def test_status_ping_is_recorded_in_conversation_chat(db_session):
    """A proactive status ping (e.g. 'preparing') must also be recorded as an outbound
    conversation Message so the dashboard chat shows it — not just delivered to WhatsApp.
    Regression: 'The restaurant has started preparing your order.' reached the customer
    but was invisible in the dashboard chat."""
    from app.conversation.models import Conversation, Message

    r, _rider, o, _batch, c = await _seed(db_session, status="preparing")
    await _notify_customer_status(
        db_session, restaurant_id=r.id, order=o, status_key="preparing"
    )
    await db_session.commit()

    # Delivered to WhatsApp (outbox) ...
    outs = await _cust_msgs(db_session, c.phone)
    assert any("preparing" in (m.payload.get("body", "") or "").lower() for m in outs)
    # ... AND mirrored into the conversation chat.
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.phone == c.phone)
    )
    assert conv is not None
    msgs = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id, Message.direction == "outbound")
    )).all()
    assert any("preparing" in (m.payload.get("body", "") or "").lower() for m in msgs)
