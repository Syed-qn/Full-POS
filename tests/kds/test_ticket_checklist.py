from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant
from app.kds.models import KitchenStation
from app.menu.models import Dish, Menu
from app.ordering.models import Customer, Order
from app.ordering.service import add_item


async def _setup_order_with_dish(db_session, *, allergens=None):
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
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Peanut Satay",
        price_aed=Decimal("20.00"), category="Grills", is_available=True,
        name_normalized="peanut satay", station_id=station.id,
        allergens=allergens if allergens is not None else ["nuts", "dairy"],
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000099", name="Checklist Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="T-0099",
        status="confirmed", subtotal=Decimal("0.00"), total=Decimal("0.00"),
    )
    db_session.add(order)
    await db_session.flush()
    return restaurant, station, dish, order


@pytest.mark.anyio
async def test_add_item_snapshots_allergens(client, auth_headers, db_session):
    restaurant, station, dish, order = await _setup_order_with_dish(db_session)
    item = await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.commit()
    await db_session.refresh(item)
    assert item.allergens_snapshot == ["nuts", "dairy"]


@pytest.mark.anyio
async def test_add_item_snapshots_empty_allergens_when_dish_has_none(client, auth_headers, db_session):
    restaurant, station, dish, order = await _setup_order_with_dish(db_session, allergens=[])
    item = await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.commit()
    await db_session.refresh(item)
    assert item.allergens_snapshot == []


@pytest.mark.anyio
async def test_mark_packaging_checked_service(client, auth_headers, db_session):
    from app.kds.service import mark_packaging_checked

    restaurant, station, dish, order = await _setup_order_with_dish(db_session)
    item = await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.commit()

    updated = await mark_packaging_checked(
        db_session, restaurant_id=restaurant.id, order_item_id=item.id
    )
    await db_session.commit()
    assert updated.packaging_checked is True


@pytest.mark.anyio
async def test_mark_quality_checked_service(client, auth_headers, db_session):
    from app.kds.service import mark_quality_checked

    restaurant, station, dish, order = await _setup_order_with_dish(db_session)
    item = await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.commit()

    updated = await mark_quality_checked(
        db_session, restaurant_id=restaurant.id, order_item_id=item.id
    )
    await db_session.commit()
    assert updated.quality_checked is True


@pytest.mark.anyio
async def test_packaging_check_router(client, auth_headers, db_session):
    restaurant, station, dish, order = await _setup_order_with_dish(db_session)
    item = await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/kds/items/{item.id}/packaging-check", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["packaging_checked"] is True


@pytest.mark.anyio
async def test_quality_check_router(client, auth_headers, db_session):
    restaurant, station, dish, order = await _setup_order_with_dish(db_session)
    item = await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/kds/items/{item.id}/quality-check", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["quality_checked"] is True


@pytest.mark.anyio
async def test_ready_for_pickup_router_lists_bumped_items(client, auth_headers, db_session):
    restaurant, station, dish, order = await _setup_order_with_dish(db_session)
    item = await add_item(db_session, order=order, dish=dish, qty=1)
    item.kitchen_status = "received"
    item.station_id_snapshot = station.id
    await db_session.commit()

    # Not ready yet — should not appear.
    listing = await client.get("/api/v1/kds/ready-for-pickup", headers=auth_headers)
    assert listing.status_code == 200
    assert all(o["order_id"] != order.id for o in listing.json())

    bump = await client.patch(f"/api/v1/kds/items/{item.id}/bump", headers=auth_headers)
    assert bump.status_code == 200

    listing = await client.get("/api/v1/kds/ready-for-pickup", headers=auth_headers)
    assert listing.status_code == 200
    matching = [o for o in listing.json() if o["order_id"] == order.id]
    assert len(matching) == 1
    assert any(i["id"] == item.id for i in matching[0]["items"])


@pytest.mark.anyio
async def test_ticket_item_out_includes_allergens(client, auth_headers, db_session):
    restaurant, station, dish, order = await _setup_order_with_dish(db_session)
    item = await add_item(db_session, order=order, dish=dish, qty=1)
    item.kitchen_status = "received"
    item.station_id_snapshot = station.id
    await db_session.commit()

    tickets = await client.get(
        f"/api/v1/kds/stations/{station.id}/tickets", headers=auth_headers
    )
    assert tickets.status_code == 200
    matching = [t for t in tickets.json() if t["id"] == item.id]
    assert len(matching) == 1
    assert matching[0]["allergens"] == ["nuts", "dairy"]
