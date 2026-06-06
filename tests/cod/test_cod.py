"""COD ledger tests (spec §4.4.4 / §3).

Schema note: orders carry no ``dropoff_lat/lon`` columns, so the seeded orders
omit them (the COD service only needs order_id/rider_id/amount).
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.cod.models import CodCollection, RiderShiftReconciliation
from app.cod.service import reconcile_shift, record_collection
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed(db_session):
    r = Restaurant(name="R", phone="+9716667777", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="X",
        phone="+971509990002",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    c = Customer(
        restaurant_id=r.id,
        phone="+971501239999",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    return r, rider, c


async def _order(db_session, r, rider, c, num, total):
    o = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number=num,
        status="delivered",
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=total,
        total=total,
        rider_id=rider.id,
    )
    db_session.add(o)
    await db_session.commit()
    return o


async def test_record_collection_writes_row(db_session):
    r, rider, c = await _seed(db_session)
    o = await _order(db_session, r, rider, c, "O1", Decimal("30.00"))
    await record_collection(
        db_session, restaurant_id=r.id, order_id=o.id, rider_id=rider.id, amount=Decimal("30.00")
    )
    await db_session.commit()
    row = await db_session.scalar(
        select(CodCollection).where(CodCollection.order_id == o.id)
    )
    assert row.amount_aed == Decimal("30.00")


async def test_record_collection_idempotent(db_session):
    r, rider, c = await _seed(db_session)
    o = await _order(db_session, r, rider, c, "O2", Decimal("15.00"))
    await record_collection(
        db_session, restaurant_id=r.id, order_id=o.id, rider_id=rider.id, amount=Decimal("15.00")
    )
    await db_session.commit()
    await record_collection(
        db_session, restaurant_id=r.id, order_id=o.id, rider_id=rider.id, amount=Decimal("15.00")
    )
    await db_session.commit()
    rows = (
        await db_session.scalars(
            select(CodCollection).where(CodCollection.order_id == o.id)
        )
    ).all()
    assert len(rows) == 1


async def test_reconcile_shift_balanced(db_session):
    r, rider, c = await _seed(db_session)
    o = await _order(db_session, r, rider, c, "O3", Decimal("25.00"))
    await record_collection(
        db_session, restaurant_id=r.id, order_id=o.id, rider_id=rider.id, amount=Decimal("25.00")
    )
    await db_session.commit()
    rec = await reconcile_shift(
        db_session,
        restaurant_id=r.id,
        rider_id=rider.id,
        shift_date=datetime.now(timezone.utc).date(),
    )
    await db_session.commit()
    assert rec.expected_total_aed == Decimal("25.00")
    assert rec.collected_total_aed == Decimal("25.00")
    assert rec.variance_aed == Decimal("0.00")
    assert rec.status == "balanced"
    persisted = await db_session.scalar(
        select(RiderShiftReconciliation).where(
            RiderShiftReconciliation.rider_id == rider.id
        )
    )
    assert persisted is not None
