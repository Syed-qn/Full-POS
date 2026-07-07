from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_create_station_and_list(client, auth_headers):
    resp = await client.post(
        "/api/v1/kds/stations", json={"name": "Grill"}, headers=auth_headers,
    )
    assert resp.status_code == 201
    station_id = resp.json()["id"]

    listing = await client.get("/api/v1/kds/stations", headers=auth_headers)
    assert listing.status_code == 200
    assert any(s["id"] == station_id for s in listing.json())


@pytest.mark.anyio
async def test_bump_then_recall_item(client, auth_headers, db_session):
    from sqlalchemy import select

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
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000098", name="Test2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="T-0002",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=1, kitchen_status="received",
        station_id_snapshot=station.id,
    )
    db_session.add(item)
    await db_session.commit()

    bump = await client.patch(f"/api/v1/kds/items/{item.id}/bump", headers=auth_headers)
    assert bump.status_code == 200
    assert bump.json()["kitchen_status"] == "ready"

    tickets = await client.get(
        f"/api/v1/kds/stations/{station.id}/tickets", headers=auth_headers
    )
    assert all(t["id"] != item.id for t in tickets.json())  # bumped item no longer "active"

    recall = await client.patch(f"/api/v1/kds/items/{item.id}/recall", headers=auth_headers)
    assert recall.status_code == 200
    assert recall.json()["kitchen_status"] == "received"
