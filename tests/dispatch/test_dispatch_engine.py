"""Dispatch engine integration tests (spec §4.3).

Schema adaptation (per Phase-3 T2 flags — NO new migration):
  * Restaurant pickup coords are ``lat``/``lng`` (not location_lat/lon).
  * Order drop-off is resolved via ``address_id`` -> CustomerAddress.latitude/
    longitude (there are no Order.dropoff_lat/lon columns).
  * Rider position lives in the ``rider_locations`` table (no Rider.last_lat/lon);
    a rider with no ping is treated as co-located with the restaurant (distance 0).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation
from app.dispatch.service import run_dispatch_engine
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order
from app.outbox.models import OutboxMessage
from app.whatsapp.port import OutboundMessageType


async def _seed_restaurant(db_session, lat=25.2048, lng=55.2708):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x", lat=lat, lng=lng)
    db_session.add(r)
    await db_session.flush()
    return r


async def _ready_order(db_session, restaurant_id, lat, lon, num, minutes_since_sla: int = 5):
    """Seed ready order; now supports minutes_since_sla for realistic sla_confirmed_at (used in GAP#4 inter-stop elapsed + route_time tests)."""
    c = Customer(
        restaurant_id=restaurant_id,
        phone=f"+97150{num:07d}",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=c.id, latitude=lat, longitude=lon, confirmed=True
    )
    db_session.add(addr)
    await db_session.flush()
    sla_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_since_sla)
    o = Order(
        restaurant_id=restaurant_id,
        customer_id=c.id,
        order_number=f"O{num}",
        status="ready",
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        address_id=addr.id,
        sla_confirmed_at=sla_at,
        sla_deadline=sla_at + timedelta(minutes=40),
        promised_eta=sla_at + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def _ping(db_session, rider, restaurant_id, lat, lon):
    db_session.add(
        RiderLocation(
            rider_id=rider.id,
            restaurant_id=restaurant_id,
            latitude=lat,
            longitude=lon,
            ts=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()


async def test_assigns_nearest_available_rider(db_session):
    r = await _seed_restaurant(db_session)
    near = Rider(
        restaurant_id=r.id,
        name="Near",
        phone="+971500000001",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    far = Rider(
        restaurant_id=r.id,
        name="Far",
        phone="+971500000002",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add_all([near, far])
    await db_session.flush()
    await _ping(db_session, near, r.id, 25.2048, 55.2708)
    await _ping(db_session, far, r.id, 25.3500, 55.4500)
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 1)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "assigned"
    assert order.rider_id == near.id
    assert result.assigned_count == 1
    assignment = await db_session.scalar(
        select(Assignment).where(Assignment.order_id == order.id)
    )
    assert assignment.rider_id == near.id
    assert "composite" in assignment.algorithm_score


async def test_dispatch_survives_missing_rider_locations(db_session, monkeypatch):
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id,
        name="Fallback",
        phone="+971500000111",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 111)
    await db_session.commit()

    from app.dispatch import service as dispatch_service

    async def _no_positions(session, restaurant_id):
        return {}

    monkeypatch.setattr(dispatch_service, "_latest_rider_positions", _no_positions)

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    await db_session.refresh(rider)
    assert result.assigned_count == 1
    assert order.status == "assigned"
    assert order.rider_id == rider.id
    assert rider.status == "on_delivery"


async def test_assignment_default_is_freeform_button(db_session):
    """With no template configured, the rider notification stays a free-form
    interactive button (unchanged dev/test/mock behaviour)."""
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="Rdr", phone="+971500000009",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2050, 55.2710)
    await _ready_order(db_session, r.id, 25.2050, 55.2710, 9)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    msg = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == rider.phone)
    )
    assert msg is not None
    assert msg.payload["type"] == str(OutboundMessageType.BUTTONS)
    assert msg.payload["buttons"][0]["id"].startswith("picked:")
    assert msg.payload["buttons"][0]["title"] == "Orders Picked"


