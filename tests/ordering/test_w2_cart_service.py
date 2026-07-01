"""W2 cart-line identity tests."""
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_add_item_noted_reAdd_merges_note(db_session, restaurant, seed_biryani_menu):
    """Re-adding a dish with a note must update the existing line's note, not create a 2nd line."""
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from app.menu.models import Dish

    customer = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+97150000001")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani"))).first()
    # First add — no note
    await add_item(db_session, order=order, dish=dish, qty=1, notes=None)
    # Second add — WITH note (should update existing line, not create new)
    await add_item(db_session, order=order, dish=dish, qty=1, notes="double masala")
    from app.ordering.models import OrderItem
    items = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    assert len(items) == 1, f"expected 1 line, got {len(items)}"
    assert items[0].notes == "double masala"
    assert items[0].qty == 2


@pytest.mark.asyncio
async def test_set_item_qty_preserves_note(db_session, restaurant, seed_biryani_menu):
    """Changing qty must preserve the kitchen note (RA-7/R-006)."""
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer, set_item_qty
    from app.menu.models import Dish

    customer = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+97150000002")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani"))).first()
    await add_item(db_session, order=order, dish=dish, qty=2, notes="extra spicy")
    # Change qty to 1 — note must survive
    result = await set_item_qty(db_session, order=order, dish_id=dish.id, qty=1)
    assert result is not None
    assert result.notes == "extra spicy", f"note lost: {result.notes!r}"
    assert result.qty == 1


@pytest.mark.asyncio
async def test_modify_order_preserves_variant_and_notes(db_session, restaurant, seed_biryani_menu):
    """modify_order must carry variant_name and notes from new_items, not silently strip them (R-009)."""
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer, modify_order
    from app.menu.models import Dish
    from decimal import Decimal

    customer = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+97150000003")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani"))).first()
    await add_item(db_session, order=order, dish=dish, qty=1)
    # Modify with explicit variant_name, notes, price_aed
    await modify_order(db_session, order=order, actor="customer", new_items=[
        {"dish": dish, "qty": 2, "variant_name": "Large", "notes": "extra spicy", "price_aed": Decimal("25.00")}
    ])
    from app.ordering.models import OrderItem
    items = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    assert len(items) == 1
    assert items[0].variant_name == "Large"
    assert items[0].notes == "extra spicy"
    assert items[0].price_aed == Decimal("25.00")
