from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant


@pytest.mark.anyio
async def test_create_and_list_combos_via_router(client, auth_headers, db_session):
    from app.menu.models import Dish, Menu

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    burger = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Burger",
        price_aed=Decimal("18.00"), is_available=True, name_normalized="burger",
    )
    fries = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Fries",
        price_aed=Decimal("9.00"), is_available=True, name_normalized="fries",
    )
    db_session.add_all([burger, fries])
    await db_session.commit()

    create_resp = await client.post(
        "/api/v1/combos",
        json={
            "name": "Burger Meal",
            "price_aed": "22.00",
            "dish_ids": [burger.id, fries.id],
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    assert body["name"] == "Burger Meal"
    assert body["price_aed"] == "22.00"
    assert set(body["dish_ids"]) == {burger.id, fries.id}

    list_resp = await client.get("/api/v1/combos", headers=auth_headers)
    assert list_resp.status_code == 200
    names = {c["name"] for c in list_resp.json()}
    assert "Burger Meal" in names
