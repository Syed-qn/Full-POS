"""Hard-delete of a rider (the dashboard "Remove" button).

A rider referenced by orders/assignments/batches/locations must still be
deletable (those are detached/cleaned), but a rider holding financial records
(COD cash) must be blocked — deactivate instead.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.cod.models import CodCollection
from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation
from app.identity.models import Restaurant, Rider
from app.identity.service import RiderHasHistoryError, delete_rider
from app.ordering.models import Customer, Order


async def _restaurant(db_session):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    return r


async def _rider(db_session, r, phone="+971500000010"):
    rider = Rider(
        restaurant_id=r.id, name="Test", phone=phone, status="on_delivery",
        performance={},
    )
    db_session.add(rider)
    await db_session.flush()
    return rider


async def _order(db_session, r, rider, status="assigned"):
    c = Customer(restaurant_id=r.id, phone="+971501112233", name="C",
                 total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(c)
    await db_session.flush()
    o = Order(
        restaurant_id=r.id, customer_id=c.id, order_number="O1", status=status,
        rider_id=rider.id, subtotal=Decimal("10.00"),
        delivery_fee_aed=Decimal("0.00"), total=Decimal("10.00"),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_delete_rider_with_no_refs(db_session):
    r = await _restaurant(db_session)
    rider = await _rider(db_session, r)
    await db_session.commit()

    ok = await delete_rider(db_session, restaurant_id=r.id, rider_id=rider.id)
    assert ok is True
    assert await db_session.get(Rider, rider.id) is None


async def test_delete_rider_detaches_active_order_and_cleans_ops(db_session):
    r = await _restaurant(db_session)
    rider = await _rider(db_session, r)
    order = await _order(db_session, r, rider, status="assigned")
    batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="planned", route={})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    db_session.add(Assignment(order_id=order.id, rider_id=rider.id, batch_id=batch.id,
                              assigned_at=datetime.now(timezone.utc), algorithm_score={}))
    db_session.add(RiderLocation(rider_id=rider.id, restaurant_id=r.id,
                                 latitude=25.2, longitude=55.2, ts=datetime.now(timezone.utc)))
    await db_session.commit()

    ok = await delete_rider(db_session, restaurant_id=r.id, rider_id=rider.id)
    assert ok is True

    assert await db_session.get(Rider, rider.id) is None
    await db_session.refresh(order)
    assert order.rider_id is None          # detached
    assert order.status == "ready"         # active delivery returned to the pool
    # operational rows gone
    assert (await db_session.scalars(select(Assignment).where(Assignment.rider_id == rider.id))).first() is None
    assert (await db_session.scalars(select(Batch).where(Batch.rider_id == rider.id))).first() is None
    assert (await db_session.scalars(select(RiderLocation).where(RiderLocation.rider_id == rider.id))).first() is None


async def test_delete_rider_blocked_by_cod_records(db_session):
    r = await _restaurant(db_session)
    rider = await _rider(db_session, r)
    order = await _order(db_session, r, rider, status="delivered")
    db_session.add(CodCollection(order_id=order.id, rider_id=rider.id, restaurant_id=r.id,
                                 amount_aed=Decimal("10.00"), collected_at=datetime.now(timezone.utc)))
    await db_session.commit()

    with pytest.raises(RiderHasHistoryError, match="payment records"):
        await delete_rider(db_session, restaurant_id=r.id, rider_id=rider.id)
    # rider preserved
    assert await db_session.get(Rider, rider.id) is not None
