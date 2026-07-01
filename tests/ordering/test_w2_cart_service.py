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
