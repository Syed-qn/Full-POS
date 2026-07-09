"""Category 10 — reporting & owner dashboard full wiring tests."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_sales_by_channel_and_waiter(db_session, restaurant):
    from app.ordering.models import Customer, Order
    from app.reports.extended import sales_by_channel, sales_by_waiter
    from app.staff.models import StaffMember
    from app.identity.auth import hash_password

    staff = StaffMember(
        restaurant_id=restaurant.id,
        name="Waiter A",
        role="staff",
        pin_hash=hash_password("1111"),
    )
    db_session.add(staff)
    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500010001",
        name="C",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()

    for i, (ch, total) in enumerate(
        [("talabat", "40"), ("website", "30"), ("whatsapp", "20")]
    ):
        o = Order(
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            order_number=f"C10-{i}",
            status="delivered",
            subtotal=Decimal(total),
            total=Decimal(total),
            source_channel=ch,
            staff_id=staff.id if i < 2 else None,
            is_training=False,
        )
        db_session.add(o)
    await db_session.commit()

    today = date.today()
    channels = await sales_by_channel(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    by_ch = {c["channel"]: c for c in channels}
    assert by_ch["talabat"]["order_count"] == 1
    assert by_ch["website"]["revenue_aed"] == Decimal("30.00")

    waiters = await sales_by_waiter(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assigned = next(w for w in waiters if w["staff_id"] == staff.id)
    assert assigned["order_count"] == 2


@pytest.mark.anyio
async def test_void_discount_tax_aov(db_session, restaurant):
    from app.ordering.models import Customer, Order
    from app.reports.extended import (
        average_order_value,
        discount_report,
        tax_report,
        void_report,
    )

    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500010002",
        name="C2",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()

    good = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C10-G1",
        status="delivered",
        subtotal=Decimal("100"),
        total=Decimal("105"),
        vat_amount_aed=Decimal("5"),
        vat_rate=Decimal("0.05"),
        manager_discount_aed=Decimal("10"),
        is_training=False,
    )
    voided = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C10-V1",
        status="cancelled",
        subtotal=Decimal("50"),
        total=Decimal("50"),
        cancellation_reason="customer request",
        cancelled_at=datetime.now(timezone.utc),
        is_training=False,
    )
    db_session.add_all([good, voided])
    await db_session.commit()

    today = date.today()
    voids = await void_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert voids["void_count"] == 1
    assert voids["void_value_aed"] == "50.00"

    disc = await discount_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert disc["manager_discount_aed"] == "10.00"

    tax = await tax_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert tax["vat_total_aed"] == "5.00"

    aov = await average_order_value(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    # only non-cancelled non-training
    assert aov["order_count"] == 1
    assert aov["aov_aed"] == "105.00"


@pytest.mark.anyio
async def test_dead_and_top_items(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem
    from app.reports.extended import dead_menu_items, top_selling_items

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    d1 = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Hot Seller",
        price_aed=Decimal("20"),
        is_available=True,
        name_normalized="hot seller",
        category="Mains",
    )
    d2 = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=2,
        name="Dead Dish",
        price_aed=Decimal("15"),
        is_available=True,
        name_normalized="dead dish",
        category="Mains",
    )
    db_session.add_all([d1, d2])
    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500010003",
        name="C3",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C10-TOP",
        status="delivered",
        subtotal=Decimal("40"),
        total=Decimal("40"),
        is_training=False,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=d1.id,
            dish_number=1,
            dish_name="Hot Seller",
            price_aed=Decimal("20"),
            qty=2,
        )
    )
    await db_session.commit()

    today = date.today()
    top = await top_selling_items(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today, limit=5
    )
    assert top[0]["dish_name"] == "Hot Seller"

    dead = await dead_menu_items(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    names = {d["dish_name"] for d in dead}
    assert "Dead Dish" in names
    assert "Hot Seller" not in names


@pytest.mark.anyio
async def test_xlsx_export_bytes():
    from app.reports.xlsx_export import build_xlsx

    data = build_xlsx(
        {
            "A": (["x", "y"], [["1", "2"], ["3", "4"]]),
            "B": (["m"], [["ok"]]),
        }
    )
    assert data[:2] == b"PK"  # zip/xlsx magic
    assert len(data) > 100


@pytest.mark.anyio
async def test_owner_whatsapp_report_and_api(client, auth_headers, restaurant, db_session):
    from app.identity.models import Restaurant
    from sqlalchemy import select

    # set phone on restaurant for owner report
    rest = await db_session.scalar(select(Restaurant).where(Restaurant.id == restaurant.id))
    rest.phone = "+971500019999"
    settings = dict(rest.settings or {})
    settings["owner_whatsapp"] = "+971500019999"
    rest.settings = settings
    await db_session.commit()

    today = date.today().isoformat()
    summary = await client.get(
        f"/api/v1/reports/owner-daily-summary?target_date={today}",
        headers=auth_headers,
    )
    assert summary.status_code == 200, summary.text
    assert "text" in summary.json()

    send = await client.post(
        f"/api/v1/reports/owner-whatsapp-report?target_date={today}",
        headers=auth_headers,
    )
    assert send.status_code == 200, send.text
    assert send.json()["status"] == "sent"

    # extended endpoints smoke
    for path in (
        f"/api/v1/reports/sales-by-channel?start_date={today}&end_date={today}",
        f"/api/v1/reports/sales-by-category?start_date={today}&end_date={today}",
        f"/api/v1/reports/sales-by-waiter?start_date={today}&end_date={today}",
        f"/api/v1/reports/sales-by-payment-method?start_date={today}&end_date={today}",
        f"/api/v1/reports/gross-profit?start_date={today}&end_date={today}",
        f"/api/v1/reports/food-cost?start_date={today}&end_date={today}",
        f"/api/v1/reports/discounts?start_date={today}&end_date={today}",
        f"/api/v1/reports/voids?start_date={today}&end_date={today}",
        f"/api/v1/reports/refunds?start_date={today}&end_date={today}",
        f"/api/v1/reports/wastage?start_date={today}&end_date={today}",
        f"/api/v1/reports/top-selling?start_date={today}&end_date={today}",
        f"/api/v1/reports/slow-moving?start_date={today}&end_date={today}",
        f"/api/v1/reports/dead-menu-items?start_date={today}&end_date={today}",
        f"/api/v1/reports/aov?start_date={today}&end_date={today}",
        f"/api/v1/reports/avg-delivery-time?start_date={today}&end_date={today}",
        f"/api/v1/reports/peak-hours?start_date={today}&end_date={today}",
        f"/api/v1/reports/tax?start_date={today}&end_date={today}",
        "/api/v1/reports/forecasted-sales?horizon=tomorrow",
        f"/api/v1/reports/retention-cohort?start_date={today}&end_date={today}",
        f"/api/v1/reports/export.xlsx?start_date={today}&end_date={today}",
    ):
        r = await client.get(path, headers=auth_headers)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
