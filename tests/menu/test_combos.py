from decimal import Decimal

import pytest

from app.menu.combo_service import combo_component_value, create_combo, list_combos


async def _make_dishes(db_session, restaurant):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()

    burger = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Burger",
        price_aed=Decimal("18.00"), is_available=True, name_normalized="burger",
    )
    fries = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Fries",
        price_aed=Decimal("9.00"), is_available=True, name_normalized="fries",
    )
    drink = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=3, name="Drink",
        price_aed=Decimal("5.00"), is_available=True, name_normalized="drink",
    )
    db_session.add_all([burger, fries, drink])
    await db_session.flush()
    return menu, burger, fries, drink


@pytest.mark.anyio
async def test_create_combo_bundles_dishes(db_session, restaurant):
    menu, burger, fries, drink = await _make_dishes(db_session, restaurant)

    combo = await create_combo(
        db_session, restaurant_id=restaurant.id, menu_id=menu.id, name="Burger Meal",
        price_aed=Decimal("25.00"), dish_ids=[burger.id, fries.id, drink.id],
    )
    await db_session.commit()

    assert combo.id is not None
    assert combo.name == "Burger Meal"
    assert combo.price_aed == Decimal("25.00")
    assert combo.is_available is True
    assert len(combo.items) == 3


@pytest.mark.anyio
async def test_list_combos_for_tenant(db_session, restaurant):
    menu, burger, fries, drink = await _make_dishes(db_session, restaurant)

    await create_combo(
        db_session, restaurant_id=restaurant.id, menu_id=menu.id, name="Burger Meal",
        price_aed=Decimal("25.00"), dish_ids=[burger.id, fries.id],
    )
    await create_combo(
        db_session, restaurant_id=restaurant.id, menu_id=menu.id, name="Snack Combo",
        price_aed=Decimal("12.00"), dish_ids=[fries.id, drink.id],
    )
    await db_session.commit()

    combos = await list_combos(db_session, restaurant_id=restaurant.id)
    assert {c.name for c in combos} == {"Burger Meal", "Snack Combo"}


@pytest.mark.anyio
async def test_combo_component_value_computes_savings(db_session, restaurant):
    menu, burger, fries, drink = await _make_dishes(db_session, restaurant)

    combo = await create_combo(
        db_session, restaurant_id=restaurant.id, menu_id=menu.id, name="Burger Meal",
        price_aed=Decimal("25.00"), dish_ids=[burger.id, fries.id, drink.id],
    )
    await db_session.commit()

    component_value = await combo_component_value(db_session, combo_id=combo.id)
    assert component_value == Decimal("32.00")

    savings = component_value - combo.price_aed
    assert savings == Decimal("7.00")


@pytest.mark.anyio
async def test_combo_component_value_respects_qty(db_session, restaurant):
    menu, burger, fries, drink = await _make_dishes(db_session, restaurant)

    from app.menu.combo_service import add_combo_item

    combo = await create_combo(
        db_session, restaurant_id=restaurant.id, menu_id=menu.id, name="Double Fries Meal",
        price_aed=Decimal("20.00"), dish_ids=[burger.id],
    )
    await add_combo_item(db_session, combo_id=combo.id, dish_id=fries.id, qty=2)
    await db_session.commit()

    component_value = await combo_component_value(db_session, combo_id=combo.id)
    assert component_value == Decimal("36.00")  # 18 + 2*9
