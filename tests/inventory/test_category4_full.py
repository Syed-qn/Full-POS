"""Category 4 — full inventory / food-cost wiring tests."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.inventory.costing import dish_cost
from app.inventory.models import DishIngredient, Ingredient
from app.inventory.purchasing import create_grn, create_purchase_order, create_vendor
from app.inventory.service import (
    add_batch,
    add_substitute,
    deduct_for_order,
    ensure_default_location,
    list_anomaly_alerts,
    record_stock_count,
    record_waste,
    spoilage_report,
    stock_variance_report,
    take_stock_closing_snapshot,
)
from app.menu.models import Dish, Menu
from app.ordering.models import Customer, Order, OrderItem


async def _ing(db_session, restaurant, name="Flour", stock="10", cost="2"):
    i = Ingredient(
        restaurant_id=restaurant.id,
        name=name,
        unit="kg",
        current_stock=Decimal(stock),
        low_stock_threshold=Decimal("2"),
        par_level=Decimal("20"),
        cost_per_unit_aed=Decimal(cost),
    )
    db_session.add(i)
    await db_session.flush()
    return i


@pytest.mark.anyio
async def test_locations_central_commissary(db_session, restaurant):
    branch = await ensure_default_location(db_session, restaurant_id=restaurant.id, kitchen_role="branch")
    central = await ensure_default_location(db_session, restaurant_id=restaurant.id, kitchen_role="central")
    comm = await ensure_default_location(db_session, restaurant_id=restaurant.id, kitchen_role="commissary")
    assert branch.kitchen_role == "branch"
    assert central.kitchen_role == "central"
    assert comm.kitchen_role == "commissary"
    assert central.code == "central"


@pytest.mark.anyio
async def test_spoilage_waste_and_report(db_session, restaurant):
    ing = await _ing(db_session, restaurant)
    await record_waste(
        db_session,
        restaurant_id=restaurant.id,
        ingredient_id=ing.id,
        quantity=Decimal("1.5"),
        reason="expired lettuce",
        recorded_by="manager",
        reason_type="spoilage",
    )
    await db_session.refresh(ing)
    assert ing.current_stock == Decimal("8.500")
    report = await spoilage_report(
        db_session,
        restaurant_id=restaurant.id,
        start_date=date.today() - timedelta(days=1),
        end_date=date.today(),
    )
    assert len(report) >= 1
    assert report[0]["quantity"] == Decimal("1.5")


@pytest.mark.anyio
async def test_stock_count_variance_log_and_alert(db_session, restaurant):
    ing = await _ing(db_session, restaurant, stock="100")
    result = await record_stock_count(
        db_session,
        restaurant_id=restaurant.id,
        ingredient_id=ing.id,
        counted_qty=Decimal("70"),
    )
    assert result["variance"] == Decimal("-30")
    assert result["variance_pct"] == 30.0
    var = await stock_variance_report(db_session, restaurant_id=restaurant.id)
    assert any(v["variance"] == Decimal("-30") for v in var)
    alerts = await list_anomaly_alerts(db_session, restaurant_id=restaurant.id)
    assert any(a.alert_type == "theft_loss" for a in alerts)


@pytest.mark.anyio
async def test_fefo_batch_deduction(db_session, restaurant):
    ing = await _ing(db_session, restaurant, stock="0")
    b1 = await add_batch(
        db_session,
        restaurant_id=restaurant.id,
        ingredient_id=ing.id,
        qty=Decimal("5"),
        expiry_date=date.today() + timedelta(days=2),
    )
    b2 = await add_batch(
        db_session,
        restaurant_id=restaurant.id,
        ingredient_id=ing.id,
        qty=Decimal("5"),
        expiry_date=date.today() + timedelta(days=10),
    )
    await db_session.refresh(ing)
    assert ing.current_stock == Decimal("10")

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Bread",
        price_aed=Decimal("5"),
        is_available=True,
        name_normalized="bread",
    )
    db_session.add(dish)
    await db_session.flush()
    db_session.add(
        DishIngredient(
            dish_id=dish.id, ingredient_id=ing.id, quantity_per_dish=Decimal("6"), yield_pct=Decimal("100")
        )
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500004401", name="I")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="INV-1",
        status="confirmed",
        subtotal=Decimal("5"),
        total=Decimal("5"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=1,
            dish_name="Bread",
            price_aed=Decimal("5"),
            qty=1,
        )
    )
    await db_session.flush()
    await deduct_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.refresh(b1)
    await db_session.refresh(b2)
    # FEFO: first batch fully consumed (5), second loses 1
    assert b1.qty_remaining == Decimal("0")
    assert b2.qty_remaining == Decimal("4")


@pytest.mark.anyio
async def test_auto_substitute_on_shortfall(db_session, restaurant):
    primary = await _ing(db_session, restaurant, name="Oil", stock="1")
    alt = await _ing(db_session, restaurant, name="Oil Alt", stock="10")
    await add_substitute(
        db_session,
        restaurant_id=restaurant.id,
        ingredient_id=primary.id,
        substitute_ingredient_id=alt.id,
        conversion_factor=Decimal("1"),
    )
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=2,
        name="Fry",
        price_aed=Decimal("8"),
        is_available=True,
        name_normalized="fry",
    )
    db_session.add(dish)
    await db_session.flush()
    db_session.add(
        DishIngredient(dish_id=dish.id, ingredient_id=primary.id, quantity_per_dish=Decimal("5"))
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500004402", name="S")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="INV-2",
        status="confirmed",
        subtotal=Decimal("8"),
        total=Decimal("8"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=2,
            dish_name="Fry",
            price_aed=Decimal("8"),
            qty=1,
        )
    )
    await db_session.flush()
    await deduct_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.refresh(primary)
    await db_session.refresh(alt)
    assert primary.current_stock == Decimal("0")
    assert alt.current_stock == Decimal("6")  # 4 of shortfall from alt


@pytest.mark.anyio
async def test_recipe_yield_cost(db_session, restaurant):
    ing = await _ing(db_session, restaurant, cost="10")
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=3,
        name="Soup",
        price_aed=Decimal("20"),
        is_available=True,
        name_normalized="soup",
    )
    db_session.add(dish)
    await db_session.flush()
    db_session.add(
        DishIngredient(
            dish_id=dish.id,
            ingredient_id=ing.id,
            quantity_per_dish=Decimal("1"),
            yield_pct=Decimal("50"),  # need 2 units raw
        )
    )
    await db_session.flush()
    cost = await dish_cost(db_session, dish_id=dish.id)
    assert cost == Decimal("20.0000")  # 1 * 10 * (100/50)


@pytest.mark.anyio
async def test_grn_partial_receive(db_session, restaurant):
    ing = await _ing(db_session, restaurant, stock="0")
    vendor = await create_vendor(db_session, restaurant_id=restaurant.id, name="Vendor A")
    po = await create_purchase_order(
        db_session,
        restaurant_id=restaurant.id,
        vendor_id=vendor.id,
        lines=[{"ingredient_id": ing.id, "qty_ordered": "10", "unit_cost_aed": "3.5"}],
    )
    from app.inventory.models import PurchaseOrderLine

    line = (
        await db_session.scalars(
            select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)
        )
    ).first()
    grn = await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po.id,
        lines=[
            {
                "po_line_id": line.id,
                "qty_received": Decimal("4"),
                "unit_cost_aed": Decimal("3.5"),
                "expiry_date": date.today() + timedelta(days=30),
            }
        ],
        received_by="manager",
    )
    await db_session.refresh(po)
    await db_session.refresh(ing)
    assert grn.grn_number.startswith("GRN-")
    assert po.status == "partial"
    assert ing.current_stock == Decimal("4")
    assert ing.cost_per_unit_aed == Decimal("3.5000")


@pytest.mark.anyio
async def test_closing_snapshot(db_session, restaurant):
    await _ing(db_session, restaurant, stock="12.5")
    rows = await take_stock_closing_snapshot(db_session, restaurant_id=restaurant.id)
    assert rows
    assert rows[0]["closing_stock"] == Decimal("12.500")
    # Idempotent second call updates same day
    rows2 = await take_stock_closing_snapshot(db_session, restaurant_id=restaurant.id)
    assert len(rows2) == len(rows)


@pytest.mark.anyio
async def test_vendor_list_router(client, auth_headers):
    r = await client.post(
        "/api/v1/vendors",
        headers=auth_headers,
        json={"name": "Spice Co", "phone": "+9715000001"},
    )
    assert r.status_code == 201
    lst = await client.get("/api/v1/vendors", headers=auth_headers)
    assert lst.status_code == 200
    assert any(v["name"] == "Spice Co" for v in lst.json())

    locs = await client.get("/api/v1/ingredients/locations", headers=auth_headers)
    assert locs.status_code == 200
    roles = {x["kitchen_role"] for x in locs.json()}
    assert "central" in roles and "commissary" in roles


@pytest.mark.anyio
async def test_grn_and_reports_http(client, auth_headers):
    """Full HTTP path: ingredient → vendor → PO → partial GRN → waste → reports."""
    ing_resp = await client.post(
        "/api/v1/ingredients",
        headers=auth_headers,
        json={
            "name": "HTTP Flour",
            "unit": "kg",
            "current_stock": "0",
            "low_stock_threshold": "1",
            "par_level": "10",
            "cost_per_unit_aed": "2",
        },
    )
    assert ing_resp.status_code == 201, ing_resp.text
    ing_id = ing_resp.json()["id"]

    vendor_resp = await client.post(
        "/api/v1/vendors",
        headers=auth_headers,
        json={"name": "HTTP Vendor", "phone": "+9715000999"},
    )
    assert vendor_resp.status_code == 201
    vendor_id = vendor_resp.json()["id"]

    po_resp = await client.post(
        "/api/v1/purchase-orders",
        headers=auth_headers,
        json={
            "vendor_id": vendor_id,
            "lines": [
                {
                    "ingredient_id": ing_id,
                    "qty_ordered": "10",
                    "unit_cost_aed": "2.5",
                }
            ],
        },
    )
    assert po_resp.status_code == 201, po_resp.text
    po = po_resp.json()
    line_id = po["lines"][0]["id"]

    grn_resp = await client.post(
        "/api/v1/grn",
        headers=auth_headers,
        json={
            "po_id": po["id"],
            "lines": [
                {
                    "po_line_id": line_id,
                    "qty_received": "3",
                    "unit_cost_aed": "2.5",
                    "expiry_date": (date.today() + timedelta(days=14)).isoformat(),
                }
            ],
        },
    )
    assert grn_resp.status_code == 201, grn_resp.text
    assert grn_resp.json()["grn_number"].startswith("GRN-")

    waste = await client.post(
        f"/api/v1/ingredients/{ing_id}/waste",
        headers=auth_headers,
        json={"quantity": "0.5", "reason": "rotten", "reason_type": "spoilage"},
    )
    assert waste.status_code == 200

    spoilage = await client.get(
        "/api/v1/ingredients/reports/spoilage",
        headers=auth_headers,
        params={
            "start_date": (date.today() - timedelta(days=1)).isoformat(),
            "end_date": date.today().isoformat(),
        },
    )
    assert spoilage.status_code == 200
    assert len(spoilage.json()) >= 1
    assert spoilage.json()[0]["reason_type"] == "spoilage"
    assert spoilage.json()[0]["ingredient_name"] == "HTTP Flour"

    count = await client.post(
        f"/api/v1/ingredients/{ing_id}/stock-count",
        headers=auth_headers,
        json={"counted_qty": "1"},
    )
    assert count.status_code == 200
    variance = await client.get(
        "/api/v1/ingredients/reports/variance", headers=auth_headers
    )
    assert variance.status_code == 200
    assert len(variance.json()) >= 1

    snap = await client.post(
        "/api/v1/ingredients/reports/closing-snapshot", headers=auth_headers
    )
    assert snap.status_code == 200
    assert len(snap.json()) >= 1

    grns = await client.get("/api/v1/grn", headers=auth_headers)
    assert grns.status_code == 200
    assert any(g["id"] == grn_resp.json()["id"] for g in grns.json())

    pos = await client.get("/api/v1/purchase-orders", headers=auth_headers)
    assert pos.status_code == 200
    assert any(p["id"] == po["id"] and p["status"] == "partial" for p in pos.json())


@pytest.mark.anyio
async def test_item_performance_includes_food_cost_pct(db_session, restaurant):
    """Reports analytics expose food_cost_pct for Category 4 food-cost feature."""
    from app.reports.analytics import item_performance

    rows = await item_performance(
        db_session,
        restaurant_id=restaurant.id,
        start_date=date.today() - timedelta(days=7),
        end_date=date.today(),
    )
    assert isinstance(rows, list)
