from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.inventory.models import Ingredient
from app.inventory.service import add_batch, list_expiring_soon


@pytest.mark.anyio
async def test_add_batch_and_list_expiring_soon(db_session, restaurant):
    flour = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add(flour)
    await db_session.flush()

    soon = await add_batch(
        db_session, restaurant_id=restaurant.id, ingredient_id=flour.id,
        qty=Decimal("5.000"), expiry_date=date.today() + timedelta(days=2),
    )
    far = await add_batch(
        db_session, restaurant_id=restaurant.id, ingredient_id=flour.id,
        qty=Decimal("5.000"), expiry_date=date.today() + timedelta(days=30),
    )
    assert soon.id is not None
    assert far.id is not None

    expiring = await list_expiring_soon(db_session, restaurant_id=restaurant.id, within_days=3)
    ids = [b.id for b in expiring]
    assert soon.id in ids
    assert far.id not in ids


@pytest.mark.anyio
async def test_batch_router(client, auth_headers):
    ing_resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Milk", "unit": "l", "current_stock": "10.000", "low_stock_threshold": "2.000"},
        headers=auth_headers,
    )
    ing_id = ing_resp.json()["id"]

    expiry = (date.today() + timedelta(days=1)).isoformat()
    resp = await client.post(
        f"/api/v1/ingredients/{ing_id}/batches",
        json={"qty": "3.000", "expiry_date": expiry},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["ingredient_id"] == ing_id

    listing = await client.get("/api/v1/ingredients/expiring-soon?within_days=3", headers=auth_headers)
    assert listing.status_code == 200
    assert any(b["ingredient_id"] == ing_id for b in listing.json())
