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


@pytest.mark.asyncio
async def test_cart_service_set_note_normalizes_prefix(db_session, restaurant, seed_biryani_menu):
    """set_note must strip politeness prefixes before storing (F101/TX-30)."""
    from app.ordering.cart_service import CartService
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from app.menu.models import Dish

    customer = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+97150000004")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani"))).first()
    await add_item(db_session, order=order, dish=dish, qty=1)
    svc = CartService(db_session)
    await svc.set_note(order=order, dish_id=dish.id, raw_note="pls add extra masala")
    from app.ordering.models import OrderItem
    items = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    assert len(items) == 1
    note = (items[0].notes or "").lower()
    assert not note.startswith("pls"), f"pls prefix not stripped: {note!r}"
    assert "masala" in note, f"masala missing: {note!r}"


@pytest.mark.asyncio
async def test_cart_service_clear_explicit_only(db_session, restaurant, seed_biryani_menu):
    """clear() must raise ValueError when explicit=False (F82)."""
    from app.ordering.cart_service import CartService
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from app.menu.models import Dish

    customer = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+97150000005")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani"))).first()
    await add_item(db_session, order=order, dish=dish, qty=1)
    svc = CartService(db_session)
    with pytest.raises(ValueError, match="explicit"):
        await svc.clear(order=order, explicit=False)


@pytest.mark.asyncio
async def test_cart_service_build_structured_context(db_session, restaurant, seed_biryani_menu):
    """build_structured_context must return CartLineContext with cart_item_id (F64)."""
    from app.ordering.cart_service import CartService
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from app.menu.models import Dish

    customer = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+97150000006")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani"))).first()
    await add_item(db_session, order=order, dish=dish, qty=2, notes="spicy")
    svc = CartService(db_session)
    lines = await svc.build_structured_context(order)
    assert len(lines) == 1
    line = lines[0]
    assert line.cart_item_id > 0
    assert line.dish_id == dish.id
    assert line.qty == 2
    assert line.notes == "spicy"


@pytest.mark.asyncio
async def test_build_context_includes_cart_lines(db_session, restaurant, seed_biryani_menu):
    """_build_context must inject cart_lines (CartLineContext list) in ordering phase (F64)."""
    from app.conversation.engine import _build_context, _set_state
    from app.conversation.service import get_or_create_conversation
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from app.menu.models import Dish

    customer = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone="+97150000007")
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani"))).first()
    await add_item(db_session, order=order, dish=dish, qty=1, notes="spicy")
    conv = await get_or_create_conversation(db_session, restaurant_id=restaurant.id, phone="+97150000007", counterpart="customer")
    _set_state(conv, draft_order_id=order.id, dialogue_phase="ordering")
    ctx = await _build_context(db_session, conv, restaurant.id, "ordering", restaurant)
    assert "cart_lines" in ctx, "cart_lines missing from context"
    lines = ctx["cart_lines"]
    assert len(lines) == 1
    assert lines[0]["cart_item_id"] > 0
    assert lines[0]["notes"] == "spicy"
