from decimal import Decimal

import pytest

from app.inventory.costing import dish_cost


@pytest.mark.anyio
async def test_dish_cost_sums_recipe_ingredient_costs(db_session, restaurant):
    from app.inventory.models import DishIngredient, Ingredient
    from app.menu.models import Dish, Menu

    flour = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("10.000"), low_stock_threshold=Decimal("1.000"),
        cost_per_unit_aed=Decimal("4.0000"),
    )
    oil = Ingredient(
        restaurant_id=restaurant.id, name="Oil", unit="L",
        current_stock=Decimal("5.000"), low_stock_threshold=Decimal("1.000"),
        cost_per_unit_aed=Decimal("10.0000"),
    )
    db_session.add_all([flour, oil])
    await db_session.flush()
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Fried Bread",
        price_aed=Decimal("15.00"), is_available=True, name_normalized="fried bread",
    )
    db_session.add(dish)
    await db_session.flush()
    db_session.add(DishIngredient(dish_id=dish.id, ingredient_id=flour.id, quantity_per_dish=Decimal("0.500")))
    db_session.add(DishIngredient(dish_id=dish.id, ingredient_id=oil.id, quantity_per_dish=Decimal("0.100")))
    await db_session.commit()

    # 0.5kg * 4.00 + 0.1L * 10.00 = 2.00 + 1.00 = 3.00
    cost = await dish_cost(db_session, dish_id=dish.id)
    assert cost == Decimal("3.0000")


@pytest.mark.anyio
async def test_dish_cost_zero_when_no_recipe(db_session, restaurant):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Water",
        price_aed=Decimal("2.00"), is_available=True, name_normalized="water",
    )
    db_session.add(dish)
    await db_session.commit()

    cost = await dish_cost(db_session, dish_id=dish.id)
    assert cost == Decimal("0.0000")
