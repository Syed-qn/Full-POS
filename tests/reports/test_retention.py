from datetime import date, datetime
from decimal import Decimal

import pytest

from app.reports.analytics import retention_report


async def _make_customer_order(db_session, restaurant, *, phone, order_number, created_at, customer=None):
    from app.ordering.models import Customer, Order

    if customer is None:
        customer = Customer(restaurant_id=restaurant.id, phone=phone, name="Retention Test")
        db_session.add(customer)
        await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number=order_number,
        status="delivered", subtotal=Decimal("10.00"), total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.flush()
    order.created_at = created_at
    await db_session.commit()
    return customer, order


@pytest.mark.anyio
async def test_retention_report_splits_new_and_returning(db_session, restaurant):
    # Returning customer: first order before the window, another inside it.
    returning_cust, _ = await _make_customer_order(
        db_session, restaurant, phone="+971500000201", order_number="RT-0001",
        created_at=datetime(2026, 5, 1, 9, 0),
    )
    await _make_customer_order(
        db_session, restaurant, phone="+971500000201", order_number="RT-0002",
        created_at=datetime(2026, 6, 5, 9, 0),
        customer=returning_cust,
    )

    # New customer: only ever ordered inside the window.
    await _make_customer_order(
        db_session, restaurant, phone="+971500000202", order_number="RT-0003",
        created_at=datetime(2026, 6, 10, 9, 0),
    )

    results = await retention_report(
        db_session, restaurant_id=restaurant.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )

    assert results["new_customers"] == 1
    assert results["returning_customers"] == 1
    assert results["repeat_rate_pct"] == pytest.approx(50.0)


@pytest.mark.anyio
async def test_retention_report_empty_range(db_session, restaurant):
    results = await retention_report(
        db_session, restaurant_id=restaurant.id,
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
    )
    assert results == {"new_customers": 0, "returning_customers": 0, "repeat_rate_pct": 0.0}


@pytest.mark.anyio
async def test_retention_report_router(client, auth_headers):
    resp = await client.get(
        "/api/v1/reports/retention?start_date=2026-06-01&end_date=2026-06-30",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"new_customers": 0, "returning_customers": 0, "repeat_rate_pct": 0.0}
