"""Prep-aware candidate pool tests (spec §5.1)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.dispatch.models import BatchOrder
from app.dispatch.service import run_dispatch_engine
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order


async def _restaurant(db_session, **settings):
    r = Restaurant(
        name="R",
        phone="+971509999001",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
        settings={"dispatch_engine": "greedy", **settings},
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _rider(db_session, r):
    rd = Rider(
        restaurant_id=r.id,
        name="Rider",
        phone="+971509999002",
        status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rd)
    await db_session.flush()
    return rd


async def _order(
    db_session,
    r,
    *,
    lat,
    lon,
    num,
    status="ready",
    prep_deadline_minutes=None,
):
    c = Customer(
        restaurant_id=r.id,
        phone=f"+97150{num:07d}",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=lat, longitude=lon, confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    sla_at = now - timedelta(minutes=5)
    prep_deadline = None
    if prep_deadline_minutes is not None:
        prep_deadline = now + timedelta(minutes=prep_deadline_minutes)
    o = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number=f"O{num}",
        status=status,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        address_id=addr.id,
        sla_confirmed_at=sla_at,
        sla_deadline=sla_at + timedelta(minutes=40),
        promised_eta=sla_at + timedelta(minutes=40),
        prep_deadline=prep_deadline,
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_preparing_order_in_pool_when_prep_deadline_within_lead(db_session):
    """A preparing order near prep_deadline batches with a nearby ready order."""
    r = await _restaurant(db_session, prep_dispatch_lead_min=8, batch_hold_seconds=0)
    rd = await _rider(db_session, r)
    ready = await _order(db_session, r, lat=25.2050, lon=55.2710, num=1, status="ready")
    prep = await _order(
        db_session,
        r,
        lat=25.2052,
        lon=55.2712,
        num=2,
        status="preparing",
        prep_deadline_minutes=6,
    )
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    batch_orders = (await db_session.scalars(select(BatchOrder))).all()
    assert len(batch_orders) >= 2
    assert result.assigned_count >= 2
    await db_session.refresh(ready)
    await db_session.refresh(prep)
    assert ready.status == "assigned"
    assert ready.rider_id == rd.id
    assert prep.status == "preparing"
    assert prep.rider_id == rd.id


async def test_preparing_order_excluded_when_prep_deadline_beyond_lead(db_session):
    """Preparing orders far from prep_deadline stay out of the dispatch pool."""
    r = await _restaurant(db_session, prep_dispatch_lead_min=8, batch_hold_seconds=0)
    rd = await _rider(db_session, r)
    ready = await _order(db_session, r, lat=25.2050, lon=55.2710, num=3, status="ready")
    prep = await _order(
        db_session,
        r,
        lat=25.2052,
        lon=55.2712,
        num=4,
        status="preparing",
        prep_deadline_minutes=20,
    )
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(ready)
    await db_session.refresh(prep)
    assert ready.status == "assigned"
    assert ready.rider_id == rd.id
    assert prep.status == "preparing"
    assert prep.rider_id is None
    assert result.assigned_count == 1
    batch_orders = (await db_session.scalars(select(BatchOrder))).all()
    assert len(batch_orders) == 1