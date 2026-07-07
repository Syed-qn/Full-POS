from decimal import Decimal

import pytest
from sqlalchemy import select


async def _second_restaurant_headers(client):
    signup = {
        "name": "Other Restaurant", "email": "owner2@other.ae",
        "phone": "+971509999999", "password": "hunter2!", "lat": 25.1, "lng": 55.1,
    }
    await client.post("/api/v1/auth/signup", json=signup)
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "owner2@other.ae", "password": "hunter2!"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.anyio
async def test_bump_rejects_other_tenants_item(client, auth_headers, db_session):
    from app.identity.models import Restaurant
    from app.kds.models import KitchenStation
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    station = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    db_session.add(station)
    await db_session.flush()
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), category="Grills", is_available=True,
        name_normalized="kebab", station_id=station.id,
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000097", name="Tenant A")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="TA-0001",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=1, kitchen_status="received", station_id_snapshot=station.id,
    )
    db_session.add(item)
    await db_session.commit()

    other_headers = await _second_restaurant_headers(client)
    resp = await client.patch(f"/api/v1/kds/items/{item.id}/bump", headers=other_headers)
    assert resp.status_code == 404

    resp2 = await client.get(f"/api/v1/kds/stations/{station.id}/tickets", headers=other_headers)
    assert resp2.status_code == 404
