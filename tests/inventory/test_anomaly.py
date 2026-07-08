from decimal import Decimal

import pytest

from app.inventory.models import Ingredient
from app.inventory.service import flag_stock_anomaly


@pytest.mark.anyio
async def test_flag_stock_anomaly_over_threshold_returns_result(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id, name="Chicken", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add(ingredient)
    await db_session.flush()

    result = await flag_stock_anomaly(
        db_session, restaurant_id=restaurant.id, ingredient_id=ingredient.id,
        expected_qty=Decimal("10.000"), actual_qty=Decimal("8.000"),
    )

    assert result is not None
    assert result["ingredient_id"] == ingredient.id
    assert result["expected_qty"] == Decimal("10.000")
    assert result["actual_qty"] == Decimal("8.000")
    assert result["variance_pct"] == pytest.approx(20.0)


@pytest.mark.anyio
async def test_flag_stock_anomaly_under_threshold_returns_none(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id, name="Chicken", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add(ingredient)
    await db_session.flush()

    result = await flag_stock_anomaly(
        db_session, restaurant_id=restaurant.id, ingredient_id=ingredient.id,
        expected_qty=Decimal("10.000"), actual_qty=Decimal("9.500"),
    )

    assert result is None


@pytest.mark.anyio
async def test_check_anomaly_router(client, auth_headers):
    resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Beef", "unit": "kg", "current_stock": "10.000", "low_stock_threshold": "2.000"},
        headers=auth_headers,
    )
    ingredient_id = resp.json()["id"]

    anomaly_resp = await client.post(
        f"/api/v1/ingredients/{ingredient_id}/check-anomaly",
        json={"expected_qty": "10.000", "actual_qty": "5.000"},
        headers=auth_headers,
    )
    assert anomaly_resp.status_code == 200
    body = anomaly_resp.json()
    assert body["variance_pct"] == pytest.approx(50.0)


@pytest.mark.anyio
async def test_check_anomaly_router_no_anomaly_returns_null(client, auth_headers):
    resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Salt", "unit": "kg", "current_stock": "10.000", "low_stock_threshold": "2.000"},
        headers=auth_headers,
    )
    ingredient_id = resp.json()["id"]

    anomaly_resp = await client.post(
        f"/api/v1/ingredients/{ingredient_id}/check-anomaly",
        json={"expected_qty": "10.000", "actual_qty": "9.900"},
        headers=auth_headers,
    )
    assert anomaly_resp.status_code == 200
    assert anomaly_resp.json() is None
