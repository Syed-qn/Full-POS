from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant
from app.inventory.models import Ingredient
from app.inventory.purchasing import create_purchase_order, create_vendor
from app.outbox.models import OutboxMessage


async def _auth_restaurant(db_session):
    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


@pytest.mark.anyio
async def test_vendor_price_comparison_router(client, auth_headers, db_session):
    restaurant = await _auth_restaurant(db_session)
    ingredient = Ingredient(
        restaurant_id=restaurant.id,
        name="Tomato",
        unit="kg",
        current_stock=Decimal("3.000"),
        cost_per_unit_aed=Decimal("2.0000"),
    )
    db_session.add(ingredient)
    await db_session.flush()
    vendor = await create_vendor(
        db_session, restaurant_id=restaurant.id, name="Fresh Vendor",
    )
    await create_purchase_order(
        db_session,
        restaurant_id=restaurant.id,
        vendor_id=vendor.id,
        lines=[{
            "ingredient_id": ingredient.id,
            "qty_ordered": "2.000",
            "unit_cost_aed": "2.7500",
        }],
    )
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/ingredients/{ingredient.id}/vendor-price-comparison",
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()[0]["vendor_name"] == "Fresh Vendor"
    assert resp.json()[0]["unit_cost_aed"] == "2.7500"


@pytest.mark.anyio
async def test_stock_adjustment_router_request_and_approve(client, auth_headers):
    ingredient_resp = await client.post(
        "/api/v1/ingredients",
        json={
            "name": "Flour",
            "unit": "kg",
            "current_stock": "5.000",
            "cost_per_unit_aed": "1.0000",
        },
        headers=auth_headers,
    )
    assert ingredient_resp.status_code == 201
    ingredient_id = ingredient_resp.json()["id"]

    request = await client.post(
        f"/api/v1/ingredients/{ingredient_id}/stock-adjustments",
        json={"requested_qty": "8.000", "reason": "closing count", "requested_by": "cashier"},
        headers=auth_headers,
    )
    assert request.status_code == 201
    body = request.json()
    assert body["status"] == "pending"
    assert body["previous_qty_snapshot"] == "5.000"

    listing = await client.get(
        "/api/v1/ingredients/stock-adjustments?status=pending",
        headers=auth_headers,
    )
    assert listing.status_code == 200
    assert any(row["id"] == body["id"] for row in listing.json())

    approved = await client.post(
        f"/api/v1/ingredients/stock-adjustments/{body['id']}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    ingredients = await client.get("/api/v1/ingredients", headers=auth_headers)
    row = next(item for item in ingredients.json() if item["id"] == ingredient_id)
    assert row["current_stock"] == "8.000"


@pytest.mark.anyio
async def test_low_stock_alert_router_is_idempotent(client, auth_headers, db_session):
    restaurant = await _auth_restaurant(db_session)
    restaurant.phone = "+971500009999"
    db_session.add(Ingredient(
        restaurant_id=restaurant.id,
        name="Mint",
        unit="bunch",
        current_stock=Decimal("1.000"),
        low_stock_threshold=Decimal("2.000"),
        cost_per_unit_aed=Decimal("0.5000"),
    ))
    await db_session.commit()

    first = await client.post("/api/v1/ingredients/low-stock-alert", headers=auth_headers)
    second = await client.post("/api/v1/ingredients/low-stock-alert", headers=auth_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["enqueued"] is True
    rows = (await db_session.scalars(select(OutboxMessage))).all()
    assert len(rows) == 1
