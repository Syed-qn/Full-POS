"""Rider button flow (spec §4.4.3-4.4.4): Orders Picked / Delivered drive the FSM.

Schema note: orders carry no ``dropoff_lat/lon`` columns; the next-stop nav uses
the order's drop-off via CustomerAddress (seeded here), falling back gracefully.
"""

from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.cod.models import CodCollection
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


async def _seed_batch(db_session, n_orders=2):
    r = Restaurant(name="R", phone="+9714445555", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="Rider",
        phone="+971509990001",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="planned", route={"stops": []})
    db_session.add(batch)
    await db_session.flush()
    orders = []
    for i in range(n_orders):
        c = Customer(
            restaurant_id=r.id,
            phone=f"+97150111000{i}",
            name=f"C{i}",
            usual_order_times={},
            tags={},
            total_orders=0,
            total_spend=Decimal("0.00"),
        )
        db_session.add(c)
        await db_session.flush()
        addr = CustomerAddress(
            customer_id=c.id, latitude=25.21, longitude=55.27, confirmed=True
        )
        db_session.add(addr)
        await db_session.flush()
        o = Order(
            restaurant_id=r.id,
            customer_id=c.id,
            order_number=f"O{i}",
            status="assigned",
            priority="normal",
            weather_delay_disclosed=False,
            delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("20.00"),
            total=Decimal("20.00"),
            rider_id=rider.id,
            address_id=addr.id,
        )
        db_session.add(o)
        await db_session.flush()
        db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=i + 1))
        orders.append(o)
    await db_session.commit()
    return r, rider, batch, orders


async def test_orders_picked_advances_all_and_sends_first_stop(db_session):
    r, rider, batch, orders = await _seed_batch(db_session)
    inbound = InboundMessage(
        wa_message_id="b-1",
        from_phone=rider.phone,
        type=MessageType.BUTTON_REPLY,
        payload={"button_id": f"picked:{batch.id}"},
        restaurant_phone=r.phone,
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(batch)
    assert batch.status == "picked_up"
    for o in orders:
        await db_session.refresh(o)
        assert o.status == "picked_up"
    msg = await db_session.scalar(
        select(OutboxMessage)
        .where(OutboxMessage.to_phone == rider.phone)
        .order_by(OutboxMessage.id.desc())
    )
    assert msg is not None  # first-stop nav sent

    # A live-location request is sent on pickup (so the dashboard can track them).
    live = await db_session.scalar(
        select(OutboxMessage).where(
            OutboxMessage.to_phone == rider.phone,
            OutboxMessage.idempotency_key == f"livereq-{batch.id}",
        )
    )
    assert live is not None
    assert "live location" in live.payload["body"].lower()


async def test_delivered_marks_delivered_and_records_cod(db_session):
    r, rider, batch, orders = await _seed_batch(db_session, n_orders=1)
    o = orders[0]
    o.status = "picked_up"
    batch.status = "picked_up"
    await db_session.commit()
    inbound = InboundMessage(
        wa_message_id="d-1",
        from_phone=rider.phone,
        type=MessageType.BUTTON_REPLY,
        payload={"button_id": f"delivered:{o.id}"},
        restaurant_phone=r.phone,
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "delivered"
    cod = await db_session.scalar(
        select(CodCollection).where(CodCollection.order_id == o.id)
    )
    assert cod is not None
    assert cod.amount_aed == Decimal("20.00")


async def test_last_delivery_frees_rider(db_session):
    r, rider, batch, orders = await _seed_batch(db_session, n_orders=1)
    o = orders[0]
    o.status = "picked_up"
    batch.status = "picked_up"
    await db_session.commit()
    inbound = InboundMessage(
        wa_message_id="d-2",
        from_phone=rider.phone,
        type=MessageType.BUTTON_REPLY,
        payload={"button_id": f"delivered:{o.id}"},
        restaurant_phone=r.phone,
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(rider)
    assert rider.status == "available"


async def test_button_only_unknown_id_no_op(db_session):
    """Flow integrity: a non-button text does not advance the batch."""
    r, rider, batch, orders = await _seed_batch(db_session, n_orders=1)
    inbound = InboundMessage(
        wa_message_id="t-1",
        from_phone=rider.phone,
        type=MessageType.TEXT,
        payload={"text": "delivered"},
        restaurant_phone=r.phone,
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(orders[0])
    assert orders[0].status == "assigned"  # unchanged — buttons only


async def test_100m_geofence_sends_dual_buttons_and_delivered_next_reveals_next_location(db_session):
    """Spec §4.4 + transcript: at ~100 m from stop → dual buttons "Delivered" | "Delivered and Next Order Location".
    Button click is the ONLY way to get next location (forces flow integrity). "delivered_next" marks + immediately sends next stop nav.
    Power bank provided per ops policy (note in code). Riders see customer contact in msg body; no raw phone leaked to customer side.
    """
    r, rider, batch, orders = await _seed_batch(db_session, n_orders=2)
    o1, o2 = orders
    # make o1 picked so stop sent; set rider loc very close to o1 dropoff (~50m < 0.1km)
    o1.status = "picked_up"
    batch.status = "picked_up"
    await db_session.commit()
    # first stop already sent in real flow on picked; here simulate location ping near o1 to trigger geofence dual
    inbound_loc = InboundMessage(
        wa_message_id="loc-near-1",
        from_phone=rider.phone,
        type=MessageType.LOCATION,
        payload={"latitude": 25.21005, "longitude": 55.27005},  # near 25.21,55.27
        restaurant_phone=r.phone,
        timestamp=0,
    )
    await handle_inbound(db_session, inbound_loc, restaurant_id=r.id)
    await db_session.commit()
    # assert choice buttons sent (dual instead of single)
    msg = await db_session.scalar(
        select(OutboxMessage)
        .where(OutboxMessage.to_phone == rider.phone)
        .order_by(OutboxMessage.id.desc())
    )
    assert msg is not None
    payload = msg.payload or {}
    assert "buttons" in payload
    titles = [b.get("title", "") for b in payload.get("buttons", [])]
    # WhatsApp caps reply-button titles at 20 chars, so titles are shortened.
    assert all(len(t) <= 20 for t in titles)
    assert any("Delivered" in t or "Collect" in t for t in titles)
    assert "Delivered & next" in titles
    body = payload.get("body", "")
    assert "Near" in body or "stop" in body.lower()
    # customer details in body for rider (safe check; seed uses customer_id)
    assert "Name:" in body or "stop" in body.lower()

    # click delivered_next for o1 -> delivered + immediate next stop for o2
    inbound_next = InboundMessage(
        wa_message_id="dn-1",
        from_phone=rider.phone,
        type=MessageType.BUTTON_REPLY,
        payload={"button_id": f"delivered_next:{o1.id}"},
        restaurant_phone=r.phone,
        timestamp=0,
    )
    await handle_inbound(db_session, inbound_next, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o1)
    assert o1.status == "delivered"
    # next stop msg for o2 sent immediately
    msg2 = await db_session.scalar(
        select(OutboxMessage)
        .where(OutboxMessage.to_phone == rider.phone)
        .order_by(OutboxMessage.id.desc())
    )
    assert msg2 is not None
    assert f"Next stop — Order {o2.order_number}" in (msg2.payload or {}).get("body", "")
