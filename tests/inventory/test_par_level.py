from decimal import Decimal

import pytest

from app.inventory.models import Ingredient
from app.inventory.service import suggest_reorder_quantities


@pytest.mark.anyio
async def test_suggest_reorder_quantities_includes_only_below_threshold(db_session, restaurant):
    low = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("1.000"), low_stock_threshold=Decimal("5.000"),
        par_level=Decimal("20.000"),
    )
    ok = Ingredient(
        restaurant_id=restaurant.id, name="Sugar", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("5.000"),
        par_level=Decimal("20.000"),
    )
    db_session.add_all([low, ok])
    await db_session.flush()

    suggestions = await suggest_reorder_quantities(db_session, restaurant_id=restaurant.id)

    assert len(suggestions) == 1
    row = suggestions[0]
    assert row["ingredient_id"] == low.id
    assert row["ingredient_name"] == "Flour"
    assert row["current_stock"] == Decimal("1.000")
    assert row["par_level"] == Decimal("20.000")
    assert row["suggested_order_qty"] == Decimal("19.000")


@pytest.mark.anyio
async def test_reorder_suggestions_router(client, auth_headers):
    resp = await client.post(
        "/api/v1/ingredients",
        json={
            "name": "Rice", "unit": "kg", "current_stock": "1.000",
            "low_stock_threshold": "5.000", "par_level": "20.000",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201

    reorder_resp = await client.get("/api/v1/ingredients/reorder-suggestions", headers=auth_headers)
    assert reorder_resp.status_code == 200
    body = reorder_resp.json()
    assert any(r["ingredient_name"] == "Rice" for r in body)
    row = next(r for r in body if r["ingredient_name"] == "Rice")
    assert row["suggested_order_qty"] == "19.000"
