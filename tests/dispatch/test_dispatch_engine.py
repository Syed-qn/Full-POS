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

from sqlalchemy import func, select

from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation
from app.dispatch.service import run_dispatch_engine
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order
from app.outbox.models import OutboxMessage


async def _seed_restaurant(db_session, lat=25.2048, lng=55.2708, dispatch_engine="greedy"):
    r = Restaurant(
        name="R", phone="+9710000000", password_hash="x", lat=lat, lng=lng,
        settings={"dispatch_engine": dispatch_engine},
    )
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


async def test_off_duty_rider_is_not_assigned(db_session):
    """A rider who flipped the in-app switch OFF (on_duty=False) is excluded from
    dispatch even though their operational status is still 'available'."""
    r = await _seed_restaurant(db_session)
    off = Rider(
        restaurant_id=r.id,
        name="Off",
        phone="+971500000201",
        status="available",
        on_duty=False,
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(off)
    await db_session.flush()
    await _ping(db_session, off, r.id, 25.2048, 55.2708)
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 201)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "ready"
    assert order.rider_id is None
    assert result.assigned_count == 0
    assert result.needs_retry is True


async def test_on_duty_rider_assigned_over_off_duty(db_session):
    """When one rider is off duty and one is on duty, only the on-duty rider gets it."""
    r = await _seed_restaurant(db_session)
    off = Rider(
        restaurant_id=r.id, name="Off", phone="+971500000202",
        status="available", on_duty=False,
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    on = Rider(
        restaurant_id=r.id, name="On", phone="+971500000203",
        status="available", on_duty=True,
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add_all([off, on])
    await db_session.flush()
    # Put the OFF rider closer so distance can't explain the choice — duty does.
    await _ping(db_session, off, r.id, 25.2048, 55.2708)
    await _ping(db_session, on, r.id, 25.3500, 55.4500)
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 202)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert result.assigned_count == 1
    assert order.rider_id == on.id


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


async def test_assignment_notifies_rider_by_push_not_whatsapp(db_session):
    """App-only rider flow: a new assignment wakes the rider by PUSH, and NO
    WhatsApp message is ever sent to the rider."""
    from app.notifications.factory import get_fake_push_provider

    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="Rdr", phone="+971500000009",
        status="available", push_token="ExponentPushToken[xyz]",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2050, 55.2710)
    await _ready_order(db_session, r.id, 25.2050, 55.2710, 9)
    await db_session.commit()

    fake = get_fake_push_provider()
    fake.sent.clear()
    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    # No WhatsApp to the rider — ever.
    msg = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == rider.phone)
    )
    assert msg is None
    # A push was sent instead.
    assert any(m.to_token == "ExponentPushToken[xyz]" for m in fake.sent)


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
    from app.notifications.factory import get_fake_push_provider

    rider_b = Rider(
        restaurant_id=r.id, name="B", phone="+971500000022", status="available",
        push_token="ExponentPushToken[b]",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider_b)
    await db_session.flush()
    old_batch = await db_session.scalar(select(Batch).where(Batch.rider_id == rider_a.id))

    fake = get_fake_push_provider()
    fake.sent.clear()
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

    # New rider notified by PUSH (never WhatsApp).
    assert any(m.to_token == "ExponentPushToken[b]" for m in fake.sent)
    whatsapp_to_b = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == rider_b.phone)
    )
    assert whatsapp_to_b is None


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


async def test_ungeocoded_order_skipped_not_faked_to_restaurant(db_session):
    """GAP#7: an order with no geocoded drop-off must be skipped (left ready) and the
    manager alerted — NOT faked to the restaurant location (which masks distance as 0
    and produces a silent SLA breach on the road)."""
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id,
        name="X",
        phone="+971500000009",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    # Order with NO address -> no drop-off coords.
    c = Customer(
        restaurant_id=r.id, phone="+971509999999", name="NoGeo", usual_order_times={},
        tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=r.id, customer_id=c.id, order_number="ONOGEO", status="ready",
        priority="normal", weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"), total=Decimal("10.00"), address_id=None,
        sla_confirmed_at=now, sla_deadline=now + timedelta(minutes=40),
        promised_eta=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "ready"  # left unassigned, not dispatched
    assert order.rider_id is None
    # Not batched
    assert await db_session.scalar(select(Batch).where(Batch.rider_id == rider.id)) is None
    # Manager alerted about the missing delivery location
    alert = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == r.phone)
    )
    assert alert is not None
    assert "ONOGEO" in str(alert.payload)


