"""Dispatch engine integration tests (spec §4.3).

Schema adaptation (per Phase-3 T2 flags — NO new migration):
  * Restaurant pickup coords are ``lat``/``lng`` (not location_lat/lon).
  * Order drop-off is resolved via ``address_id`` -> CustomerAddress.latitude/
    longitude (there are no Order.dropoff_lat/lon columns).
  * Rider position lives in the ``rider_locations`` table (no Rider.last_lat/lon);
    a rider with no ping is treated as co-located with the restaurant (distance 0).
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation
from app.dispatch.service import run_dispatch_engine
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order
from app.outbox.models import OutboxMessage


async def _seed_restaurant(db_session, lat=25.2048, lng=55.2708):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x", lat=lat, lng=lng)
    db_session.add(r)
    await db_session.flush()
    return r


async def _ready_order(db_session, restaurant_id, lat, lon, num):
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
