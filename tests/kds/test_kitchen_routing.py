"""Multiple kitchens: station CRUD, category wiring, and the routing precedence
(dish override -> category default -> Main fallback)."""

from decimal import Decimal

import pytest


async def _restaurant(db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


async def _dish(db_session, restaurant, *, number, category, station_id=None):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant.id, version=number, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=number,
        name=f"Dish {number}", price_aed=Decimal("10.00"), category=category,
        is_available=True, name_normalized=f"dish{number}", station_id=station_id,
    )
    db_session.add(dish)
    await db_session.flush()
    return dish


@pytest.mark.anyio
async def test_resolve_station_precedence(client, auth_headers, db_session):
    """dish override wins; else category default; else Main fallback."""
    from app.kds.models import CategoryStationDefault, KitchenStation
    from app.kds.service import resolve_station

    restaurant = await _restaurant(db_session)
    juice = KitchenStation(restaurant_id=restaurant.id, name="Juice", station_type="beverage")
    grill = KitchenStation(restaurant_id=restaurant.id, name="Grill", station_type="grill")
    db_session.add_all([juice, grill])
    await db_session.flush()
    db_session.add(
        CategoryStationDefault(restaurant_id=restaurant.id, category="Fresh Juice", station_id=juice.id)
    )
    await db_session.flush()

    # 1) dish override -> its own station (grill), even though category maps to juice
    d_override = await _dish(db_session, restaurant, number=1, category="Fresh Juice", station_id=grill.id)
    assert await resolve_station(db_session, restaurant_id=restaurant.id, dish=d_override) == grill.id

    # 2) no override, category wired -> juice
    d_cat = await _dish(db_session, restaurant, number=2, category="Fresh Juice")
    assert await resolve_station(db_session, restaurant_id=restaurant.id, dish=d_cat) == juice.id

    # 3) no override, category not wired -> Main (auto-created)
    d_main = await _dish(db_session, restaurant, number=3, category="Burgers")
    main_id = await resolve_station(db_session, restaurant_id=restaurant.id, dish=d_main)
    main = await db_session.get(KitchenStation, main_id)
    assert main.name == "Main"


@pytest.mark.anyio
async def test_delete_kitchen_rehomes_to_main(client, auth_headers, db_session):
    """Deleting a kitchen drops its category wirings, clears dish overrides, and
    moves in-flight tickets to Main. Main itself cannot be deleted."""
    from app.kds.models import CategoryStationDefault, KitchenStation
    from app.kds.service import get_or_create_main_station
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await _restaurant(db_session)
    main = await get_or_create_main_station(db_session, restaurant_id=restaurant.id)
    juice = KitchenStation(restaurant_id=restaurant.id, name="Juice", station_type="beverage")
    db_session.add(juice)
    await db_session.flush()
    db_session.add(
        CategoryStationDefault(restaurant_id=restaurant.id, category="Fresh Juice", station_id=juice.id)
    )
    dish = await _dish(db_session, restaurant, number=5, category="Fresh Juice", station_id=juice.id)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000123", name="T")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="KR-0001",
        status="preparing", subtotal=Decimal("10.00"), total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=5, dish_name="Dish 5",
        price_aed=Decimal("10.00"), qty=1, kitchen_status="received",
        station_id_snapshot=juice.id,
    )
    db_session.add(item)
    await db_session.commit()

    # Main is protected.
    blocked = await client.delete(f"/api/v1/kds/stations/{main.id}", headers=auth_headers)
    assert blocked.status_code == 409

    # Delete Juice -> everything re-homes to Main.
    resp = await client.delete(f"/api/v1/kds/stations/{juice.id}", headers=auth_headers)
    assert resp.status_code == 204

    await db_session.refresh(dish)
    await db_session.refresh(item)
    assert dish.station_id is None                    # override cleared
    assert item.station_id_snapshot == main.id        # ticket moved to Main
    wiring = await client.get("/api/v1/kds/category-defaults", headers=auth_headers)
    assert all(w["category"] != "Fresh Juice" for w in wiring.json())  # wiring dropped


@pytest.mark.anyio
async def test_unwire_category(client, auth_headers, db_session):
    from app.kds.models import KitchenStation

    restaurant = await _restaurant(db_session)
    juice = KitchenStation(restaurant_id=restaurant.id, name="Juice", station_type="beverage")
    db_session.add(juice)
    await db_session.commit()

    wire = await client.post(
        "/api/v1/kds/category-defaults",
        json={"category": "Fresh Juice", "station_id": juice.id},
        headers=auth_headers,
    )
    assert wire.status_code == 201
    unwire = await client.delete(
        "/api/v1/kds/category-defaults/Fresh%20Juice", headers=auth_headers
    )
    assert unwire.status_code == 204
    listing = await client.get("/api/v1/kds/category-defaults", headers=auth_headers)
    assert listing.json() == []
