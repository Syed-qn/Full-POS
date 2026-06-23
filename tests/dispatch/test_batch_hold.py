"""Batch hold-window tests (opt-in ``batch_hold_seconds``).

The hold window briefly defers a freshly-ready, lone order so a nearby order can
join its batch before a rider is committed — the standard "batching window". A held
order is skipped this dispatch pass and re-evaluated by the periodic dispatch sweep
until it finds a batch-mate or the window matures. We must NEVER hold an order that:
  * already has a batch-mate ready within proximity,
  * is priority, or
  * is under SLA pressure (waiting the window would risk the internal target).
Default ``batch_hold_seconds`` = 0 keeps the original assign-immediately behaviour.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.dispatch.models import Batch, RiderLocation
from app.dispatch.service import run_dispatch_engine
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order


async def _restaurant(db_session, hold_seconds, lat=25.2048, lng=55.2708):
    r = Restaurant(
        name="R", phone=f"+9710{hold_seconds:06d}", password_hash="x", lat=lat, lng=lng,
        settings={
            "dispatch_engine": "greedy",
            "batch_hold_seconds": hold_seconds,
            "batch_proximity_km": 1.0,
        },
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _rider(db_session, r, lat=25.2048, lng=55.2708):
    rd = Rider(
        restaurant_id=r.id, name="Rider", phone=f"+9715{r.id:07d}", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rd)
    await db_session.flush()
    db_session.add(RiderLocation(
        rider_id=rd.id, restaurant_id=r.id, latitude=lat, longitude=lng,
        ts=datetime.now(timezone.utc),
    ))
    await db_session.flush()
    return rd


async def _ready_order(
    db_session, r, lat, lon, num,
    ready_minutes_ago=0, elapsed_min=5, priority="normal",
):
    c = Customer(
        restaurant_id=r.id, phone=f"+97150{num:07d}", name="C", usual_order_times={},
        tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=lat, longitude=lon, confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    sla_at = now - timedelta(minutes=elapsed_min)
    o = Order(
        restaurant_id=r.id, customer_id=c.id, order_number=f"O{num}", status="ready",
        priority=priority, weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"), total=Decimal("10.00"), address_id=addr.id,
        sla_confirmed_at=sla_at, sla_deadline=sla_at + timedelta(minutes=40),
        promised_eta=sla_at + timedelta(minutes=40),
        # updated_at is the "became ready" proxy the hold window reads; set on INSERT
        # (no BEFORE UPDATE trigger fires) so we can simulate a matured wait. The column
        # is TIMESTAMP WITHOUT TIME ZONE, so store naive UTC (engine coerces to UTC).
        updated_at=(now - timedelta(minutes=ready_minutes_ago)).replace(tzinfo=None),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_hold_disabled_assigns_immediately(db_session):
    """Default batch_hold_seconds=0 → a lone fresh order is assigned at once (no regression)."""
    r = await _restaurant(db_session, hold_seconds=0)
    rd = await _rider(db_session, r)
    o = await _ready_order(db_session, r, 25.2050, 55.2710, 1, ready_minutes_ago=0)
    await db_session.commit()

    res = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "assigned"
    assert o.rider_id == rd.id
    assert res.assigned_count == 1


async def test_lone_fresh_order_is_held(db_session):
    """A single fresh order is held (not assigned) while the window is open."""
    r = await _restaurant(db_session, hold_seconds=120)
    await _rider(db_session, r)
    o = await _ready_order(db_session, r, 25.2050, 55.2710, 2, ready_minutes_ago=0)
    await db_session.commit()

    res = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "ready"
    assert o.rider_id is None
    assert res.assigned_count == 0


async def test_held_order_releases_after_window(db_session):
    """Once it has waited past the window, the lone order is dispatched."""
    r = await _restaurant(db_session, hold_seconds=120)
    rd = await _rider(db_session, r)
    o = await _ready_order(db_session, r, 25.2050, 55.2710, 3, ready_minutes_ago=3)  # 180s > 120
    await db_session.commit()

    res = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "assigned"
    assert o.rider_id == rd.id
    assert res.assigned_count == 1


async def test_two_close_fresh_orders_batch_immediately(db_session):
    """Two nearby fresh orders each have a batch-mate present → no hold; they batch now."""
    r = await _restaurant(db_session, hold_seconds=120)
    rd = await _rider(db_session, r)
    o1 = await _ready_order(db_session, r, 25.2050, 55.2710, 4, ready_minutes_ago=0)
    o2 = await _ready_order(db_session, r, 25.2052, 55.2712, 5, ready_minutes_ago=0)  # ~0.03 km
    await db_session.commit()

    res = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    for o in (o1, o2):
        await db_session.refresh(o)
    assert o1.status == "assigned" and o2.status == "assigned"
    assert o1.rider_id == rd.id and o2.rider_id == rd.id
    assert res.assigned_count == 2
    batches = (
        await db_session.execute(select(Batch).where(Batch.restaurant_id == r.id))
    ).scalars().all()
    assert len(batches) == 1  # one rider trip, both stops


async def test_sla_pressure_overrides_hold(db_session):
    """A fresh order already deep into its SLA can't afford the wait → dispatched now."""
    r = await _restaurant(db_session, hold_seconds=120)
    rd = await _rider(db_session, r)
    o = await _ready_order(
        db_session, r, 25.2050, 55.2710, 6, ready_minutes_ago=0, elapsed_min=29,
    )
    await db_session.commit()

    res = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "assigned"
    assert o.rider_id == rd.id
    assert res.assigned_count == 1


async def test_priority_order_not_held(db_session):
    """Priority orders bypass the hold window entirely."""
    r = await _restaurant(db_session, hold_seconds=120)
    rd = await _rider(db_session, r)
    o = await _ready_order(
        db_session, r, 25.2050, 55.2710, 7, ready_minutes_ago=0, priority="priority",
    )
    await db_session.commit()

    res = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "assigned"
    assert o.rider_id == rd.id
    assert res.assigned_count == 1
