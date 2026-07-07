from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_create_group_and_modifier_via_router(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Sandwich",
        price_aed=Decimal("18.00"), is_available=True, name_normalized="sandwich",
    )
    db_session.add(dish)
    await db_session.commit()

    group_resp = await client.post(
        f"/api/v1/dishes/{dish.id}/modifier-groups",
        json={"name": "Bread Type", "min_select": 1, "max_select": 1, "required": True},
        headers=auth_headers,
    )
    assert group_resp.status_code == 201
    group_id = group_resp.json()["id"]

    mod_resp = await client.post(
        f"/api/v1/modifier-groups/{group_id}/modifiers",
        json={"name": "Whole Wheat", "price_delta_aed": "0.00"},
        headers=auth_headers,
    )
    assert mod_resp.status_code == 201

    listing = await client.get(f"/api/v1/dishes/{dish.id}/modifier-groups", headers=auth_headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1
