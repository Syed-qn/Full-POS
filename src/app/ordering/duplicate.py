from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ordering.models import Order, OrderItem
from app.ordering.service import create_draft_order


async def duplicate_order(session: AsyncSession, *, restaurant_id: int, order_id: int) -> Order:
    """Repeat-order / duplicate-order: create a fresh draft copying the source
    order's items, customer, and address. Never touches the source order."""
    source = await session.get(Order, order_id)
    if source is None or source.restaurant_id != restaurant_id:
        raise ValueError(f"order {order_id} not found")

    new_order = await create_draft_order(session, restaurant_id=restaurant_id, customer_id=source.customer_id)
    new_order.address_id = source.address_id
    new_order.subtotal = source.subtotal
    new_order.delivery_fee_aed = source.delivery_fee_aed
    new_order.total = source.total
    new_order.order_type = getattr(source, "order_type", None) or "delivery"
    new_order.table_id = source.table_id
    new_order.customer_allergy_notes = source.customer_allergy_notes

    source_items = (await session.scalars(
        select(OrderItem).where(
            OrderItem.order_id == source.id,
            OrderItem.cancelled.is_(False),
        )
    )).all()
    for item in source_items:
        session.add(OrderItem(
            order_id=new_order.id, dish_id=item.dish_id, dish_number=item.dish_number,
            dish_name=item.dish_name, variant_name=item.variant_name, price_aed=item.price_aed,
            qty=item.qty, notes=item.notes,
            course_number=getattr(item, "course_number", 1) or 1,
            seat_number=getattr(item, "seat_number", None),
            selected_modifiers=list(getattr(item, "selected_modifiers", None) or []),
            allergens_snapshot=list(getattr(item, "allergens_snapshot", None) or []),
        ))
    await session.flush()
    return new_order