async def test_assignment_uses_template_when_configured(db_session, monkeypatch):
    """When wa_rider_assign_template is set, the assignment is sent as a TEMPLATE
    (delivers outside the 24h window) with the order numbers as body param and
    picked:{batch_id} as the quick-reply button payload."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "wa_rider_assign_template", "rider_assignment")
    monkeypatch.setattr(settings, "wa_rider_assign_template_lang", "en")

    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="Rdr", phone="+971500000010",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2050, 55.2710)
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 10)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    msg = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == rider.phone)
    )
    assert msg is not None
    assert msg.payload["type"] == str(OutboundMessageType.TEMPLATE)
    assert msg.payload["name"] == "rider_assignment"
    assert msg.payload["language"] == "en"
    comps = msg.payload["components"]
    body = next(c for c in comps if c["type"] == "body")
    assert body["parameters"][0]["text"] == order.order_number
    btn = next(c for c in comps if c["type"] == "button")
    assert btn["sub_type"] == "quick_reply"
    batch = await db_session.scalar(select(Batch).where(Batch.rider_id == rider.id))
    assert btn["parameters"][0]["payload"] == f"picked:{batch.id}"


async def test_reassign_moves_order_and_frees_old_rider(db_session):
    """Manual reassign: order moves to the chosen rider in a fresh batch, the old
    rider is freed (no other live orders), the new rider goes on_delivery, and the
    new rider is notified."""
    from app.dispatch.service import reassign_order

    r = await _seed_restaurant(db_session)
    rider_a = Rider(
        restaurant_id=r.id, name="A", phone="+971500000021", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider_a)
    await db_session.flush()
    await _ping(db_session, rider_a, r.id, 25.2050, 55.2710)
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 21)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(order)
    assert order.rider_id == rider_a.id  # auto-assigned to the only rider

    # Manager picks a different rider.
    rider_b = Rider(
        restaurant_id=r.id, name="B", phone="+971500000022", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider_b)
    await db_session.flush()
    old_batch = await db_session.scalar(select(Batch).where(Batch.rider_id == rider_a.id))

    await reassign_order(
        db_session, restaurant_id=r.id, order_id=order.id, new_rider_id=rider_b.id
    )
    await db_session.commit()

    await db_session.refresh(order)
    await db_session.refresh(rider_a)
    await db_session.refresh(rider_b)
    assert order.rider_id == rider_b.id
    assert order.status == "assigned"
    assert rider_a.status == "available"   # freed
    assert rider_b.status == "on_delivery"

    # New single-order batch for B carries the order.
    new_batch = await db_session.scalar(select(Batch).where(Batch.rider_id == rider_b.id))
    assert new_batch is not None and new_batch.id != old_batch.id
    bo = await db_session.scalar(select(BatchOrder).where(BatchOrder.order_id == order.id))
    assert bo.batch_id == new_batch.id

    # New rider notified.
    msg = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == rider_b.phone)
    )
    assert msg is not None


async def test_reassign_rejects_non_assigned_order(db_session):
    from app.dispatch.service import reassign_order

    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="A", phone="+971500000031", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider)
    await db_session.flush()
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 31)  # status "ready"
    await db_session.commit()

    import pytest
    with pytest.raises(ValueError, match="Only assigned orders"):
        await reassign_order(
            db_session, restaurant_id=r.id, order_id=order.id, new_rider_id=rider.id
        )


async def test_reassign_to_same_rider_rejected(db_session):
    from app.dispatch.service import reassign_order

    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="A", phone="+971500000041", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2050, 55.2710)
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 41)
    await db_session.commit()
    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    import pytest
    with pytest.raises(ValueError, match="already assigned to this rider"):
        await reassign_order(
            db_session, restaurant_id=r.id, order_id=order.id, new_rider_id=rider.id
        )


async def test_no_available_riders_alerts_manager_and_leaves_unassigned(db_session):
    r = await _seed_restaurant(db_session)
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 2)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "ready"  # unchanged
    assert order.rider_id is None
    assert result.unassigned_count == 1
    assert result.needs_retry is True
    alert = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == r.phone)
    )
    assert alert is not None  # manager alerted


async def test_rider_set_on_delivery_and_batch_created(db_session):
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id,
        name="X",
        phone="+971500000003",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    await _ready_order(db_session, r.id, 25.2050, 55.2710, 3)
    await _ready_order(db_session, r.id, 25.2051, 55.2711, 4)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(rider)
    assert rider.status == "on_delivery"
    batch = await db_session.scalar(select(Batch).where(Batch.rider_id == rider.id))
    assert batch is not None
    bos = (
        await db_session.scalars(
            select(BatchOrder).where(BatchOrder.batch_id == batch.id)
        )
    ).all()
    assert len(bos) == 2  # both nearby orders batched to one rider


async def test_inter_stop_travel_gap_splits_batch_and_sets_total_est_min(db_session):
    """GAP_LIST #4 + spec §4.3: inter-stop travel (via geo port/haversine in sequenced stops) + (now-sla_elapsed) + 10min/order buf must respect <=30 internal target.

    Uses real sla_confirmed_at (populated in service candidates), ~0.78km inter-stop (~1.9min @25kmh city), elapsed~19min so 19+1.9+10~30.9>30 -> split to fresh batches even within proximity 1km + window.
    2 riders available so both batches assign. Verifies total_est_min set on Batch (from compute using geo inter-stop sum).
    Also exercises priority single protection if threatens (existing + new logic).
    40min customer respected implicitly via 30+buf design.
    """
    r = await _seed_restaurant(db_session)
    rider1 = Rider(
        restaurant_id=r.id,
        name="R1",
        phone="+971500000011",
        status="available",
        performance={"on_time_pct": 100.0},
    )
    rider2 = Rider(
        restaurant_id=r.id,
        name="R2",
        phone="+971500000012",
        status="available",
        performance={"on_time_pct": 100.0},
    )
    db_session.add_all([rider1, rider2])
    await db_session.flush()
    await _ping(db_session, rider1, r.id, 25.2048, 55.2708)
    await _ping(db_session, rider2, r.id, 25.2048, 55.2708)

    # spaced ~0.78km (within default 1.0km prox to seed), high elapsed for gap
    await _ready_order(db_session, r.id, 25.2048, 55.2708, 101, minutes_since_sla=19)
    await _ready_order(
        db_session, r.id, 25.2048 + 0.0075, 55.2708 + 0.0005, 102, minutes_since_sla=19
    )
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    # 2 batches assigned thanks to 2 riders + split
    assert result.assigned_count == 2
    assert result.unassigned_count == 0

    batches = (await db_session.scalars(select(Batch))).all()
    assert len(batches) == 2, "inter-stop travel gap must cause split to fresh batch (not fit <~30 internal)"
    for b in batches:
        assert b.total_est_min is not None
        assert b.total_est_min > 0, "total_est_min must be set on batch per GAP#4/spec"
        # est should be at least the elapsed + small for this case ~20+
        assert b.total_est_min >= 19

    bos = (await db_session.scalars(select(BatchOrder))).all()
    assert len(bos) == 2
    # confirm not batched together (would be 1 batch 2 bos if no gap fix)



async def test_advance_to_ready_auto_assigns_rider(db_session):
    """Marking an order READY auto-dispatches a rider — no manual /dispatch/trigger
    and no Celery beat (the assignment happens in the kitchen-advance request)."""
    from app.ordering.service import advance_kitchen_status

    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="X", phone="+971500000099", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)

    c = Customer(
        restaurant_id=r.id, phone="+971509999999", name="C",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=25.2050, longitude=55.2710, confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    o = Order(
        restaurant_id=r.id, customer_id=c.id, order_number="OA1", status="preparing",
        priority="normal", weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"), total=Decimal("10.00"), address_id=addr.id,
        sla_confirmed_at=now, sla_deadline=now + timedelta(minutes=40),
        promised_eta=now + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.commit()

    # preparing -> ready triggers auto-dispatch in the same call
    await advance_kitchen_status(db_session, order=o)

    await db_session.refresh(o)
    await db_session.refresh(rider)
    assert o.status == "assigned"
    assert o.rider_id == rider.id
    assert rider.status == "on_delivery"