async def test_unassigned_order_past_sla_projection_warns_manager(db_session):
    """Predictive breach warning: when an order can't be assigned (no riders) AND its
    projected completion already blows the 40-min customer SLA, the manager is warned
    NOW (at dispatch) rather than only when the 40-min timer trips. Reuses the depot-leg
    projection (GAP#1) — order 38 min elapsed + ~km drive -> projected > 40."""
    r = await _seed_restaurant(db_session)  # restaurant at 25.2048,55.2708
    # No riders available.
    # Drop-off ~3km away so depot leg adds several minutes on top of 38 elapsed.
    order = await _ready_order(
        db_session, r.id, 25.2300, 55.2900, 7, minutes_since_sla=38
    )
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "ready"
    assert result.needs_retry is True
    msgs = (
        await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.to_phone == r.phone)
        )
    ).all()
    bodies = " ".join(str(m.payload) for m in msgs)
    # A distinct breach-prediction alert naming the order, not just the generic retry note.
    assert "O7" in bodies
    assert "40" in bodies and ("can't" in bodies.lower() or "cannot" in bodies.lower())


async def test_unassigned_order_within_sla_no_breach_warning(db_session):
    """Counterpart: an unassigned order that CAN still make 40 min gets only the normal
    'waiting, will retry' note — no false breach alarm."""
    r = await _seed_restaurant(db_session)
    order = await _ready_order(
        db_session, r.id, 25.2050, 55.2710, 8, minutes_since_sla=2
    )
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "ready"
    msgs = (
        await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.to_phone == r.phone)
        )
    ).all()
    bodies = " ".join(str(m.payload) for m in msgs).lower()
    assert "cannot" not in bodies and "can't" not in bodies


async def test_ortools_engine_assigns_and_tags_score(db_session):
    """With the per-restaurant flag set to 'ortools', dispatch runs the VRP optimizer,
    assigns orders, and tags the assignment score with engine=ortools."""
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id, name="X", phone="+971500000044", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    o1 = await _ready_order(db_session, r.id, 25.2050, 55.2710, 41)
    o2 = await _ready_order(db_session, r.id, 25.2055, 55.2715, 42)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(o1)
    await db_session.refresh(o2)
    assert o1.status == "assigned" and o2.status == "assigned"
    assert result.assigned_count == 2
    a = await db_session.scalar(select(Assignment).where(Assignment.order_id == o1.id))
    assert a.algorithm_score.get("engine") == "ortools"


async def test_ortools_engine_drops_impossible_and_warns(db_session):
    """OR-Tools engine: an order already past SLA is dropped (left ready) and the
    manager is warned; a feasible order in the same run is still assigned."""
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id, name="X", phone="+971500000045", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    good = await _ready_order(db_session, r.id, 25.2050, 55.2710, 43, minutes_since_sla=2)
    late = await _ready_order(db_session, r.id, 25.2300, 55.3200, 44, minutes_since_sla=50)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(good)
    await db_session.refresh(late)
    assert good.status == "assigned"
    assert late.status == "ready"  # dropped, not faked into a doomed route
    alert = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == r.phone)
    )
    assert alert is not None and "O44" in str(alert.payload)


