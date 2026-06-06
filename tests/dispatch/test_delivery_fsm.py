"""Delivery FSM tests (spec §3): assigned -> picked_up -> arriving -> delivered.

Schema adaptation (matching the real models, per Phase-3 T2 flags):
  * Restaurant pickup coords are ``lat``/``lng`` (not location_lat/lon).
  * Orders carry no ``dropoff_lat/lon`` columns; drop-off coordinates are not
    needed by the delivery FSM so the seed omits an address entirely.
  * Rider position lives in ``rider_locations``; the Rider model has no
    ``last_lat/last_lon`` columns, so the seed omits them.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.dispatch.delivery import InvalidTransitionError, advance_delivery
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed(db_session, status="assigned", *, batched=True):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="X",
        phone="+971500000010",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    c = Customer(
        restaurant_id=r.id,
        phone="+971501112233",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    o = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number="O1",
        status=status,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        rider_id=rider.id,
        sla_deadline=datetime.now(timezone.utc) + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    if batched:
        batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="picked_up", route={"stops": []})
        db_session.add(batch)
        await db_session.flush()
        db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=1))
    await db_session.commit()
    return r, rider, o


async def test_assigned_to_picked_up(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    await advance_delivery(db_session, order_id=o.id, to_status="picked_up")
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "picked_up"


async def test_full_happy_path_to_delivered_sets_timestamp(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    for nxt in ("picked_up", "arriving", "delivered"):
        await advance_delivery(db_session, order_id=o.id, to_status=nxt)
        await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "delivered"
    assert o.delivered_at is not None
    assert o.late is False  # within deadline


async def test_late_flag_set_when_past_deadline(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    o.sla_deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    await advance_delivery(db_session, order_id=o.id, to_status="delivered")
    await db_session.commit()
    await db_session.refresh(o)
    assert o.late is True


async def test_illegal_transition_rejected(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    with pytest.raises(InvalidTransitionError):
        await advance_delivery(db_session, order_id=o.id, to_status="delivered")


async def test_transition_writes_audit(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    await advance_delivery(db_session, order_id=o.id, to_status="picked_up")
    await db_session.commit()
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.entity == "order", AuditLog.entity_id == str(o.id))
    )
    assert audit is not None


async def test_last_delivery_completes_batch_and_frees_rider(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    await advance_delivery(db_session, order_id=o.id, to_status="delivered")
    await db_session.commit()
    await db_session.refresh(rider)
    assert rider.status == "available"
    bo = await db_session.scalar(select(BatchOrder).where(BatchOrder.order_id == o.id))
    assert bo.delivered_at is not None
    batch = await db_session.get(Batch, bo.batch_id)
    assert batch.status == "completed"
