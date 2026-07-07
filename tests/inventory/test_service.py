from decimal import Decimal

import pytest

from app.inventory.models import DishIngredient, Ingredient
from app.inventory.service import deduct_for_order, list_low_stock, record_waste


@pytest.mark.anyio
async def test_deduct_for_order_walks_recipe_and_decrements_stock(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    flour = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
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

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000044", name="Inv Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="I-0001",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Bread",
        price_aed=Decimal("10.00"), qty=2,
    )
    db_session.add(item)
    await db_session.commit()

    await deduct_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.commit()
    await db_session.refresh(flour)

    # 2 breads x 0.5kg flour each = 1kg deducted from 10kg
    assert flour.current_stock == Decimal("9.000")


@pytest.mark.anyio
async def test_deduct_for_order_skips_dishes_with_no_recipe(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Water",
        price_aed=Decimal("2.00"), is_available=True, name_normalized="water",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000045", name="Inv Test2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="I-0002",
        status="confirmed", subtotal=Decimal("2.00"), total=Decimal("2.00"),
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Water",
        price_aed=Decimal("2.00"), qty=1,
    )
    db_session.add(item)
    await db_session.commit()

    await deduct_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.commit()  # must not raise even though no recipe exists


@pytest.mark.anyio
async def test_list_low_stock_returns_only_below_threshold(db_session, restaurant):
    low = Ingredient(
        restaurant_id=restaurant.id, name="Sugar", unit="kg",
        current_stock=Decimal("1.000"), low_stock_threshold=Decimal("5.000"),
    )
    ok = Ingredient(
        restaurant_id=restaurant.id, name="Salt", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("2.000"),
    )
    db_session.add_all([low, ok])
    await db_session.commit()

    results = await list_low_stock(db_session, restaurant_id=restaurant.id)
    names = {r.name for r in results}
    assert names == {"Sugar"}


@pytest.mark.anyio
async def test_record_waste_decrements_stock(db_session, restaurant):
    ing = Ingredient(
        restaurant_id=restaurant.id, name="Tomato", unit="kg",
        current_stock=Decimal("5.000"), low_stock_threshold=Decimal("1.000"),
    )
    db_session.add(ing)
    await db_session.commit()

    await record_waste(
        db_session, restaurant_id=restaurant.id, ingredient_id=ing.id,
        quantity=Decimal("1.500"), reason="spoiled", recorded_by="manager",
    )
    await db_session.commit()
    await db_session.refresh(ing)
    assert ing.current_stock == Decimal("3.500")