async def test_ortools_busy_rider_absorbs_new_nearby_order(db_session):
    """Phase 3b: a new ready order is added to an in-flight rider's route (their already-
    assigned order participates as locked context) when no free rider is available —
    instead of sitting unassigned. Re-running is idempotent (no duplicate batch rows)."""
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id, name="X", phone="+971500000046", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    o1 = await _ready_order(db_session, r.id, 25.2050, 55.2710, 46, minutes_since_sla=2)
    await db_session.commit()

    # First run assigns o1 to the only rider (rider -> on_delivery).
    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o1)
    await db_session.refresh(rider)
    assert o1.status == "assigned" and rider.status == "on_delivery"

    # A new nearby order arrives; the rider is busy (no free rider).
    o2 = await _ready_order(db_session, r.id, 25.2052, 55.2712, 47, minutes_since_sla=1)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(o1)
    await db_session.refresh(o2)
    # New order absorbed by the in-flight rider; original still on that rider.
    assert o2.status == "assigned" and o2.rider_id == rider.id
    assert o1.rider_id == rider.id
    # Idempotent: each order maps to exactly one BatchOrder (unique constraint holds).
    for oid in (o1.id, o2.id):
        cnt = await db_session.scalar(
            select(func.count(BatchOrder.id)).where(BatchOrder.order_id == oid)
        )
        assert cnt == 1


