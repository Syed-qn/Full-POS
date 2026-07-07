from decimal import Decimal

import pytest

from app.inventory.models import Ingredient
from app.inventory.purchasing import create_purchase_order, create_vendor, receive_purchase_order


@pytest.mark.anyio
async def test_create_vendor(db_session, restaurant):
    vendor = await create_vendor(
        db_session, restaurant_id=restaurant.id, name="Acme Foods", phone="+97150000000", email="a@acme.com",
    )
    assert vendor.id is not None
    assert vendor.name == "Acme Foods"
    assert vendor.restaurant_id == restaurant.id


@pytest.mark.anyio
async def test_create_and_receive_purchase_order_increments_stock(db_session, restaurant):
    vendor = await create_vendor(db_session, restaurant_id=restaurant.id, name="Acme Foods", phone=None, email=None)
    flour = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add(flour)
    await db_session.flush()

    po = await create_purchase_order(
        db_session, restaurant_id=restaurant.id, vendor_id=vendor.id,
        lines=[{"ingredient_id": flour.id, "qty_ordered": Decimal("5.000"), "unit_cost_aed": Decimal("2.5000")}],
    )
    assert po.status == "draft"

    received = await receive_purchase_order(db_session, restaurant_id=restaurant.id, po_id=po.id)
    assert received.status == "received"

    await db_session.refresh(flour)
    assert flour.current_stock == Decimal("15.000")


@pytest.mark.anyio
async def test_receive_purchase_order_wrong_restaurant_raises(db_session, restaurant):
    vendor = await create_vendor(db_session, restaurant_id=restaurant.id, name="Acme Foods", phone=None, email=None)
    flour = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add(flour)
    await db_session.flush()
    po = await create_purchase_order(
        db_session, restaurant_id=restaurant.id, vendor_id=vendor.id,
        lines=[{"ingredient_id": flour.id, "qty_ordered": Decimal("5.000"), "unit_cost_aed": Decimal("2.5000")}],
    )

    with pytest.raises(ValueError):
        await receive_purchase_order(db_session, restaurant_id=restaurant.id + 999, po_id=po.id)


@pytest.mark.anyio
async def test_vendor_and_purchase_order_router(client, auth_headers):
    vendor_resp = await client.post(
        "/api/v1/vendors", json={"name": "Acme Foods", "phone": "+97150000000", "email": "a@acme.com"},
        headers=auth_headers,
    )
    assert vendor_resp.status_code == 201
    vendor_id = vendor_resp.json()["id"]

    ing_resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Sugar", "unit": "kg", "current_stock": "1.000", "low_stock_threshold": "0.500"},
        headers=auth_headers,
    )
    ing_id = ing_resp.json()["id"]

    po_resp = await client.post(
        "/api/v1/purchase-orders",
        json={
            "vendor_id": vendor_id,
            "lines": [{"ingredient_id": ing_id, "qty_ordered": "3.000", "unit_cost_aed": "4.0000"}],
        },
        headers=auth_headers,
    )
    assert po_resp.status_code == 201
    po_id = po_resp.json()["id"]
    assert po_resp.json()["status"] == "draft"

    receive_resp = await client.post(f"/api/v1/purchase-orders/{po_id}/receive", headers=auth_headers)
    assert receive_resp.status_code == 200
    assert receive_resp.json()["status"] == "received"

    ing_after = await client.get("/api/v1/ingredients", headers=auth_headers)
    updated = next(i for i in ing_after.json() if i["id"] == ing_id)
    assert updated["current_stock"] == "4.000"
