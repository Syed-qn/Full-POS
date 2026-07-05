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

# WhatsApp per-message caps: a product_list shows at most 30 products; an interactive
# list shows at most 10 rows. Past these the customer can't reach the rest of the menu,
# which is what browse-by-category solves.
_PRODUCT_LIST_MAX = 30
_LIST_MAX_ROWS = 10
# One list row is reserved for a "More categories" link when more pages exist, so each
# category page shows up to 9 categories. Paginating this way makes EVERY category
# reachable by tapping no matter how many there are (e.g. 31 categories -> 4 pages).
_CAT_PAGE_SIZE = _LIST_MAX_ROWS - 1


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


def _retailer_id_from_item(item: dict) -> str:
    """Normalize retailer id keys from Cloud API / simulator / legacy payloads."""
    for key in (
        "product_retailer_id",
        "productretailerid",
        "product_retailer_id",
        "productretailer_id",
    ):
        val = item.get(key)
        if val:
            return str(val)
    return ""


async def _find_dish(session: AsyncSession, *, restaurant_id: int, retailer_id: str) -> Dish | None:
    """Map a catalog product (Content / retailer id) back to a dish for this restaurant."""
    if not retailer_id:
        return None
    return await session.scalar(
        select(Dish)
        .where(Dish.restaurant_id == restaurant_id, Dish.catalog_retailer_id == retailer_id)
        .limit(1)
    )


