from decimal import Decimal

import pytest

from app.inventory.models import Ingredient
from app.inventory.service import add_substitute, list_substitutes


@pytest.mark.anyio
async def test_add_and_list_substitutes(db_session, restaurant):
    primary = Ingredient(
        restaurant_id=restaurant.id, name="Butter", unit="kg",
        current_stock=Decimal("5.000"), low_stock_threshold=Decimal("1.000"),
    )
    sub = Ingredient(
        restaurant_id=restaurant.id, name="Margarine", unit="kg",
        current_stock=Decimal("5.000"), low_stock_threshold=Decimal("1.000"),
    )
    db_session.add_all([primary, sub])
    await db_session.flush()

    created = await add_substitute(
        db_session, restaurant_id=restaurant.id, ingredient_id=primary.id,
        substitute_ingredient_id=sub.id, notes="1:1 ratio",
    )
    assert created.id is not None
    assert created.ingredient_id == primary.id
    assert created.substitute_ingredient_id == sub.id
    assert created.notes == "1:1 ratio"

    subs = await list_substitutes(db_session, restaurant_id=restaurant.id, ingredient_id=primary.id)
    assert len(subs) == 1
    assert subs[0].substitute_ingredient_id == sub.id


@pytest.mark.anyio
async def test_substitutes_router(client, auth_headers):
    primary_resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Cream", "unit": "L", "current_stock": "5.000", "low_stock_threshold": "1.000"},
        headers=auth_headers,
    )
    primary_id = primary_resp.json()["id"]

    sub_resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Milk", "unit": "L", "current_stock": "5.000", "low_stock_threshold": "1.000"},
        headers=auth_headers,
    )
    sub_id = sub_resp.json()["id"]

    create_resp = await client.post(
        f"/api/v1/ingredients/{primary_id}/substitutes",
        json={"substitute_ingredient_id": sub_id, "notes": "reduce liquid"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["substitute_ingredient_id"] == sub_id

    list_resp = await client.get(f"/api/v1/ingredients/{primary_id}/substitutes", headers=auth_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["notes"] == "reduce liquid"
