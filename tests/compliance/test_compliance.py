"""Category 13 — UAE compliance full stack tests."""

from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_apply_vat_inclusive_extracts_tax():
    from app.ordering.models import Order
    from app.ordering.tax import apply_vat, vat_from_inclusive

    net, vat = vat_from_inclusive(Decimal("105.00"), Decimal("0.05"))
    assert net == Decimal("100.00")
    assert vat == Decimal("5.00")

    order = Order(subtotal=Decimal("105.00"), total=Decimal("105.00"))
    apply_vat(order, vat_rate=Decimal("0.05"), pricing_mode="inclusive")
    assert order.vat_amount_aed == Decimal("5.00")
    assert order.tax_pricing_mode == "inclusive"


@pytest.mark.anyio
async def test_resolve_invoice_kind_b2b_and_threshold():
    from app.ordering.tax import resolve_invoice_kind

    assert (
        resolve_invoice_kind(
            total_aed=Decimal("50"),
            buyer_trn="100123456700003",
            threshold=Decimal("10000"),
        )
        == "tax_invoice"
    )
    assert (
        resolve_invoice_kind(
            total_aed=Decimal("50"),
            buyer_trn=None,
            threshold=Decimal("10000"),
        )
        == "simplified_tax_invoice"
    )
    assert (
        resolve_invoice_kind(
            total_aed=Decimal("15000"),
            buyer_trn=None,
            threshold=Decimal("10000"),
        )
        == "tax_invoice"
    )


@pytest.mark.anyio
async def test_tax_settings_endpoint(client, auth_headers, db_session):
    resp = await client.get("/api/v1/compliance/tax-settings", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tax_pricing_mode"] in ("exclusive", "inclusive")
    assert "default_vat_rate" in body

    patch = await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={
            "trn": "100123456700003",
            "legal_name": "Biryani House LLC",
            "legal_name_ar": "بيت البرياني",
            "tax_pricing_mode": "inclusive",
            "e_invoice_enabled": True,
        },
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["trn"] == "100123456700003"
    assert patch.json()["tax_pricing_mode"] == "inclusive"
    assert patch.json()["e_invoice_enabled"] is True


@pytest.mark.anyio
async def test_invoice_simplified_vs_full_and_vat_breakdown(
    client, auth_headers, db_session
):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    restaurant.settings = {
        **(restaurant.settings or {}),
        "trn": "100123456700003",
        "legal_name": "Biryani House LLC",
    }
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Kebab",
        price_aed=Decimal("100.00"),
        is_available=True,
        name_normalized="kebab",
        vat_rate=Decimal("0.0500"),
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009913", name="C13")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C13-0001",
        status="confirmed",
        subtotal=Decimal("100.00"),
        total=Decimal("105.00"),
        vat_rate=Decimal("0.0500"),
        vat_amount_aed=Decimal("5.00"),
        invoice_kind="simplified_tax_invoice",
        tax_pricing_mode="exclusive",
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=1,
            dish_name="Kebab",
            price_aed=Decimal("100.00"),
            qty=1,
            vat_rate=Decimal("0.0500"),
            vat_amount_aed=Decimal("5.00"),
        )
    )
    await db_session.commit()

    simple = await client.get(
        f"/api/v1/compliance/invoices/{order.id}", headers=auth_headers
    )
    assert simple.status_code == 200
    assert simple.json()["document_type"] == "simplified_tax_invoice"
    assert simple.json()["simplified"] is True
    assert simple.json()["trn"] == "100123456700003"
    assert "vat_breakdown" in simple.json()
    assert simple.json()["labels_ar"]["title"]
    assert simple.json()["branch_trn"] == "100123456700003"

    full = await client.get(
        f"/api/v1/compliance/invoices/{order.id}?document_type=tax_invoice&buyer_trn=200999888700003",
        headers=auth_headers,
    )
    assert full.status_code == 200
    assert full.json()["document_type"] == "tax_invoice"
    assert full.json()["simplified"] is False
    assert full.json()["buyer"]["trn"] == "200999888700003"

    structured = await client.get(
        f"/api/v1/compliance/invoices/{order.id}/structured", headers=auth_headers
    )
    assert structured.status_code == 200
    assert structured.json()["profile"] == "PINT-AE-JSON-v1"
    assert structured.json()["seller"]["trn"] == "100123456700003"


