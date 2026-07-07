from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.reports.analytics import avg_prep_time_by_item, avg_prep_time_by_staff


async def _make_bumped_item(
    db_session, *, restaurant, order_number, dish_name, station_id, minutes_to_prep
):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    menu = await db_session.scalar(
        __import__("sqlalchemy").select(Menu).where(Menu.restaurant_id == restaurant.id)
    )
    if menu is None:
        menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
        db_session.add(menu)
        await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name=dish_name,
        price_aed=Decimal("15.00"), is_available=True, name_normalized=dish_name.lower(),
    )
    db_session.add(dish)
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone=f"+97150000{order_number}", name="Prep Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number=order_number,
        status="delivered", subtotal=Decimal("15.00"), total=Decimal("15.00"),
    )
    db_session.add(order)
    await db_session.flush()

    # OrderItem.created_at is stored naive UTC (TimestampMixin) — mirror that here.
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_to_prep)).replace(tzinfo=None)
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name=dish_name,
        price_aed=Decimal("15.00"), qty=1, kitchen_status="ready",
        station_id_snapshot=station_id,
    )
    db_session.add(item)
    await db_session.flush()
    # created_at is server-set via TimestampMixin default; override directly.
    item.created_at = created_at
    item.bumped_at = datetime.now(timezone.utc)
    await db_session.commit()
    return item


@pytest.mark.anyio
async def test_avg_prep_time_by_item_computes_minutes_from_creation_to_bump(db_session, restaurant):
    from app.kds.models import KitchenStation

    station = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    db_session.add(station)
    await db_session.flush()
    await db_session.commit()

    await _make_bumped_item(
        db_session, restaurant=restaurant, order_number="PT-0001",
        dish_name="Kebab", station_id=station.id, minutes_to_prep=10,
    )
    await _make_bumped_item(
        db_session, restaurant=restaurant, order_number="PT-0002",
        dish_name="Kebab", station_id=station.id, minutes_to_prep=20,
    )

    today = date.today()
    results = await avg_prep_time_by_item(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert len(results) == 1
    assert results[0]["key"] == "Kebab"
    assert results[0]["ticket_count"] == 2
    assert results[0]["avg_prep_minutes"] == pytest.approx(15.0, abs=0.5)


@pytest.mark.anyio
async def test_avg_prep_time_by_staff_groups_by_station(db_session, restaurant):
    from app.kds.models import KitchenStation

    station = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    db_session.add(station)
    await db_session.flush()
    await db_session.commit()

    await _make_bumped_item(
        db_session, restaurant=restaurant, order_number="PT-0003",
        dish_name="Fries", station_id=station.id, minutes_to_prep=8,
    )

    today = date.today()
    results = await avg_prep_time_by_staff(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert len(results) == 1
    assert results[0]["key"] == "Grill"
    assert results[0]["ticket_count"] == 1
    assert results[0]["avg_prep_minutes"] == pytest.approx(8.0, abs=0.5)


@pytest.mark.anyio
async def test_avg_prep_time_excludes_unbumped_items(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Salad",
        price_aed=Decimal("15.00"), is_available=True, name_normalized="salad",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009999", name="Unbumped")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="PT-0004",
        status="confirmed", subtotal=Decimal("15.00"), total=Decimal("15.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Salad",
        price_aed=Decimal("15.00"), qty=1, kitchen_status="received",
    ))
    await db_session.commit()

    today = date.today()
    results = await avg_prep_time_by_item(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert results == []


@pytest.mark.anyio
async def test_prep_time_router_endpoints_return_empty_lists_with_no_data(client, auth_headers):
    today = date.today().isoformat()
    for path in ("prep-time-by-item", "prep-time-by-staff"):
        resp = await client.get(
            f"/api/v1/reports/{path}?start_date={today}&end_date={today}", headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []
