from datetime import date
from decimal import Decimal

import pytest

from app.reports.analytics import invoice_sequence_report


async def _make_order(db_session, restaurant, *, order_number: str, status: str):
    from app.ordering.models import Customer, Order

    cust = Customer(
        restaurant_id=restaurant.id,
        phone=f"+9715000{abs(hash(order_number)) % 100000:05d}",
        name="Seq Test",
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number=order_number,
        status=status,
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.flush()
    return order


@pytest.mark.anyio
async def test_no_gaps_when_sequence_is_consecutive(db_session, restaurant):
    for i in range(1, 4):
        await _make_order(db_session, restaurant, order_number=f"R{restaurant.id}-{i:04d}", status="confirmed")
    await db_session.commit()

    today = date.today()
    report = await invoice_sequence_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert report["first_invoice"] == f"R{restaurant.id}-0001"
    assert report["last_invoice"] == f"R{restaurant.id}-0003"
    assert report["expected_count"] == 3
    assert report["actual_count"] == 3
    assert report["gaps_detected"] == []


@pytest.mark.anyio
async def test_detects_gap_in_confirmed_sequence(db_session, restaurant):
    await _make_order(db_session, restaurant, order_number=f"R{restaurant.id}-0001", status="confirmed")
    # 0002 deliberately missing
    await _make_order(db_session, restaurant, order_number=f"R{restaurant.id}-0003", status="delivered")
    await db_session.commit()

    today = date.today()
    report = await invoice_sequence_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert report["first_invoice"] == f"R{restaurant.id}-0001"
    assert report["last_invoice"] == f"R{restaurant.id}-0003"
    assert report["expected_count"] == 3
    assert report["actual_count"] == 2
    assert report["gaps_detected"] == [f"R{restaurant.id}-0002"]


@pytest.mark.anyio
async def test_draft_orders_excluded_from_sequence_check(db_session, restaurant):
    await _make_order(db_session, restaurant, order_number=f"R{restaurant.id}-0001", status="confirmed")
    # Draft never became an invoice — its "gap" in raw allocation is expected and
    # must NOT be reported since it was never issued as a tax invoice.
    await _make_order(db_session, restaurant, order_number=f"R{restaurant.id}-0002", status="draft")
    await _make_order(db_session, restaurant, order_number=f"R{restaurant.id}-0003", status="delivered")
    await db_session.commit()

    today = date.today()
    report = await invoice_sequence_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert report["actual_count"] == 2
    assert report["gaps_detected"] == [f"R{restaurant.id}-0002"]


@pytest.mark.anyio
async def test_empty_range_returns_zero_report(db_session, restaurant):
    today = date.today()
    report = await invoice_sequence_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert report == {
        "first_invoice": None,
        "last_invoice": None,
        "expected_count": 0,
        "actual_count": 0,
        "gaps_detected": [],
    }


@pytest.mark.anyio
async def test_invoice_sequence_check_router_endpoint(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    await _make_order(db_session, restaurant, order_number=f"R{restaurant.id}-0001", status="confirmed")
    await _make_order(db_session, restaurant, order_number=f"R{restaurant.id}-0003", status="delivered")
    await db_session.commit()

    today = date.today().isoformat()
    resp = await client.get(
        f"/api/v1/reports/invoice-sequence-check?start_date={today}&end_date={today}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["actual_count"] == 2
    assert body["expected_count"] == 3
    assert body["gaps_detected"] == [f"R{restaurant.id}-0002"]