@pytest.mark.anyio
async def test_refund_note_issue_and_list(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009914", name="RN")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C13-RN-1",
        status="delivered",
        subtotal=Decimal("50.00"),
        total=Decimal("52.50"),
        vat_amount_aed=Decimal("2.50"),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/compliance/refund-notes",
        headers=auth_headers,
        json={
            "order_id": order.id,
            "amount_aed": "52.50",
            "reason": "customer return",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["refund_note_number"].startswith("RN-")
    assert body["amount_aed"] == "52.50"

    listed = await client.get("/api/v1/compliance/refund-notes", headers=auth_headers)
    assert listed.status_code == 200
    assert any(n["id"] == body["id"] for n in listed.json())

    doc = await client.get(
        f"/api/v1/compliance/refund-notes/{body['id']}", headers=auth_headers
    )
    assert doc.status_code == 200
    assert doc.json()["document_type"] == "refund_note"
    assert doc.json()["labels_ar"]["title"]


@pytest.mark.anyio
async def test_einvoice_readiness_and_transmit(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    restaurant.settings = {
        **(restaurant.settings or {}),
        "trn": "100123456700003",
        "legal_name": "Biryani House LLC",
        "e_invoice_enabled": True,
        "asp_provider": "mock",
    }
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=2,
        name="Rice",
        price_aed=Decimal("20.00"),
        is_available=True,
        name_normalized="rice",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009915", name="EI")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C13-EI-1",
        status="confirmed",
        subtotal=Decimal("20.00"),
        total=Decimal("21.00"),
        vat_rate=Decimal("0.05"),
        vat_amount_aed=Decimal("1.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=2,
            dish_name="Rice",
            price_aed=Decimal("20.00"),
            qty=1,
        )
    )
    await db_session.commit()

    ready = await client.get(
        "/api/v1/compliance/e-invoice/readiness", headers=auth_headers
    )
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert ready.json()["structured_profile"] == "PINT-AE-JSON-v1"

    tx = await client.post(
        "/api/v1/compliance/e-invoice/transmit",
        headers=auth_headers,
        json={"order_id": order.id},
    )
    assert tx.status_code == 201, tx.text
    assert tx.json()["status"] == "accepted"
    assert tx.json()["external_id"]
    assert tx.json()["asp_provider"] == "mock"

    listed = await client.get(
        "/api/v1/compliance/e-invoice/transmissions", headers=auth_headers
    )
    assert listed.status_code == 200
    assert any(r["order_id"] == order.id for r in listed.json())


@pytest.mark.anyio
async def test_retention_and_accountant_export(client, auth_headers, db_session):
    dry = await client.post(
        "/api/v1/compliance/retention/run",
        headers=auth_headers,
        json={"dry_run": True, "retention_days": 90},
    )
    assert dry.status_code == 200, dry.text
    assert dry.json()["status"] == "dry_run"
    assert "purged_counts" in dry.json()

    runs = await client.get("/api/v1/compliance/retention/runs", headers=auth_headers)
    assert runs.status_code == 200
    assert len(runs.json()) >= 1

    exp = await client.get(
        "/api/v1/compliance/accountant-export?start_date=2020-01-01&end_date=2030-12-31&format=json",
        headers=auth_headers,
    )
    assert exp.status_code == 200, exp.text
    assert exp.json()["export_type"] == "accountant_pack"
    assert "summary" in exp.json()
    assert "orders" in exp.json()

    csv_exp = await client.get(
        "/api/v1/compliance/accountant-export?start_date=2020-01-01&end_date=2030-12-31&format=csv",
        headers=auth_headers,
    )
    assert csv_exp.status_code == 200
    assert "csv" in csv_exp.json()
    assert "order_number" in csv_exp.json()["csv"]


@pytest.mark.anyio
async def test_apply_order_vat_from_settings_multi_rate(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem
    from app.ordering.tax import apply_order_vat_from_settings

    restaurant.settings = {
        **(restaurant.settings or {}),
        "tax_pricing_mode": "exclusive",
        "default_vat_rate": "0.05",
    }
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    d1 = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=10,
        name="Std",
        price_aed=Decimal("100.00"),
        is_available=True,
        name_normalized="std",
    )
    d2 = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=11,
        name="Zero",
        price_aed=Decimal("50.00"),
        is_available=True,
        name_normalized="zero",
        vat_rate=Decimal("0.0000"),
    )
    db_session.add_all([d1, d2])
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009916", name="MR")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C13-MR-1",
        status="pending_confirmation",
        subtotal=Decimal("150.00"),
        total=Decimal("150.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add_all(
        [
            OrderItem(
                order_id=order.id,
                dish_id=d1.id,
                dish_number=10,
                dish_name="Std",
                price_aed=Decimal("100.00"),
                qty=1,
            ),
            OrderItem(
                order_id=order.id,
                dish_id=d2.id,
                dish_number=11,
                dish_name="Zero",
                price_aed=Decimal("50.00"),
                qty=1,
            ),
        ]
    )
    await db_session.flush()

    await apply_order_vat_from_settings(db_session, order=order, restaurant=restaurant)
    await db_session.commit()
    await db_session.refresh(order)
    # 5% of 100 + 0% of 50 = 5.00
    assert order.vat_amount_aed == Decimal("5.00")
    assert order.tax_pricing_mode == "exclusive"
    assert order.invoice_kind in ("simplified_tax_invoice", "tax_invoice")
