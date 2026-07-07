from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.reports.analytics import sales_rollup


async def _make_order(db_session, restaurant, *, phone, order_number, status, created_at, total):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone=phone, name="Rollup Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number=order_number,
        status=status, subtotal=total, total=total,
    )
    db_session.add(order)
    await db_session.flush()
    order.created_at = created_at
    await db_session.commit()
    return order


@pytest.mark.anyio
async def test_sales_rollup_hourly_groups_by_hour(db_session, restaurant):
    base = datetime(2026, 6, 1, 10, 15)
    await _make_order(
        db_session, restaurant, phone="+971500000101", order_number="R-0001",
        status="delivered", created_at=base, total=Decimal("10.00"),
    )
    await _make_order(
        db_session, restaurant, phone="+971500000102", order_number="R-0002",
        status="delivered", created_at=base + timedelta(minutes=20), total=Decimal("15.00"),
    )
    await _make_order(
        db_session, restaurant, phone="+971500000103", order_number="R-0003",
        status="delivered", created_at=base + timedelta(hours=1), total=Decimal("5.00"),
    )
    await _make_order(
        db_session, restaurant, phone="+971500000104", order_number="R-0004",
        status="cancelled", created_at=base, total=Decimal("99.00"),
    )
    await _make_order(
        db_session, restaurant, phone="+971500000105", order_number="R-0005",
        status="draft", created_at=base, total=Decimal("99.00"),
    )

    results = await sales_rollup(
        db_session, restaurant_id=restaurant.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
        granularity="hourly",
    )

    assert len(results) == 2
    assert results[0]["order_count"] == 2
    assert results[0]["revenue_aed"] == Decimal("25.00")
    assert results[1]["order_count"] == 1
    assert results[1]["revenue_aed"] == Decimal("5.00")
    assert results[0]["bucket"] < results[1]["bucket"]


@pytest.mark.anyio
async def test_sales_rollup_daily_groups_by_day(db_session, restaurant):
    await _make_order(
        db_session, restaurant, phone="+971500000111", order_number="R-0011",
        status="delivered", created_at=datetime(2026, 6, 1, 9, 0),
        total=Decimal("10.00"),
    )
    await _make_order(
        db_session, restaurant, phone="+971500000112", order_number="R-0012",
        status="delivered", created_at=datetime(2026, 6, 2, 9, 0),
        total=Decimal("20.00"),
    )

    results = await sales_rollup(
        db_session, restaurant_id=restaurant.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        granularity="daily",
    )

    assert len(results) == 2
    assert results[0]["revenue_aed"] == Decimal("10.00")
    assert results[1]["revenue_aed"] == Decimal("20.00")


@pytest.mark.anyio
async def test_sales_rollup_rejects_invalid_granularity(db_session, restaurant):
    with pytest.raises(ValueError):
        await sales_rollup(
            db_session, restaurant_id=restaurant.id,
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
            granularity="fortnightly",
        )


@pytest.mark.anyio
async def test_sales_rollup_router_returns_stringified_decimals(client, auth_headers):
    resp = await client.get(
        "/api/v1/reports/sales-rollup"
        "?start_date=2026-06-01&end_date=2026-06-01&granularity=daily",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_sales_rollup_router_rejects_bad_granularity(client, auth_headers):
    resp = await client.get(
        "/api/v1/reports/sales-rollup"
        "?start_date=2026-06-01&end_date=2026-06-01&granularity=fortnightly",
        headers=auth_headers,
    )
    assert resp.status_code == 400
