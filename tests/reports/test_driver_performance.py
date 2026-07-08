from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.reports.analytics import driver_performance_report


async def _make_rider(db_session, restaurant, *, name, phone):
    from app.identity.models import Rider

    rider = Rider(restaurant_id=restaurant.id, name=name, phone=phone, status="available")
    db_session.add(rider)
    await db_session.flush()
    return rider


async def _make_delivered_order(
    db_session, restaurant, rider, *, order_number, sla_confirmed_at, delivered_at, late
):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone=f"+9715000{order_number}", name="Cust")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number=order_number,
        status="delivered",
        rider_id=rider.id,
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        sla_confirmed_at=sla_confirmed_at,
        delivered_at=delivered_at,
        late=late,
    )
    db_session.add(order)
    await db_session.flush()
    return order


@pytest.mark.anyio
async def test_driver_performance_reports_avg_time_and_late_pct(db_session, restaurant):
    rider = await _make_rider(db_session, restaurant, name="Ali", phone="+971500000201")

    base = datetime.now(timezone.utc) - timedelta(days=1)
    await _make_delivered_order(
        db_session, restaurant, rider,
        order_number="DP-0001",
        sla_confirmed_at=base,
        delivered_at=base + timedelta(minutes=20),
        late=False,
    )
    await _make_delivered_order(
        db_session, restaurant, rider,
        order_number="DP-0002",
        sla_confirmed_at=base,
        delivered_at=base + timedelta(minutes=40),
        late=True,
    )
    await db_session.commit()

    today = date.today()
    start = today - timedelta(days=2)
    results = await driver_performance_report(
        db_session, restaurant_id=restaurant.id, start_date=start, end_date=today
    )

    assert len(results) == 1
    row = results[0]
    assert row["rider_id"] == rider.id
    assert row["rider_name"] == "Ali"
    assert row["delivery_count"] == 2
    assert row["avg_delivery_minutes"] == pytest.approx(30.0)
    assert row["late_count"] == 1
    assert row["late_pct"] == pytest.approx(50.0)


@pytest.mark.anyio
async def test_driver_performance_excludes_riders_with_no_deliveries_in_range(db_session, restaurant):
    rider = await _make_rider(db_session, restaurant, name="Bystander", phone="+971500000202")
    await db_session.commit()

    today = date.today()
    results = await driver_performance_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert results == []


@pytest.mark.anyio
async def test_driver_performance_ignores_orders_missing_delivered_at(db_session, restaurant):
    rider = await _make_rider(db_session, restaurant, name="Carl", phone="+971500000203")
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000299", name="NoDeliver")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="DP-0099",
        status="assigned", rider_id=rider.id,
        subtotal=Decimal("10.00"), total=Decimal("10.00"),
        sla_confirmed_at=datetime.now(timezone.utc),
    )
    db_session.add(order)
    await db_session.commit()

    today = date.today()
    results = await driver_performance_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert results == []
