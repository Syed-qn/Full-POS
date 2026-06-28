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
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import CatalogProduct
from app.menu.models import Dish
from app.ordering.models import Order
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


async def send_catalog(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    header: str = "Our Menu",
    body: str = "Tap an item to add it to your basket, then send the basket to order 😊",
    idempotency_key: str | None = None,
) -> bool:
    """Send the catalog as a multi-product message (tappable cards with Add to basket).

    This is THE way to show a catalog on the Cloud API (there is no reliable chat-header
    icon for API numbers). Builds sections from the restaurant's dishes that are linked
    to catalog products (``catalog_retailer_id``), grouped by category. Returns False if
    the restaurant has no catalog id or no linked, available products. Caller commits.
    """
    from app.identity.models import Restaurant

    rest = await session.get(Restaurant, restaurant_id)
    settings = (rest.settings or {}) if rest is not None else {}
    catalog_id = (settings.get("catalog_id") or "").strip()
    if not catalog_id:
        logger.info("send_catalog skipped: no catalog_id for restaurant %s", restaurant_id)
        return False

    # The catalogue SYNCED from Meta (the OPS "Sync from Meta" mirror) is the ONLY
    # source of truth in catalogue mode. STRICT, no fallback: if nothing has been
    # synced we send nothing rather than leak unsynced text-menu dishes as tappable
    # cards. The manager must press "Sync from Meta" first.
    synced = (
        await session.scalars(
            select(CatalogProduct).where(
                CatalogProduct.restaurant_id == restaurant_id,
                CatalogProduct.is_active.is_(True),
            ).order_by(CatalogProduct.category, CatalogProduct.name)
        )
    ).all()
    if not synced:
        logger.info(
            "send_catalog skipped: catalogue not synced for restaurant %s "
            "(refusing to fall back to text-menu dishes)", restaurant_id
        )
        return False

    # Group into sections by category (WhatsApp limits: <=10 sections, <=30
    # products total, section title <=24 chars). Stable, readable order.
    sections: dict[str, list[dict]] = {}
    total = 0
    for p in synced:
        if total >= 30:
            break
        cat = (p.category or "Menu")[:24]
        sections.setdefault(cat, []).append({"product_retailer_id": p.retailer_id})
        total += 1

    payload_sections = [
        {"title": title, "product_items": items}
        for title, items in list(sections.items())[:10]
    ]
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=to_phone,
        msg_type=OutboundMessageType.PRODUCT_LIST,
        payload={
            "header": header[:60],
            "body": body[:1024],
            "catalog_id": catalog_id,
            "sections": payload_sections,
        },
        idempotency_key=idempotency_key or f"catalog-send-{restaurant_id}-{to_phone}-{uuid4().hex}",
    )
    logger.info(
        "sent catalog to %s for restaurant %s: %d product(s) in %d section(s)",
        to_phone, restaurant_id, total, len(payload_sections),
    )
    return True


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
    import time

    payload = inbound.payload or {}
    product_items: list[dict] = payload.get("product_items") or []
    if not product_items:
        return

    # The catalogue basket fills the SAME conversation + cart the text bot uses, then
    # leaves the customer in the normal "collecting_items" state. So after the basket
    # everything is identical to the text flow: the customer sends 'done' and the
    # conversation engine drives delivery, confirmation, kitchen and dispatch. We reuse
    # the engine's helpers (lazy import) so behaviour cannot drift from the text path.
    from app.conversation.engine import _build_cart_summary, _send_text, _set_state
    from app.conversation.service import get_or_create_conversation, record_message

    conv = await get_or_create_conversation(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone, counterpart="customer",
    )
    await record_message(
        session, conversation_id=conv.id, direction="inbound",
        wa_message_id=inbound.wa_message_id, msg_type="order",
        payload={"product_items": product_items},
        ts=inbound.timestamp or int(time.time()),
    )
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone
    )

    # Reuse the engine's draft order (the live cart pointed to by conv.state), exactly
    # like _execute_ai_add_item does — never start a parallel order.
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is not None and str(order.status) != "draft":
        order = None
    if order is None:
        order = await create_draft_order(
            session, restaurant_id=restaurant_id, customer_id=customer.id
        )
        _set_state(conv, draft_order_id=order.id)

    added = 0
    unmapped: list[str] = []
    for item in product_items:
        retailer_id = str(item.get("product_retailer_id") or "")
        try:
            qty = max(1, int(item.get("quantity", 1)))
        except (TypeError, ValueError):
            qty = 1
        dish = await _find_dish(session, restaurant_id=restaurant_id, retailer_id=retailer_id)
        # STRICT catalogue membership: only add an item that is backed by an ACTIVE
        # synced CatalogProduct. A dish linked to a retailer_id that was never synced
        # (or has since gone inactive/out of stock) must never sneak into the cart.
        in_catalogue = await session.scalar(
            select(CatalogProduct.id).where(
                CatalogProduct.restaurant_id == restaurant_id,
                CatalogProduct.retailer_id == retailer_id,
                CatalogProduct.is_active.is_(True),
            ).limit(1)
        )
        if dish is None or dish.price_aed is None or in_catalogue is None:
            price = _to_decimal(item.get("item_price"))
            unmapped.append(
                f"{qty}x item {retailer_id}" + (f" (AED {_aed(price)})" if price else "")
            )
            continue
        await add_item(session, order=order, dish=dish, qty=qty)
        added += 1

    if not added:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="catalog-empty",
            body=("Thanks 🙏 We couldn't match those items to our menu yet. "
                  "Please type your order and we'll help you right away 😊"),
        )
        logger.info("catalog basket with no mappable items for restaurant %s", restaurant_id)
        return

    # Hand control to the normal flow: same state the text bot is in after adding items.
    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
    cart = await _build_cart_summary(session, conv)
    extra = ("\nWe couldn't add: " + "; ".join(unmapped)) if unmapped else ""
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="catalog-cart",
        body=(f"Got your basket 🎉\n\n🛒 {cart}{extra}\n\n"
              f"Reply with more items, or send 'done' to proceed to delivery details."),
    )
    logger.info(
        "catalog basket -> order %s for restaurant %s: %d line(s), subtotal %s",
        order.order_number, restaurant_id, added, order.subtotal,
    )