from app.catalog.tenant_scope import (
    load_tenant_catalog_mirror as _load_tenant_catalog_mirror,
    native_catalog_view_allowed,
    product_belongs_to_restaurant,
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
    from app.catalog.sync_service import refresh_pending_catalog_sendability

    await refresh_pending_catalog_sendability(session, restaurant_id=restaurant_id)
    catalog_id, synced = await _load_tenant_catalog_mirror(session, restaurant_id)
    if not catalog_id:
        logger.info("send_catalog skipped: no catalog_id for restaurant %s", restaurant_id)
        return False

    # The catalogue SYNCED from Meta (the OPS "Sync from Meta" mirror) is the ONLY
    # source of truth in catalogue mode. STRICT, no fallback: if nothing has been
    # synced we send nothing rather than leak unsynced text-menu dishes as tappable
    # cards. The manager must press "Sync from Meta" first.
    if not synced:
        logger.info(
            "send_catalog skipped: catalogue not synced for restaurant %s "
            "(refusing to fall back to text-menu dishes)", restaurant_id
        )
        return False

    # The mirror's category column is NULL (Meta doesn't echo it), so resolve each
    # product's real category from its dish for grouping and the text fallback.
    _apply_category_map(synced, await _load_category_map(session, restaurant_id))

    # Only products Meta has finished processing (image on its CDN + approved) can be
    # sent in a product_list — including a still-"in review" product makes the WHOLE
    # message fail with #131009 "None of the products provided could be sent". So we
    # link only sendable products here; the rest stay in review (shown with a pill in
    # the dashboard) until the next Sync flips them sendable.
    sendable = [p for p in synced if p.is_sendable]
    if not sendable:
        # Everything is still in review → don't drop the customer. Reply with a text menu
        # they can order from by typing, so "menu" always gets an answer.
        await _send_catalog_text_fallback(
            session,
            restaurant_id=restaurant_id,
            to_phone=to_phone,
            products=synced,
            idempotency_key=idempotency_key,
        )
        logger.info(
            "send_catalog: %d product(s) still in review for restaurant %s — sent text "
            "menu fallback instead of an (un-sendable) product_list", len(synced), restaurant_id,
        )
        return True

    # Native catalogue view (the market-standard way to show a big menu): instead of
    # paginating cards 30 at a time, send ONE "View full menu" button that opens
    # WhatsApp's built-in catalogue UI. The customer browses EVERY product there — no
    # 30-card cap, no "Show more" — and Meta collections show as categories. Preferred
    # when enabled (default ON); the product_list / category-picker paths below are
    # fallbacks when native view is off or the catalogue button doesn't render.
    from app.identity.models import Restaurant

    rest = await session.get(Restaurant, restaurant_id)
    settings = (rest.settings or {}) if rest is not None else {}
    if await native_catalog_view_allowed(
        session, restaurant_id=restaurant_id, settings=settings
    ):
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=to_phone,
            msg_type=OutboundMessageType.CATALOG_MESSAGE,
            payload={
                "body": "Here's our full menu 😊 Tap *View full menu* to browse "
                        "everything, or just tell me what you'd like.",
                "footer": "Add dishes to your basket, then send it to order.",
                "thumbnail_product_retailer_id": sendable[0].retailer_id,
            },
            idempotency_key=idempotency_key or f"catalog-view-{restaurant_id}-{to_phone}-{uuid4().hex}",
        )
        logger.info(
            "sent native catalog view to %s for restaurant %s (%d sendable, thumb=%s)",
            to_phone, restaurant_id, len(sendable), sendable[0].retailer_id,
        )
        return True

    # Browse-by-category: a single product_list maxes out at 30 cards, so a big menu
    # (e.g. a POS pull of hundreds of dishes) would silently hide everything past the
    # first 30. When the manager turns this on AND there's more than one message worth
    # of dishes, send a tappable category picker instead; the customer taps a category
    # and gets that category's cards. Default off → unchanged single-list behaviour.
    if settings.get("catalog_browse_by_category") and len(sendable) > _PRODUCT_LIST_MAX:
        return await _render_category_page(
            session, restaurant_id=restaurant_id, to_phone=to_phone,
            products=sendable, page=0, idempotency_key=idempotency_key,
        )

    # Small menus (e.g. Lims with 4 dishes): ONE section only. WhatsApp's product_list
    # UI often shows the first section's carousel only — a 4th dish in a second
    # section (e.g. "Biryani" vs "Fried Chicken") never appears unless the customer
    # discovers the section switch, so they count 3 instead of 4 (prod Lims Jul 2026).
    if len(sendable) <= 10:
        payload_sections = [
            {
                "title": "Menu",
                "product_items": [
                    {"product_retailer_id": p.retailer_id} for p in sendable[:30]
                ],
            }
        ]
    else:
        # Group into sections by category (WhatsApp limits: <=10 sections, <=30
        # products total, section title <=24 chars). Stable, readable order.
        sections: dict[str, list[dict]] = {}
        total = 0
        for p in sendable:
            if total >= 30:
                break
            cat = _category_of(p)[:24]
            sections.setdefault(cat, []).append({"product_retailer_id": p.retailer_id})
            total += 1
        payload_sections = [
            {"title": title, "product_items": items}
            for title, items in list(sections.items())[:10]
        ]
    list_body = body[:1024]
    if len(sendable) > 1:
        list_body = (
            f"{list_body}\n\n👈 Swipe the cards to see all {len(sendable)} items."
        )[:1024]
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=to_phone,
        msg_type=OutboundMessageType.PRODUCT_LIST,
        payload={
            "header": header[:60],
            "body": list_body,
            "catalog_id": catalog_id,
            "sections": payload_sections,
        },
        idempotency_key=idempotency_key or f"catalog-send-{restaurant_id}-{to_phone}-{uuid4().hex}",
    )
    logger.info(
        "sent catalog to %s for restaurant %s: %d product(s) in %d section(s)",
        to_phone, restaurant_id, len(sendable), len(payload_sections),
    )
    return True


async def _send_catalog_text_fallback(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    products: list[CatalogProduct],
    idempotency_key: str | None = None,
) -> None:
    """Send a plain-text menu when no catalogue product is sendable yet (all in review).

    Lists the active products (name + price) grouped by category so the customer can
    still order by typing. Prevents the "menu" request from going unanswered while Meta
    finishes processing the product images. Caller commits."""
    lines: list[str] = ["Here's our menu 😊 Reply with what you'd like and we'll add it:"]
    current_cat: str | None = None
    for p in products[:40]:
        cat = _category_of(p)
        if cat != current_cat:
            lines.append(f"\n*{cat}*")
            current_cat = cat
        price = f" — AED {_aed(p.price_aed)}" if p.price_aed is not None else ""
        lines.append(f"• {p.name}{price}")
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=to_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "\n".join(lines)[:4096]},
        idempotency_key=(
            f"{idempotency_key}-textfallback" if idempotency_key
            else f"catalog-textfallback-{restaurant_id}-{to_phone}-{uuid4().hex}"
        ),
    )


