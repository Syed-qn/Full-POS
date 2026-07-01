"""Pure DB renderer tests (W3/RA-1/R-013)."""
from __future__ import annotations

import pytest
from decimal import Decimal


@pytest.mark.asyncio
async def test_render_cart_state_ordering_phase(db_session, restaurant, seed_biryani_menu):
    """ordering phase: result starts with \n\n🛒, contains dish name and subtotal."""
    from app.conversation.renderer import render_cart_state
    from app.menu.models import Dish
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from sqlalchemy import select

    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000060"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    dish = (await db_session.scalars(
        select(Dish).where(Dish.name_normalized == "chicken biryani",
                           Dish.restaurant_id == restaurant.id)
    )).first()
    await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.flush()

    result = await render_cart_state(db_session, order=order, phase="ordering")

    assert result.startswith("\n\n🛒"), f"expected \\n\\n🛒 prefix, got: {result!r}"
    assert "Chicken Biryani" in result or "biryani" in result.lower()
    assert "Subtotal" in result


@pytest.mark.asyncio
async def test_render_cart_state_confirm_phase(db_session, restaurant, seed_biryani_menu):
    """awaiting_confirmation phase: result contains order summary fields."""
    from app.conversation.renderer import render_cart_state
    from app.menu.models import Dish
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from sqlalchemy import select

    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000061"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    dish = (await db_session.scalars(
        select(Dish).where(Dish.name_normalized == "chicken biryani",
                           Dish.restaurant_id == restaurant.id)
    )).first()
    await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.flush()

    result = await render_cart_state(db_session, order=order, phase="awaiting_confirmation")

    assert "Order summary" in result, f"missing 'Order summary' in: {result!r}"
    assert "Subtotal:" in result
    assert "Total:" in result
    assert "Delivery fee:" in result
    assert "Payment: COD" in result


@pytest.mark.asyncio
async def test_render_cart_state_empty_ordering(db_session, restaurant, seed_biryani_menu):
    """ordering phase with no items → '\\n\\n🛒 Your cart is now empty.'"""
    from app.conversation.renderer import render_cart_state
    from app.ordering.service import create_draft_order, get_or_create_customer

    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000062"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await db_session.flush()

    result = await render_cart_state(db_session, order=order, phase="ordering")
    assert result == "\n\n🛒 Your cart is now empty."
