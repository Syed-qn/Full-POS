from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.cashdrawer.service import add_event, close_session, open_session
from app.cod.models import CodCollection
from app.identity.models import Rider
from app.ordering.models import Customer, Order
from app.reports.zreport import build_z_report


@pytest.mark.anyio
async def test_z_report_aggregates_orders_collections_and_drawer(db_session, restaurant):
    today = date.today()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000077", name="Z Test")
    rider = Rider(restaurant_id=restaurant.id, name="Z Rider", phone="+971500000078", status="available")
    db_session.add_all([cust, rider])
    await db_session.flush()

    order1 = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="Z-0001",
        status="delivered", subtotal=Decimal("100.00"), delivery_fee_aed=Decimal("5.00"),
        coupon_discount_aed=Decimal("10.00"), wallet_applied_aed=Decimal("0.00"),
        total=Decimal("95.00"),
    )
    order2 = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="Z-0002",
        status="cancelled", subtotal=Decimal("50.00"), delivery_fee_aed=Decimal("0.00"),
        total=Decimal("50.00"),
    )
    db_session.add_all([order1, order2])
    await db_session.flush()
    db_session.add(CodCollection(
        order_id=order1.id, rider_id=rider.id, restaurant_id=restaurant.id,
        amount_aed=Decimal("95.00"), collected_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    drawer = await open_session(
        db_session, restaurant_id=restaurant.id, opened_by="manager", opening_float_aed=Decimal("200.00")
    )
    await db_session.commit()
    await add_event(
        db_session, session_id=drawer.id, restaurant_id=restaurant.id,
        type="cash_in", amount_aed=Decimal("95.00"), reason="COD handover", created_by="manager",
    )
    await db_session.commit()
    await close_session(
        db_session, session_id=drawer.id, restaurant_id=restaurant.id,
        closed_by="manager", closing_count_aed=Decimal("295.00"),
    )
    await db_session.commit()

    report = await build_z_report(db_session, restaurant_id=restaurant.id, target_date=today)

    assert report["order_count"] == 2
    assert report["delivered_order_count"] == 1
    assert report["gross_sales_aed"] == Decimal("95.00")  # only delivered order's total
    assert report["total_discounts_aed"] == Decimal("10.00")
    assert report["cod_collected_aed"] == Decimal("95.00")
    assert len(report["drawer_sessions"]) == 1
    assert report["drawer_sessions"][0]["variance_aed"] == Decimal("0.00")
