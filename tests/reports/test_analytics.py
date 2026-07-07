from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.reports.analytics import (
    inventory_usage,
    item_performance,
    labor_hours,
    table_turn_time,
)


@pytest.mark.anyio
async def test_item_performance_ranks_by_revenue(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    kebab = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), is_available=True, name_normalized="kebab",
    )
    water = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Water",
        price_aed=Decimal("2.00"), is_available=True, name_normalized="water",
    )
    db_session.add_all([kebab, water])
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000011", name="Perf Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="P-0001",
        status="delivered", subtotal=Decimal("42.00"), total=Decimal("42.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=kebab.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=2,
    ))
    db_session.add(OrderItem(
        order_id=order.id, dish_id=water.id, dish_number=2, dish_name="Water",
        price_aed=Decimal("2.00"), qty=1,
    ))
    await db_session.commit()

    today = date.today()
    results = await item_performance(db_session, restaurant_id=restaurant.id, start_date=today, end_date=today)
    assert results[0]["dish_name"] == "Kebab"
    assert results[0]["revenue_aed"] == Decimal("40.00")
    assert results[0]["order_count"] == 2
    assert results[1]["dish_name"] == "Water"


@pytest.mark.anyio
async def test_inventory_usage_walks_confirmed_orders_recipes(db_session, restaurant):
    from app.inventory.models import DishIngredient, Ingredient
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    flour = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("1.000"),
    )
    db_session.add(flour)
    await db_session.flush()
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Bread",
        price_aed=Decimal("10.00"), is_available=True, name_normalized="bread",
    )
    db_session.add(dish)
    await db_session.flush()
    db_session.add(DishIngredient(dish_id=dish.id, ingredient_id=flour.id, quantity_per_dish=Decimal("0.500")))
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000012", name="Usage Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="U-0001",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Bread",
        price_aed=Decimal("10.00"), qty=2,
    ))
    await db_session.commit()

    today = date.today()
    results = await inventory_usage(db_session, restaurant_id=restaurant.id, start_date=today, end_date=today)
    assert results[0]["ingredient_name"] == "Flour"
    assert results[0]["quantity_used"] == Decimal("1.000")


@pytest.mark.anyio
async def test_table_turn_time_pairs_seated_to_available(db_session, restaurant):
    from app.audit import record_audit
    from app.tables.models import DiningTable

    table = DiningTable(restaurant_id=restaurant.id, label="T1", seats=4)
    db_session.add(table)
    await db_session.flush()
    await record_audit(
        db_session, actor="manager", entity="table", entity_id=str(table.id),
        action="status_change", restaurant_id=restaurant.id,
        before={"status": "available"}, after={"status": "seated"},
    )
    await db_session.commit()
    await record_audit(
        db_session, actor="manager", entity="table", entity_id=str(table.id),
        action="status_change", restaurant_id=restaurant.id,
        before={"status": "needs_bill"}, after={"status": "available"},
    )
    await db_session.commit()

    today = date.today()
    results = await table_turn_time(db_session, restaurant_id=restaurant.id, start_date=today, end_date=today)
    assert len(results) == 1
    assert results[0]["table_id"] == table.id
    assert results[0]["turn_minutes"] >= 0


@pytest.mark.anyio
async def test_labor_hours_reports_per_staff(db_session, restaurant):
    from app.staff.models import StaffMember
    from app.staff.service import clock_in, clock_out

    staff = StaffMember(restaurant_id=restaurant.id, name="Zara", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    in_time = datetime.now(timezone.utc) - timedelta(hours=4)
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=in_time)
    await db_session.commit()
    await clock_out(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()

    results = await labor_hours(db_session, restaurant_id=restaurant.id, target_date=date.today())
    assert results[0]["staff_id"] == staff.id
    assert results[0]["hours"] == pytest.approx(4.0, abs=0.01)
