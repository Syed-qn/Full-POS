"""Unit tests for dispatch/tracking.py — build_tracking_reply."""

from datetime import datetime, timezone
from decimal import Decimal

from app.dispatch.models import RiderLocation
from app.dispatch.tracking import build_tracking_reply
from app.geo.fake import FakeGeoProvider
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order


# ---------------------------------------------------------------------------
# Seed helpers (mirrors patterns in tests/dispatch/test_dispatch_engine.py)
# ---------------------------------------------------------------------------


async def _seed_restaurant(db_session) -> Restaurant:
    r = Restaurant(
        name="TrackTest",
        phone="+971900000001",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _seed_rider(db_session, restaurant_id: int) -> Rider:
    rider = Rider(
        restaurant_id=restaurant_id,
        name="Ali",
        phone="+971500000099",
        status="on_delivery",
        performance={"on_time_pct": 95.0, "avg_delivery_min": 22, "total_deliveries": 10},
    )
    db_session.add(rider)
    await db_session.flush()
    return rider


async def _seed_order(
    db_session,
    restaurant_id: int,
    status: str,
    rider_id: int | None = None,
    drop_lat: float = 25.2100,
    drop_lon: float = 55.2750,
) -> Order:
    customer = Customer(
        restaurant_id=restaurant_id,
        phone="+971501234999",
        name="Test Customer",
        usual_order_times={},
        tags={},
        total_orders=1,
        total_spend=Decimal("25.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id,
        latitude=drop_lat,
        longitude=drop_lon,
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        order_number="T001",
        status=status,
        priority="normal",
        rider_id=rider_id,
        address_id=addr.id,
        subtotal=Decimal("25.00"),
        delivery_fee_aed=Decimal("5.00"),
        total=Decimal("30.00"),
        weather_delay_disclosed=False,
    )
    db_session.add(order)
    await db_session.flush()
    return order


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_tracking_reply_preparing(db_session):
    """Non-en-route status 'preparing' → base human message, no ETA."""
    r = await _seed_restaurant(db_session)
    order = await _seed_order(db_session, r.id, status="preparing")

    geo = FakeGeoProvider()
    reply = await build_tracking_reply(db_session, order=order, geo=geo)

    assert "prepar" in reply.lower()
    # No ETA injected for non-en-route statuses
    assert "min" not in reply


async def test_tracking_reply_en_route_includes_eta(db_session):
    """En-route 'arriving' with a rider GPS ping → reply includes ETA in minutes."""
    r = await _seed_restaurant(db_session)
    rider = await _seed_rider(db_session, r.id)

    # Rider is ~0.5 km away from drop-off
    order = await _seed_order(
        db_session,
        r.id,
        status="arriving",
        rider_id=rider.id,
        drop_lat=25.2100,
        drop_lon=55.2750,
    )

    # Record a GPS ping for the rider slightly away from the drop-off
    db_session.add(
        RiderLocation(
            rider_id=rider.id,
            restaurant_id=r.id,
            latitude=25.2055,   # ~0.5 km north of drop-off
            longitude=55.2750,
            ts=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()

    geo = FakeGeoProvider()
    reply = await build_tracking_reply(db_session, order=order, geo=geo)

    assert "min" in reply
    # FakeGeoProvider is always an estimate
    assert "estimated" in reply


async def test_tracking_reply_delivered(db_session):
    """Terminal status 'delivered' → reply contains 'deliver'."""
    r = await _seed_restaurant(db_session)
    order = await _seed_order(db_session, r.id, status="delivered")

    geo = FakeGeoProvider()
    reply = await build_tracking_reply(db_session, order=order, geo=geo)

    assert "deliver" in reply.lower()