async def _order_cart_snapshot(session, order_id: int) -> tuple[str, list[dict]]:
    """Resolve the resulting draft cart into (display_text, structured snapshot).

    display_text is a human basket line ('2x Chicken Biryani') used by the LLM
    history; the snapshot is the structured per-line array the interpreter reads.
    """
    from app.ordering.models import OrderItem

    items = list((await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order_id)
    )).all())
    snapshot: list[dict] = []
    parts: list[str] = []
    for it in items:
        snapshot.append({
            "cart_item_id": it.id,
            "dish": it.dish_name,
            "variant": it.variant_name,
            "note": it.notes,
            "qty": it.qty,
            "price": str(it.price_aed),
        })
        label = f"{it.qty}x {it.dish_name}"
        if it.variant_name:
            label += f" ({it.variant_name})"
        if it.notes:
            label += f" — {it.notes}"
        parts.append(label)
    return "; ".join(parts), snapshot


def _category_of(product: CatalogProduct) -> str:
    """Display category for a catalogue product; products with none bucket into "Menu".

    Prefers the category resolved from the linked dish (stashed on ``_resolved_category``
    by :func:`_apply_category_map`) because the Meta catalogue mirror
    (``catalog_products.category``) comes back NULL — Meta doesn't echo our category. The
    real category lives on the dish, so we resolve it at send time and fall back to the
    mirror column, then to "Menu"."""
    resolved = getattr(product, "_resolved_category", None)
    return ((resolved or product.category or "").strip()) or "Menu"


async def _load_category_map(session: AsyncSession, restaurant_id: int) -> dict[str, str]:
    """Map ``retailer_id -> dish category`` for a restaurant. The catalogue mirror
    doesn't carry category back from Meta, so the source of truth is the dish, linked by
    ``dishes.catalog_retailer_id == catalog_products.retailer_id``."""
    rows = (
        await session.execute(
            select(Dish.catalog_retailer_id, Dish.category).where(
                Dish.restaurant_id == restaurant_id,
                Dish.catalog_retailer_id.is_not(None),
            )
        )
    ).all()
    return {rid: cat for rid, cat in rows if rid and cat}


def _apply_category_map(products: list[CatalogProduct], cat_map: dict[str, str]) -> None:
    """Stash each product's dish category on a transient ``_resolved_category`` attribute
    (not a mapped column, so it never persists) for :func:`_category_of` to pick up."""
    for p in products:
        cat = cat_map.get(p.retailer_id)
        if cat:
            p._resolved_category = cat


async def _load_sendable_products(
    session: AsyncSession, restaurant_id: int
) -> tuple[str | None, list[CatalogProduct]]:
    """Return (catalog_id, sendable synced products) for browse-by-category helpers.
    catalog_id is None when the catalogue isn't configured."""
    catalog_id, synced = await _load_tenant_catalog_mirror(session, restaurant_id)
    if not catalog_id:
        return None, []
    sendable = [p for p in synced if p.is_sendable]
    _apply_category_map(sendable, await _load_category_map(session, restaurant_id))
    return catalog_id, sendable


