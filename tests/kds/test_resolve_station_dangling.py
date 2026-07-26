"""A category wired to a station that no longer exists must NOT crash order
confirmation. resolve_station should fall back to Main instead of returning a
dangling id that then blows up ticket/print-job creation with an FK error."""

from decimal import Decimal

import pytest


async def _restaurant(db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


@pytest.mark.anyio
async def test_confirm_survives_dangling_category_default(client, auth_headers, db_session):
    from app.kds.models import CategoryStationDefault
    from app.menu.models import Dish, Menu

    from app.kds.models import KitchenStation

    restaurant = await _restaurant(db_session)
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=120, name="Combo",
        price_aed=Decimal("17.00"), category="Combo Sandwich", is_available=True,
        name_normalized="combo",
    )
    bev = KitchenStation(restaurant_id=restaurant.id, name="Beverage", station_type="beverage")
    db_session.add_all([dish, bev])
    await db_session.flush()
    db_session.add(
        CategoryStationDefault(
            restaurant_id=restaurant.id, category="Combo Sandwich", station_id=bev.id
        )
    )
    await db_session.commit()

    # Takeaway KOT (auto_confirm=True) must succeed, not 500.
    resp = await client.post(
        "/api/v1/orders/pos",
        json={
            "order_type": "takeaway",
            "customer_phone": "0565594403",
            "customer_name": "Asfer",
            "items": [{"dish_id": dish.id, "qty": 1}],
            "auto_confirm": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