async def test_ortools_reopt_unchanged_route_is_noop(db_session):
    """Re-running dispatch with no new orders does not churn an already-optimal route."""
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    rider = Rider(
        restaurant_id=r.id, name="X", phone="+971500000048", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    o1 = await _ready_order(db_session, r.id, 25.2050, 55.2710, 49, minutes_since_sla=2)
    await db_session.commit()
    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    batch_count_1 = await db_session.scalar(select(func.count(Batch.id)))

    # No new orders -> second run is a no-op (no new batch, no error).
    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    batch_count_2 = await db_session.scalar(select(func.count(Batch.id)))
    assert batch_count_2 == batch_count_1
    assert result.assigned_count == 0


async def test_dispatch_metrics_increment(db_session):
    """Greedy dispatch bumps the engine run + assigned-order counters (observability)."""
    from app.metrics import DISPATCH_ORDERS, DISPATCH_RUNS

    runs_before = DISPATCH_RUNS.labels(engine="greedy")._value.get()
    assigned_before = DISPATCH_ORDERS.labels(engine="greedy", outcome="assigned")._value.get()

    r = await _seed_restaurant(db_session)  # greedy
    rider = Rider(
        restaurant_id=r.id, name="X", phone="+971500000050", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    await _ready_order(db_session, r.id, 25.2050, 55.2710, 51)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    assert DISPATCH_RUNS.labels(engine="greedy")._value.get() == runs_before + 1
    assert (
        DISPATCH_ORDERS.labels(engine="greedy", outcome="assigned")._value.get()
        == assigned_before + 1
    )


async def test_shadow_compare_logs_when_enabled(db_session, caplog):
    """With dispatch_shadow_compare on, a greedy run also logs the ortools plan it would
    have produced (no writes)."""
    import logging as _logging

    from app.config import get_settings

    settings = get_settings()
    settings.dispatch_shadow_compare = True
    try:
        r = await _seed_restaurant(db_session)  # greedy
        rider = Rider(
            restaurant_id=r.id, name="X", phone="+971500000052", status="available",
            performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
        )
        db_session.add(rider)
        await db_session.flush()
        await _ping(db_session, rider, r.id, 25.2048, 55.2708)
        await _ready_order(db_session, r.id, 25.2050, 55.2710, 53)
        await db_session.commit()

        with caplog.at_level(_logging.INFO, logger="app.dispatch.service"):
            await run_dispatch_engine(db_session, restaurant_id=r.id)
            await db_session.commit()
        assert any("shadow-compare" in rec.getMessage() for rec in caplog.records)
    finally:
        settings.dispatch_shadow_compare = False


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



async def test_multistop_batch_persists_nearest_first_sequence(db_session):
    """A batch's stops are delivered nearest-first from the restaurant, even when the
    farther order arrived (seeded) first — not in arrival order."""
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="R", phone="+971500000021", status="available",
        performance={"on_time_pct": 100.0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    # 'far' is added first -> seeds the batch; 'near' is closer to the restaurant.
    # Both north of the restaurant and within 1 km of each other -> one batch.
    far = await _ready_order(db_session, r.id, 25.2048 + 0.0054, 55.2708, 201)   # ~0.6 km
    near = await _ready_order(db_session, r.id, 25.2048 + 0.0018, 55.2708, 202)  # ~0.2 km
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    batch = await db_session.scalar(select(Batch).where(Batch.rider_id == rider.id))
    bos = (
        await db_session.scalars(
            select(BatchOrder)
            .where(BatchOrder.batch_id == batch.id)
            .order_by(BatchOrder.sequence)
        )
    ).all()
    assert len(bos) == 2
    assert bos[0].order_id == near.id  # nearer drop-off visited first
    assert bos[1].order_id == far.id


async def test_single_rider_goes_to_tightest_batch(db_session):
    """With one rider and two separate batches, the rider goes to the order closest to
    its SLA deadline — not the one that happened to become ready first."""
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="R", phone="+971500000022", status="available",
        performance={"on_time_pct": 100.0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    # 'fresh' is created first (earlier updated_at -> seeded first today) but has lots of
    # SLA slack; 'tight' is created second but is close to the 40-min deadline. They're
    # far apart -> two separate single-order batches.
    fresh = await _ready_order(db_session, r.id, 25.2048 + 0.018, 55.2708, 211, minutes_since_sla=2)
    tight = await _ready_order(db_session, r.id, 25.2048, 55.2708 + 0.027, 212, minutes_since_sla=25)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(fresh)
    await db_session.refresh(tight)
    assert result.assigned_count == 1
    assert tight.status == "assigned" and tight.rider_id == rider.id
    assert fresh.status == "ready" and fresh.rider_id is None


async def test_priority_batch_beats_tighter_normal_batch_for_scarce_rider(db_session):
    """A priority order keeps first claim on a scarce rider even when a normal order is
    closer to its SLA deadline (urgency ordering must not demote priority)."""
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="R", phone="+971500000023", status="available",
        performance={"on_time_pct": 100.0},
    )
    db_session.add(rider)
    await db_session.flush()
    await _ping(db_session, rider, r.id, 25.2048, 55.2708)
    prio = await _ready_order(db_session, r.id, 25.2048 + 0.018, 55.2708, 221, minutes_since_sla=2)
    prio.priority = "priority"
    await db_session.flush()
    tight_normal = await _ready_order(db_session, r.id, 25.2048, 55.2708 + 0.027, 222, minutes_since_sla=25)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(prio)
    await db_session.refresh(tight_normal)
    assert result.assigned_count == 1
    assert prio.status == "assigned" and prio.rider_id == rider.id
    assert tight_normal.status == "ready"


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


async def test_batch_expedite_nudges_kitchen_for_same_area_cooking_order(db_session):
    """A still-cooking order whose delivery is in the same area as an order going out now
    gets a 'batch_expedite' kitchen nudge; a far cooking order does not."""
    from app.sla.models import SlaEvent

    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="X", phone="+971500000060", status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()

    async def _order(num, lat, lon, status, rider_id=None):
        c = Customer(
            restaurant_id=r.id, phone=f"+971509{num}", name="C",
            usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
        )
        db_session.add(c)
        await db_session.flush()
        addr = CustomerAddress(customer_id=c.id, latitude=lat, longitude=lon, confirmed=True)
        db_session.add(addr)
        await db_session.flush()
        o = Order(
            restaurant_id=r.id, customer_id=c.id, order_number=num, status=status,
            rider_id=rider_id, subtotal=Decimal("10.00"), total=Decimal("10.00"),
            address_id=addr.id,
        )
        db_session.add(o)
        await db_session.flush()
        return o

    # Delivery going out now → area A.
    await _order("A1", 25.2050, 55.2710, "assigned", rider_id=rider.id)
    near = await _order("N1", 25.2055, 55.2715, "preparing")   # ~70 m from A
    far = await _order("F1", 25.2500, 55.3200, "preparing")    # ~6 km away
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    near_events = {e.type for e in (await db_session.scalars(
        select(SlaEvent).where(SlaEvent.order_id == near.id)
    )).all()}
    far_events = {e.type for e in (await db_session.scalars(
        select(SlaEvent).where(SlaEvent.order_id == far.id)
    )).all()}
    assert "batch_expedite" in near_events
    assert "batch_expedite" not in far_events

    msg = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == r.phone)
    )
    assert msg is not None and "N1" in str(msg.payload)
