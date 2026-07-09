"""Category 2 — full kitchen/KDS wiring tests."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.kds.models import KitchenStation, PrintJob
from app.kds.printer_status import record_printer_heartbeat
from app.kds.service import (
    create_tickets_for_order,
    ensure_default_stations,
    kitchen_performance_report,
    list_station_tickets,
    mark_missing_item,
)
from app.menu.models import Dish, Menu
from app.ordering.models import Customer, Order
from app.ordering.service import add_item


async def _order_with_item(db_session, restaurant, *, station=None, allergens=None, mods=None):
    if station is None:
        station = KitchenStation(
            restaurant_id=restaurant.id, name="Grill", station_type="grill", kitchen_code="main"
        )
        db_session.add(station)
        await db_session.flush()
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=77,
        name="Mixed Grill",
        price_aed=Decimal("40.00"),
        category="Grills",
        is_available=True,
        name_normalized="mixed grill",
        station_id=station.id,
        allergens=allergens if allergens is not None else ["gluten"],
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009901", name="KDS Cat2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="K2-0001",
        status="confirmed",
        subtotal=Decimal("40.00"),
        total=Decimal("40.00"),
        customer_allergy_notes="shellfish",
        prep_deadline=datetime.now(timezone.utc) + timedelta(minutes=25),
        priority="rush",
    )
    db_session.add(order)
    await db_session.flush()
    item = await add_item(db_session, order=order, dish=dish, qty=1, notes="well done")
    if mods is not None:
        item.selected_modifiers = mods
    await db_session.flush()
    return station, order, item, dish


@pytest.mark.anyio
async def test_seed_default_stations_includes_typed_stations(db_session, restaurant):
    stations = await ensure_default_stations(db_session, restaurant_id=restaurant.id)
    await db_session.commit()
    types = {s.station_type for s in stations}
    for required in ("grill", "fry", "beverage", "dessert", "pizza", "cloud", "main"):
        assert required in types


@pytest.mark.anyio
async def test_create_tickets_payload_has_allergens_modifiers_and_fallback(db_session, restaurant):
    main = KitchenStation(
        restaurant_id=restaurant.id, name="Main FB", station_type="main", kitchen_code="main"
    )
    grill = KitchenStation(
        restaurant_id=restaurant.id,
        name="Grill FB",
        station_type="grill",
        kitchen_code="main",
    )
    db_session.add_all([main, grill])
    await db_session.flush()
    grill.fallback_station_id = main.id
    await db_session.flush()

    await record_printer_heartbeat(
        db_session, restaurant_id=restaurant.id, station_id=grill.id, healthy=False
    )
    await record_printer_heartbeat(
        db_session, restaurant_id=restaurant.id, station_id=main.id, healthy=True
    )

    station, order, item, dish = await _order_with_item(
        db_session,
        restaurant,
        station=grill,
        allergens=["nuts"],
        mods=[{"name": "extra sauce", "price_delta_aed": "2.00"}],
    )
    await create_tickets_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.commit()

    jobs = list(
        (await db_session.scalars(select(PrintJob).where(PrintJob.order_id == order.id))).all()
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.via_fallback is True
    assert job.station_id == main.id
    assert job.original_station_id == grill.id
    assert "ALLERGENS:nuts" in job.payload
    assert "extra sauce" in job.payload
    assert "NOTE:well done" in job.payload
    assert "CUSTOMER ALLERGY" in job.payload
    assert "RUSH" in job.payload.upper() or "rush" in job.payload.lower()

    await db_session.refresh(item)
    assert item.kitchen_status == "received"
    assert item.kitchen_received_at is not None
    assert item.kitchen_code_snapshot == "main"


@pytest.mark.anyio
async def test_list_station_tickets_auto_prioritizes_old_and_rush(db_session, restaurant):
    station, order, item, dish = await _order_with_item(db_session, restaurant)
    await create_tickets_for_order(db_session, restaurant_id=restaurant.id, order=order)
    item.kitchen_received_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    await db_session.flush()

    tickets = await list_station_tickets(
        db_session, restaurant_id=restaurant.id, station_id=station.id
    )
    assert len(tickets) >= 1
    t0 = tickets[0]
    assert t0["urgency"] in ("warning", "late")
    assert t0["is_delayed"] is True
    assert t0["age_seconds"] > 0
    assert t0["allergens"] == ["gluten"]
    assert t0["customer_allergy_notes"] == "shellfish"
    assert t0["estimated_ready_at"] is not None
    assert t0["order_priority"] == "rush"


@pytest.mark.anyio
async def test_missing_item_and_performance(db_session, restaurant):
    station, order, item, dish = await _order_with_item(db_session, restaurant)
    await create_tickets_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await mark_missing_item(
        db_session, restaurant_id=restaurant.id, order_item_id=item.id, note="missing fries"
    )
    await db_session.refresh(item)
    assert item.missing_item_confirmed is True
    assert item.missing_item_note == "missing fries"

    item.bumped_at = datetime.now(timezone.utc)
    item.kitchen_status = "ready"
    await db_session.flush()
    today = date.today()
    report = await kitchen_performance_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert report["ticket_count"] >= 1
    assert report["bumped_count"] >= 1


@pytest.mark.anyio
async def test_router_station_tickets_and_missing_item(client, auth_headers, db_session):
    # auth_headers signs up owner@biryani.ae — resolve that restaurant
    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    assert restaurant is not None
    station, order, item, dish = await _order_with_item(db_session, restaurant)
    await create_tickets_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.commit()

    r = await client.get(
        f"/api/v1/kds/stations/{station.id}/tickets", headers=auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    assert "urgency" in body[0]
    assert "age_seconds" in body[0]
    assert body[0]["allergens"] == ["gluten"]

    r2 = await client.post(
        f"/api/v1/kds/items/{item.id}/missing-item",
        headers=auth_headers,
        json={"note": "short portion"},
    )
    assert r2.status_code == 200
    assert r2.json()["missing_item_confirmed"] is True

    r3 = await client.get(
        f"/api/v1/kds/performance?start_date={date.today()}&end_date={date.today()}",
        headers=auth_headers,
    )
    assert r3.status_code == 200
    assert "ticket_count" in r3.json()


@pytest.mark.anyio
async def test_multi_kitchen_seed(db_session, restaurant):
    cloud = await ensure_default_stations(
        db_session, restaurant_id=restaurant.id, kitchen_code="cloud-a"
    )
    await db_session.commit()
    assert all(s.kitchen_code == "cloud-a" for s in cloud)
    assert any(s.station_type == "cloud" for s in cloud)