def _ordered_categories(products: list[CatalogProduct]) -> list[tuple[str, int]]:
    """(category, count) pairs, largest category first then alphabetical — a stable
    order so pagination is deterministic across taps."""
    counts: dict[str, int] = {}
    for p in products:
        cat = _category_of(p)
        counts[cat] = counts.get(cat, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


async def _render_category_page(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    products: list[CatalogProduct],
    page: int = 0,
    idempotency_key: str | None = None,
) -> bool:
    """Send ONE page of the tappable category list. Each page holds up to 9 categories
    plus a "More categories" row (id ``catpage:<next>``) when further pages exist, so
    every category is reachable by tapping. Tapping a category replies ``cat:<name>``.
    Caller commits."""
    ordered = _ordered_categories(products)
    page = max(page, 0)
    start = page * _CAT_PAGE_SIZE
    page_cats = ordered[start:start + _CAT_PAGE_SIZE]
    if not page_cats:  # page past the end — nothing to show
        return False

    rows = [
        {
            "id": f"cat:{cat}"[:200],
            "title": cat[:24],
            "description": (f"{n} item" + ("s" if n != 1 else ""))[:72],
        }
        for cat, n in page_cats
    ]
    has_more = start + _CAT_PAGE_SIZE < len(ordered)
    if has_more:
        rows.append({
            "id": f"catpage:{page + 1}",
            "title": "More categories",
            "description": "See the rest of the menu",
        })

    body = (
        "Browse our menu by category 😊 Tap a category to see the dishes."
        if page == 0 else "More categories 😊 Tap one to see the dishes."
    )
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=to_phone,
        msg_type=OutboundMessageType.LIST,
        payload={
            "body": body[:1024],
            "button_label": "Categories",
            "sections": [{"title": "Categories", "rows": rows}],
        },
        idempotency_key=idempotency_key or f"catalog-cats-{restaurant_id}-{to_phone}-p{page}-{uuid4().hex}",
    )
    logger.info(
        "sent category page %d to %s for restaurant %s: %d categories (%d total, more=%s)",
        page, to_phone, restaurant_id, len(page_cats), len(ordered), has_more,
    )
    return True


async def send_catalog_categories(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    page: int = 0,
    idempotency_key: str | None = None,
) -> bool:
    """Send a page of the category picker (used by the "More categories" tap). Caller commits."""
    _catalog_id, sendable = await _load_sendable_products(session, restaurant_id)
    if not sendable:
        return False
    return await _render_category_page(
        session, restaurant_id=restaurant_id, to_phone=to_phone,
        products=sendable, page=page, idempotency_key=idempotency_key,
    )


