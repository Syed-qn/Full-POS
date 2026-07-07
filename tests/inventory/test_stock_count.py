from decimal import Decimal

import pytest

from app.inventory.models import Ingredient
from app.inventory.service import record_stock_count


@pytest.mark.anyio
async def test_record_stock_count_positive_variance(db_session, restaurant):
    flour = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add(flour)
    await db_session.flush()

    result = await record_stock_count(
        db_session, restaurant_id=restaurant.id, ingredient_id=flour.id, counted_qty=Decimal("12.000"),
    )
    assert result["variance"] == Decimal("2.000")
    assert result["previous_stock"] == Decimal("10.000")
    assert result["counted_stock"] == Decimal("12.000")

    await db_session.refresh(flour)
    assert flour.current_stock == Decimal("12.000")


@pytest.mark.anyio
async def test_record_stock_count_negative_variance(db_session, restaurant):
    flour = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add(flour)
    await db_session.flush()

    result = await record_stock_count(
        db_session, restaurant_id=restaurant.id, ingredient_id=flour.id, counted_qty=Decimal("7.000"),
    )
    assert result["variance"] == Decimal("-3.000")


@pytest.mark.anyio
async def test_stock_count_router(client, auth_headers):
    ing_resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Rice", "unit": "kg", "current_stock": "20.000", "low_stock_threshold": "2.000"},
        headers=auth_headers,
    )
    ing_id = ing_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/ingredients/{ing_id}/stock-count", json={"counted_qty": "18.000"}, headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["variance"] == "-2.000"
    assert body["previous_stock"] == "20.000"
    assert body["counted_stock"] == "18.000"

    listing = await client.get("/api/v1/ingredients", headers=auth_headers)
    updated = next(i for i in listing.json() if i["id"] == ing_id)
    assert updated["current_stock"] == "18.000"
