"""Tests for set_item_qty + out-of-stock matching helpers."""
from decimal import Decimal

from app.menu.models import Dish, Menu
from app.ordering.matching import (
    find_unavailable_match,
    suggest_available_alternative,
)
from app.ordering.models import OrderItem
from app.ordering.service import (
    add_item,
    create_draft_order,
    get_or_create_customer,
    set_item_qty,
)


async def _seed_menu(db_session, restaurant_id):
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dishes = {
        "biryani": Dish(
            menu_id=menu.id, restaurant_id=restaurant_id, dish_number=1,
            name="Chicken Biryani", price_aed=Decimal("28.00"), category="Rice",
            is_available=True, name_normalized="chicken biryani",
        ),
        "paneer": Dish(
            menu_id=menu.id, restaurant_id=restaurant_id, dish_number=2,
            name="Paneer Tikka", price_aed=Decimal("26.00"), category="Curries",
            is_available=False, name_normalized="paneer tikka",
        ),
        "karahi": Dish(
            menu_id=menu.id, restaurant_id=restaurant_id, dish_number=3,
            name="Mutton Karahi", price_aed=Decimal("35.00"), category="Curries",
            is_available=True, name_normalized="mutton karahi",
        ),
    }
    for d in dishes.values():
        db_session.add(d)
    await db_session.flush()
    return dishes


async def test_set_item_qty_updates_and_recalcs(db_session, restaurant):
    dishes = await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+9715")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await add_item(db_session, order=order, dish=dishes["biryani"], qty=2)
    assert order.subtotal == Decimal("56.00")

    survivor = await set_item_qty(db_session, order=order, dish_id=dishes["biryani"].id, qty=3)
    assert survivor is not None
    assert survivor.qty == 3
    assert order.subtotal == Decimal("84.00")  # 3 * 28


async def test_set_item_qty_zero_removes(db_session, restaurant):
    dishes = await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+9716")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await add_item(db_session, order=order, dish=dishes["biryani"], qty=2)

    survivor = await set_item_qty(db_session, order=order, dish_id=dishes["biryani"].id, qty=0)
    assert survivor is None
    remaining = (await db_session.scalars(
        select_items(order.id)
    )).all()
    assert remaining == []
    assert order.subtotal == Decimal("0.00")


async def test_set_item_qty_missing_dish_returns_none(db_session, restaurant):
    dishes = await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+9717")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    # dish not in cart
    assert await set_item_qty(db_session, order=order, dish_id=dishes["karahi"].id, qty=3) is None


async def test_find_unavailable_match_and_alternative(db_session, restaurant):
    dishes = await _seed_menu(db_session, restaurant.id)
    await db_session.commit()

    # "paneer tikka" is real but unavailable
    unavailable = await find_unavailable_match(db_session, restaurant.id, "paneer tikka")
    assert unavailable is not None
    assert unavailable.id == dishes["paneer"].id

    # available alternative in the same category (Curries) -> Mutton Karahi
    alt = await suggest_available_alternative(
        db_session, restaurant.id, category="Curries", exclude_id=dishes["paneer"].id
    )
    assert alt is not None
    assert alt.id == dishes["karahi"].id


async def test_find_unavailable_match_none_for_available(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)
    await db_session.commit()
    # an available dish should NOT be reported as unavailable
    assert await find_unavailable_match(db_session, restaurant.id, "chicken biryani") is None


def select_items(order_id):
    from sqlalchemy import select
    return select(OrderItem).where(OrderItem.order_id == order_id)
