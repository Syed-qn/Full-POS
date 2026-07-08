from datetime import date
from decimal import Decimal

import pytest

from app.inventory.models import Ingredient
from app.inventory.service import daily_stock_closing


@pytest.mark.anyio
async def test_daily_stock_closing_returns_current_stock(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id, name="Tomato", unit="kg",
        current_stock=Decimal("7.500"), low_stock_threshold=Decimal("1.000"),
    )
    db_session.add(ingredient)
    await db_session.flush()

    rows = await daily_stock_closing(db_session, restaurant_id=restaurant.id, target_date=date.today())

    assert len(rows) == 1
    row = rows[0]
    assert row["ingredient_id"] == ingredient.id
    assert row["ingredient_name"] == "Tomato"
    assert row["closing_stock"] == Decimal("7.500")
    assert row["unit"] == "kg"


@pytest.mark.anyio
async def test_daily_stock_closing_router(client, auth_headers):
    await client.post(
        "/api/v1/ingredients",
        json={"name": "Onion", "unit": "kg", "current_stock": "3.000", "low_stock_threshold": "1.000"},
        headers=auth_headers,
    )

    resp = await client.get(
        "/api/v1/reports/daily-stock-closing", params={"target_date": str(date.today())},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(r["ingredient_name"] == "Onion" for r in body)
