"""Handle a WhatsApp catalog cart (``order`` message) → a draft order.

This is intentionally independent of ``conversation.engine``. It reuses the
ordering domain helpers (customer + draft order + items) but holds none of the
engine's dialogue state, so the two flows never interfere. Small formatting
helpers are COPIED here rather than imported from the engine to keep the
separation hard.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.models import Dish
from app.ordering.service import add_item, create_draft_order, get_or_create_customer
from app.outbox.service import enqueue_message
from app.whatsapp.port import InboundMessage, OutboundMessageType

logger = logging.getLogger(__name__)


def _aed(value) -> str:
    """Plain AED amount, trailing zeros stripped (18.00 -> "18", 18.50 -> "18.5").

    Copied from the conversation engine on purpose so the catalog flow has no
    import dependency on it.
    """
    return f"{Decimal(value).normalize():f}"


def _to_decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


async def _find_dish(session: AsyncSession, *, restaurant_id: int, retailer_id: str) -> Dish | None:
    """Map a catalog product (Content / retailer id) back to a dish for this restaurant."""
    if not retailer_id:
        return None
    return await session.scalar(
        select(Dish)
        .where(Dish.restaurant_id == restaurant_id, Dish.catalog_retailer_id == retailer_id)
        .limit(1)
    )


async def handle_catalog_order(
    session: AsyncSession,
    inbound: InboundMessage,
    *,
    restaurant_id: int,
) -> None:
    """Turn a sent catalog cart into a draft order and ask for the delivery location.

    Mapped items (a dish carries the cart's retailer id) are added at the dish's own
    price. Unmapped items are listed back to the customer so nothing is silently lost.
    The caller (webhook) commits and flushes the outbox.
    """
    payload = inbound.payload or {}
    product_items: list[dict] = payload.get("product_items") or []
    if not product_items:
        return

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone
    )
    order = await create_draft_order(
        session, restaurant_id=restaurant_id, customer_id=customer.id
    )

    added_lines: list[str] = []
    unmapped: list[str] = []
    for item in product_items:
        retailer_id = str(item.get("product_retailer_id") or "")
        try:
            qty = max(1, int(item.get("quantity", 1)))
        except (TypeError, ValueError):
            qty = 1
        dish = await _find_dish(session, restaurant_id=restaurant_id, retailer_id=retailer_id)
        if dish is None or dish.price_aed is None:
            # Keep the customer informed; record the raw price from the cart for context.
            price = _to_decimal(item.get("item_price"))
            label = f"{qty}x item {retailer_id}" + (f" (AED {_aed(price)})" if price else "")
            unmapped.append(label)
            continue
        await add_item(session, order=order, dish=dish, qty=qty)
        added_lines.append(f"• {qty}x {dish.name} (AED {_aed(dish.price_aed * qty)})")

    if not added_lines:
        # Nothing we could match — tell the customer instead of leaving an empty order.
        body = (
            "Thanks for your order 🙏 We couldn't match those items to our menu yet. "
            "Please send your order as a message and we'll help you right away 😊"
        )
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": body},
            idempotency_key=f"catalog-empty-{inbound.wa_message_id}",
        )
        logger.info("catalog order with no mappable items for restaurant %s", restaurant_id)
        return

    lines = "\n".join(added_lines)
    extra = ("\n\nWe couldn't add: " + "; ".join(unmapped)) if unmapped else ""
    body = (
        f"Got your order 🎉\n\n"
        f"🛒 Your cart:\n{lines}\n"
        f"Subtotal: AED {_aed(order.subtotal)}{extra}\n\n"
        f"To finish, please share your delivery location 📍 and we'll get it on its way 😊"
    )
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
        idempotency_key=f"catalog-order-{inbound.wa_message_id}",
    )
    logger.info(
        "catalog order %s for restaurant %s: %d line(s), subtotal %s",
        order.order_number, restaurant_id, len(added_lines), order.subtotal,
    )