async def send_catalog_category(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    category: str,
    offset: int = 0,
    idempotency_key: str | None = None,
) -> bool:
    """Send the product cards for ONE category (a browse-by-category tap), paginated 30
    at a time. When more than 30 remain a "More <category>" quick-reply (id
    ``catmore:<next_offset>:<category>``) follows so the whole category is reachable.
    Returns False if the catalogue isn't configured or the category has nothing sendable.
    Caller commits."""
    catalog_id, sendable = await _load_sendable_products(session, restaurant_id)
    if not catalog_id:
        return False

    wanted = (category or "").strip().lower()
    chosen = [p for p in sendable if _category_of(p).lower() == wanted]
    offset = max(offset, 0)
    window = chosen[offset:offset + _PRODUCT_LIST_MAX]
    if not window:
        if offset == 0:
            await enqueue_message(
                session,
                restaurant_id=restaurant_id,
                to_phone=to_phone,
                msg_type=OutboundMessageType.TEXT,
                payload={"body": "Nothing's available in that category right now 🙏 "
                                 "Type a dish name and I'll add it for you 😊"},
                idempotency_key=(
                    f"{idempotency_key}-empty" if idempotency_key
                    else f"catalog-cat-empty-{restaurant_id}-{to_phone}-{uuid4().hex}"
                ),
            )
        return False

    title = _category_of(window[0])[:24]
    items = [{"product_retailer_id": p.retailer_id} for p in window]
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=to_phone,
        msg_type=OutboundMessageType.PRODUCT_LIST,
        payload={
            "header": title[:60],
            "body": "Tap an item to add it to your basket, then send the basket to order 😊",
            "catalog_id": catalog_id,
            "sections": [{"title": title, "product_items": items}],
        },
        idempotency_key=idempotency_key or f"catalog-cat-{restaurant_id}-{to_phone}-o{offset}-{uuid4().hex}",
    )

    # A product_list can't carry a navigation row, so when the category has more than 30
    # dishes we follow up with a quick-reply that loads the next 30.
    next_offset = offset + _PRODUCT_LIST_MAX
    if next_offset < len(chosen):
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=to_phone,
            msg_type=OutboundMessageType.BUTTONS,
            payload={
                "body": f"More dishes in {title}? Tap below to see the next {min(_PRODUCT_LIST_MAX, len(chosen) - next_offset)}."[:1024],
                "buttons": [{"id": f"catmore:{next_offset}:{category}"[:256], "title": "Show more"}],
            },
            idempotency_key=(
                f"{idempotency_key}-more" if idempotency_key
                else f"catalog-cat-more-{restaurant_id}-{to_phone}-o{next_offset}-{uuid4().hex}"
            ),
        )

    logger.info(
        "sent category '%s' (offset %d) to %s for restaurant %s: %d product(s), more=%s",
        title, offset, to_phone, restaurant_id, len(items), next_offset < len(chosen),
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
    if not product_items and isinstance(payload.get("productitems"), list):
        product_items = payload["productitems"]
    if not product_items:
        return

    # The catalogue basket fills the SAME conversation + cart the text bot uses, then
    # leaves the customer in the normal "collecting_items" state. So after the basket
    # everything is identical to the text flow: the customer sends 'done' and the
    # conversation engine drives delivery, confirmation, kitchen and dispatch. We reuse
    # the engine's helpers (lazy import) so behaviour cannot drift from the text path.
    from app.conversation.engine import (
        _build_cart_summary, _post_add_extras, _send_buttons, _send_text, _set_state,
    )
    from app.conversation.service import get_or_create_conversation, record_message
    from app.identity.phones import normalize_phone

    # Normalize so the catalogue basket lands on the SAME conversation thread the
    # text bot uses (F71/R-027) — handle_inbound already normalizes; without this
    # the raw Meta digits-only phone (no leading '+') splits into a second row.
    _phone = normalize_phone(inbound.from_phone)
    conv = await get_or_create_conversation(
        session, restaurant_id=restaurant_id, phone=_phone, counterpart="customer",
    )
    # Manual takeover: a human runs this thread — record the basket so the
    # manager sees it, but never auto-process or reply over them (same contract
    # as handle_inbound; this path used to bypass takeover entirely).
    if conv.manual_takeover:
        await record_message(
            session,
            conversation_id=conv.id,
            direction="inbound",
            wa_message_id=inbound.wa_message_id,
            msg_type=str(inbound.type),
            payload=dict(payload),
            ts=inbound.timestamp,
        )
        return
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=_phone
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
        # A NEW order: clear any address/location state left over from a previous order
        # so a returning customer is re-offered their saved address (and the fee/distance
        # is recomputed for THIS order), exactly like the engine's text path does.
        _set_state(
            conv, draft_order_id=order.id, address_offer_made=None,
            saved_address_declined=None, saved_address_id=None,
            pin_lat=None, pin_lon=None, distance_km=None, distance_source=None, delivery_fee=None,
        )

    from app.identity.models import Restaurant
    from app.ordering.quantity_policy import QuantityError, QuantityPolicy

    _CENT = Decimal("0.01")
    rest = await session.get(Restaurant, restaurant_id)
    policy = QuantityPolicy.from_restaurant(rest)

    added = 0
    unmapped: list[str] = []
    price_mismatch: list[str] = []  # tapped price drifted from the catalogue price
    oversized: list[str] = []  # per-line quantity over the tenant guard (R-050)
    for item in product_items:
        retailer_id = _retailer_id_from_item(item)
        try:
            qty = max(1, int(item.get("quantity", 1)))
        except (TypeError, ValueError):
            qty = 1
        if not retailer_id or not await product_belongs_to_restaurant(
            session, restaurant_id=restaurant_id, retailer_id=retailer_id
        ):
            price = _to_decimal(item.get("item_price"))
            unmapped.append(
                f"{qty}x item {retailer_id or '?'}"
                + (f" (AED {_aed(price)})" if price else "")
            )
            continue
        dish = await _find_dish(session, restaurant_id=restaurant_id, retailer_id=retailer_id)
        # STRICT catalogue membership: only add an item that is backed by an ACTIVE
        # synced CatalogProduct. A dish linked to a retailer_id that was never synced
        # (or has since gone inactive/out of stock) must never sneak into the cart.
        product = await session.scalar(
            select(CatalogProduct).where(
                CatalogProduct.restaurant_id == restaurant_id,
                CatalogProduct.retailer_id == retailer_id,
                CatalogProduct.is_active.is_(True),
            ).limit(1)
        )
        # Also reject a dish the manager turned OFF today, directly on dish.is_available —
        # a Meta pull can reset CatalogProduct.is_active to True, so is_active alone isn't
        # a reliable availability gate for a tapped catalogue card. Same for the manager's
        # per-dish WhatsApp switch (whatsapp_enabled=False, TX-45) — never let a disabled
        # dish sneak into the cart via a stale catalogue card.
        if (
            dish is None
            or dish.price_aed is None
            or product is None
            or not dish.is_available
            or not getattr(dish, "whatsapp_enabled", True)
        ):
            price = _to_decimal(item.get("item_price"))
            unmapped.append(
                f"{qty}x item {retailer_id}" + (f" (AED {_aed(price)})" if price else "")
            )
            continue

        # R-050: per-line max-quantity guard — parity with the typed-order path. A
        # malformed/replayed basket with a huge quantity never mutates the cart.
        try:
            policy.check_line(qty)
        except QuantityError:
            oversized.append(f"{qty}x {dish.name}")
            continue

        # R-051 / R-019: snapshot the TAPPED Meta ``item_price`` onto the order line,
        # not the (possibly stale) local Dish.price_aed. If the tapped price and the
        # tenant catalogue price disagree beyond a cent, BLOCK the item and force a
        # resync rather than silently under/overcharge.
        item_price = _to_decimal(item.get("item_price"))
        price_override: Decimal | None = None
        if item_price is not None and product.price_aed is not None:
            if abs(item_price - Decimal(product.price_aed)) > _CENT:
                price_mismatch.append(
                    f"{dish.name} (card AED {_aed(item_price)} vs menu AED {_aed(product.price_aed)})"
                )
                continue
            price_override = item_price

        await add_item(
            session, order=order, dish=dish, qty=qty, price_aed_override=price_override
        )
        added += 1

    if not added:
        await record_message(
            session, conversation_id=conv.id, direction="inbound",
            wa_message_id=inbound.wa_message_id, msg_type="order",
            payload={"product_items": product_items, "display_text": "", "cart_snapshot": []},
            ts=inbound.timestamp or int(time.time()),
        )
        if price_mismatch:
            body = (
                "Sorry, the price changed for " + "; ".join(price_mismatch) + ". "
                "Please reopen the menu to see the current price, or type your order 😊"
            )
        elif oversized:
            body = (
                "That's a large quantity for " + "; ".join(oversized) + ". "
                "Please reply with a smaller amount, or call us for bulk orders 🙏"
            )
        else:
            body = (
                "Thanks 🙏 We couldn't match those items to our menu yet. "
                "Please type your order and we'll help you right away 😊"
            )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="catalog-empty",
            body=body,
        )
        logger.info("catalog basket with no addable items for restaurant %s", restaurant_id)
        return

    # Hand control to the normal flow: same state the text bot is in after adding items.
    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")

    # Faithful ORDER record: persist a readable basket + structured snapshot so the
    # LLM history (engine._build_history) renders dish names, not "[order]" (DB-H8).
    _display_text, _cart_snapshot = await _order_cart_snapshot(session, order.id)
    await record_message(
        session, conversation_id=conv.id, direction="inbound",
        wa_message_id=inbound.wa_message_id, msg_type="order",
        payload={
            "product_items": product_items,
            "display_text": _display_text,
            "cart_snapshot": _cart_snapshot,
        },
        ts=inbound.timestamp or int(time.time()),
    )

    cart = await _build_cart_summary(session, conv)
    notes: list[str] = []
    if unmapped:
        notes.append("We couldn't add: " + "; ".join(unmapped))
    if price_mismatch:
        notes.append(
            "Price changed (reopen the menu for the latest): " + "; ".join(price_mismatch)
        )
    if oversized:
        notes.append("Quantity too large: " + "; ".join(oversized))
    extra = ("\n" + "\n".join(notes)) if notes else ""
    upsell_line, buttons = await _post_add_extras(
        session, conv, restaurant_id, order
    )
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="catalog-cart",
        body=f"Got your basket 🎉\n\n🛒 {cart}{extra}{upsell_line}",
        buttons=buttons,
    )
    logger.info(
        "catalog basket -> order %s for restaurant %s: %d line(s), subtotal %s",
        order.order_number, restaurant_id, added, order.subtotal,
    )
