from decimal import Decimal

import pytest

from app.menu.modifier_service import compute_selection_total, create_group, create_modifier


@pytest.mark.anyio
async def test_create_group_and_modifiers(db_session, restaurant):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Pizza",
        price_aed=Decimal("35.00"), is_available=True, name_normalized="pizza",
    )
    db_session.add(dish)
    await db_session.flush()

    group = await create_group(
        db_session, restaurant_id=restaurant.id, dish_id=dish.id, name="Toppings",
        min_select=0, max_select=3, required=False,
    )
    await db_session.commit()
    mod1 = await create_modifier(db_session, group_id=group.id, name="Extra Cheese", price_delta_aed=Decimal("5.00"))
    mod2 = await create_modifier(db_session, group_id=group.id, name="Mushrooms", price_delta_aed=Decimal("3.00"))
    await db_session.commit()

    assert mod1.name == "Extra Cheese"
    assert mod2.price_delta_aed == Decimal("3.00")


@pytest.mark.anyio
async def test_compute_selection_total_sums_deltas(db_session, restaurant):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Burger",
        price_aed=Decimal("25.00"), is_available=True, name_normalized="burger",
    )
    db_session.add(dish)
    await db_session.flush()
    group = await create_group(
        db_session, restaurant_id=restaurant.id, dish_id=dish.id, name="Add-ons",
        min_select=0, max_select=5, required=False,
    )
    await db_session.commit()
    mod1 = await create_modifier(db_session, group_id=group.id, name="Bacon", price_delta_aed=Decimal("6.00"))
    mod2 = await create_modifier(db_session, group_id=group.id, name="Avocado", price_delta_aed=Decimal("4.00"))
    await db_session.commit()

    total = await compute_selection_total(
        db_session, base_price_aed=Decimal("25.00"), modifier_ids=[mod1.id, mod2.id],
    )
    assert total == Decimal("35.00")
