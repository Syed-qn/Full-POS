"""Dispatch KPI aggregation tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.dispatch.kpis import compute_dispatch_kpis
from app.dispatch.models import Assignment, Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order


async def _seed_batch_assignment(db_session, *, multi_stop: bool):
    r = Restaurant(
        name="KPI",
        phone="+971508888001",
        password_hash="x",
        lat=25.2,
        lng=55.2,
        settings={},
    )
    db_session.add(r)
    await db_session.flush()
    rd = Rider(
        restaurant_id=r.id,
        name="R",
        phone="+971508888002",
        status="available",
        performance={},
    )
    db_session.add(rd)
    await db_session.flush()

    async def _order(num: int):
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
        addr = CustomerAddress(
            customer_id=c.id, latitude=25.2, longitude=55.2, confirmed=True
        )
        db_session.add(addr)
        await db_session.flush()
        now = datetime.now(timezone.utc)
        o = Order(
            restaurant_id=r.id,
            customer_id=c.id,
            order_number=f"K{num}",
            status="assigned",
            priority="normal",
            weather_delay_disclosed=False,
            delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("10.00"),
            total=Decimal("10.00"),
            address_id=addr.id,
            rider_id=rd.id,
            sla_confirmed_at=now,
            sla_deadline=now + timedelta(minutes=40),
            promised_eta=now + timedelta(minutes=40),
        )
        db_session.add(o)
        await db_session.flush()
        return o

    o1 = await _order(1)
    orders = [o1]
    if multi_stop:
        orders.append(await _order(2))

    batch = Batch(
        restaurant_id=r.id,
        rider_id=rd.id,
        status="planned",
        route={},
        total_est_min=20,
    )
    db_session.add(batch)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    for seq, o in enumerate(orders, start=1):
        db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=seq))
        db_session.add(
            Assignment(
                order_id=o.id,
                rider_id=rd.id,
                batch_id=batch.id,
                assigned_at=now,
                algorithm_score={
                    "engine": "ortools",
                    "engine_fallback": seq == 2,
                },
            )
        )
    await db_session.commit()
    return r


async def test_compute_dispatch_kpis_empty(db_session):
    r = Restaurant(
        name="Empty",
        phone="+971507777001",
        password_hash="x",
        lat=25.2,
        lng=55.2,
        settings={},
    )
    db_session.add(r)
    await db_session.commit()
    kpis = await compute_dispatch_kpis(db_session, restaurant_id=r.id)
    assert kpis == {
        "batch_rate_pct": 0.0,
        "avg_stops": 0.0,
        "engine_fallback_pct": 0.0,
        "window": "today",
    }


async def test_compute_dispatch_kpis_multi_stop_batch(db_session):
    r = await _seed_batch_assignment(db_session, multi_stop=True)
    kpis = await compute_dispatch_kpis(db_session, restaurant_id=r.id)
    assert kpis["batch_rate_pct"] == 100.0
    assert kpis["avg_stops"] == 2.0
    assert kpis["engine_fallback_pct"] == 50.0


async def test_compute_dispatch_kpis_solo_only(db_session):
    r = await _seed_batch_assignment(db_session, multi_stop=False)
    kpis = await compute_dispatch_kpis(db_session, restaurant_id=r.id)
    assert kpis["batch_rate_pct"] == 0.0
    assert kpis["avg_stops"] == 0.0
    assert kpis["engine_fallback_pct"] == 0.0