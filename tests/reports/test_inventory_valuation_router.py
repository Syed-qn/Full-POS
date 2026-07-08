from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant
from app.inventory.models import Ingredient


@pytest.mark.anyio
async def test_inventory_valuation_router(client, auth_headers, db_session):
    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    db_session.add_all([
        Ingredient(
            restaurant_id=restaurant.id,
            name="Rice",
            unit="kg",
            current_stock=Decimal("5.000"),
            cost_per_unit_aed=Decimal("4.0000"),
        ),
        Ingredient(
            restaurant_id=restaurant.id,
            name="Oil",
            unit="L",
            current_stock=Decimal("2.000"),
            cost_per_unit_aed=Decimal("8.5000"),
        ),
    ])
    await db_session.commit()

    resp = await client.get("/api/v1/reports/inventory-valuation", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_value_aed"] == "37.00"
    assert [row["ingredient_name"] for row in body["rows"]] == ["Rice", "Oil"]
