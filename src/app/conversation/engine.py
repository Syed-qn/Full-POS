import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.conversation.models import Conversation
from app.conversation.service import get_or_create_conversation, record_message
from app.ordering.matching import MatchConfidence, find_dish_matches, resolve_variant
from app.outbox.service import enqueue_message
from app.whatsapp.port import InboundMessage, MessageType, OutboundMessageType


import re as _re

_logger = logging.getLogger(__name__)


def _aed(value) -> str:
    """Format a money value as a plain AED amount string.

    Strips trailing zeros (18.00 -> "18", 18.50 -> "18.5") but, unlike a bare
    Decimal.normalize(), never emits scientific notation: Decimal('50').normalize()
    is Decimal('5E+1'), which previously rendered as "AED 5E+1" in customer
    messages. The ':f' presentation type forces fixed-point output.
    """
    return f"{Decimal(value).normalize():f}"


# A menu line looks like "• Chicken Biryani — AED 28" or "5. Chicken Biryani — AED 28"
# (leading bullet or number, any dash/colon, any currency).
_MENU_LINE = _re.compile(
    r"^\s*(?:\d+[\.\)]|[•\-\*])\s+.+?(?:AED|aed|Rs\.?|₹|\$)\s*\d", _re.MULTILINE
)


def _looks_like_menu(text: str) -> bool:
    """True if an AI reply appears to list dishes+prices (≥2 menu-ish lines).

    Safety net: the LLM sometimes fabricates an entire menu in free text. Any
    such reply in the ordering phase is replaced with the real DB menu before it
    reaches the customer.
    """
    return len(_MENU_LINE.findall(text or "")) >= 2


def _is_menu_request(text: str) -> bool:
    """True for short, explicit 'show me the menu' messages (lowercased).

    Kept tight (short message + menu/list keyword) so normal ordering text like
    'add the chicken from the menu' isn't intercepted — the AI's show_menu action
    covers the natural-language cases.
    """
    t = text.strip()
    if not t or len(t) > 40:
        return False
    keywords = ("menu", "full menu", "show menu", "see menu", "the list", "what do you have",
                "what do you serve", "options")
    return any(k in t for k in keywords)


# Words that, on their own, mean "hello" (a greeting = start a fresh order).
_GREET_WORDS = frozenset({
    "hi", "hii", "hiii", "hey", "heya", "hello", "helo", "hellow", "yo", "yoo",
    "salam", "salaam", "salams", "asalam", "asalaam", "assalam", "assalaam",
    "assalamu", "asalamualaikum", "assalamualaikum", "salamualaikum",
    "alaikum", "alaykum", "aleikum", "walaikum", "walekum", "waalaikum",
    "namaste", "marhaba", "ahlan", "hala", "greetings", "start",
    "morning", "afternoon", "evening",
})
# Filler words allowed to surround a greeting without making it "not a greeting".
_GREET_FILLER = frozenset({
    "as", "o", "u", "wa", "there", "everyone", "team", "bro", "sir", "maam",
    "madam", "good", "and", "the", "a", "dear", "please",
})


def _is_tracking_query(text: str | None) -> bool:
    """True for short 'where is my order / show me the live location' messages.

    Routed deterministically to the status handler so re-sharing the live tracking
    link never depends on the LLM correctly classifying it (it sometimes replied
    "let me check…" and never sent the link).
    """
    if not text:
        return False
    t = text.strip().lower()
    if not t or len(t) > 60:
        return False
    phrases = (
        "where is my order", "where's my order", "where is my food",
        "where is my rider", "where is the rider", "where is my delivery",
        "track my order", "track order", "tracking", "live location",
        "live tracking", "see location", "see the location", "rider location",
        "track rider", "where is it", "status of my order", "order status",
    )
    return any(p in t for p in phrases)


def _is_restaurant_location_request(text: str | None) -> bool:
    """True when the customer is asking WHERE THE RESTAURANT is (to self-pickup /
    "I'll come direct"), so we send the restaurant's location pin deterministically.

    Without this the LLM (which only has the restaurant's area name in context, no
    pin) improvises and asks the CUSTOMER to share THEIR location — which both
    fails the request and can push them into the address-capture flow.
    """
    if not text:
        return False
    t = text.strip().lower()
    if not t or len(t) > 80:
        return False
    phrases = (
        "restaurant location", "restaurant address", "your location", "your address",
        "your exact location", "exact location", "where are you located",
        "where is the restaurant", "where's the restaurant", "where is your restaurant",
        "where are you", "where r u", "location pin", "send location", "share location",
        "pickup location", "pick up location", "pickup address", "self pickup",
        "i will come", "i'll come", "ill come", "come direct", "come and collect",
        "collect myself", "collect it myself", "pick it up myself", "pick up myself",
    )
    return any(p in t for p in phrases)


def _is_pure_greeting(text: str | None) -> bool:
    """True if the message is ONLY a greeting, with no ordering content.

    A greeting means "start fresh", so we only treat a message as one when every
    word is a greeting or filler token — e.g. "hi", "As salam walekum",
    "hello there", "good morning". "hi I want biryani" is NOT a pure greeting and
    must reach the ordering flow so the dish still gets added.
    """
    if not text:
        return False
    tokens = _re.findall(r"[a-z]+", text.lower())
    if not tokens or len(tokens) > 6:
        return False
    if not any(t in _GREET_WORDS for t in tokens):
        return False
    return all(t in _GREET_WORDS or t in _GREET_FILLER for t in tokens)


_CATEGORY_EMOJI: tuple[tuple[tuple[str, ...], str], ...] = (
    (("biryani", "rice", "pulao"), "🍛"),
    (("bread", "naan", "roti", "paratha"), "🍞"),
    (("curry", "curries", "gravy", "masala"), "🥘"),
    (("starter", "appetizer", "appetiser", "snack", "tikka", "kebab", "grill"), "🍢"),
    (("drink", "beverage", "lassi", "juice", "shake", "tea", "coffee"), "🥤"),
    (("dessert", "sweet", "ice", "kulfi"), "🍨"),
    (("salad",), "🥗"),
    (("soup",), "🍲"),
)


def _category_emoji(category: str) -> str:
    """Pick a tasteful emoji for a menu category by keyword, default 🍽️.

    Categories are restaurant-defined free text, so this is a best-effort match
    on common words — anything unrecognised falls back to the generic plate.
    """
    c = (category or "").lower()
    for keywords, emoji in _CATEGORY_EMOJI:
        if any(k in c for k in keywords):
            return emoji
    return "🍽️"


async def _render_menu(session: AsyncSession, restaurant_id: int) -> str:
    """Render the active menu as categorized text."""
    from app.menu.models import Dish, Menu

    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if menu is None:
        return "Our menu is currently unavailable. Please try again later."

    dishes = await session.scalars(
        select(Dish)
        .where(Dish.menu_id == menu.id, Dish.is_available == True)  # noqa: E712
        .order_by(Dish.category, Dish.dish_number)
    )
    dish_list = list(dishes)
    if not dish_list:
        return "Our menu is currently unavailable. Please try again later."

    lines: list[str] = ["👋 *Welcome! Here's our menu*"]
    current_category: str | None = None
    for dish in dish_list:
        if dish.category != current_category:
            current_category = dish.category
            if current_category:
                lines.append(f"\n{_category_emoji(current_category)} *{current_category}*")
        price = _aed(dish.price_aed)
        lines.append(f"• {dish.name} — AED {price}")

    lines.append("\nJust tell me what you'd like and I'll add it to your order 😊")
    return "\n".join(lines)


async def _handle_greeting(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Send uploaded menu files (image/PDF) then a short prompt; fall back to text menu."""
    import base64

    from app.config import get_settings
    from app.menu.models import Menu, MenuFile
    from app.menu.storage import FileBlobStore

    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )

    files_sent = 0
    if menu is not None:
        menu_files = list(
            (
                await session.scalars(
                    select(MenuFile).where(MenuFile.menu_id == menu.id)
                )
            ).all()
        )
        store = FileBlobStore(get_settings().upload_dir)
        for mf in menu_files:
            # Only send image or PDF files — skip txt/csv/other non-media formats
            is_image = mf.content_type.startswith("image/")
            is_pdf = mf.content_type == "application/pdf"
            if not (is_image or is_pdf):
                continue
            data = store.get(restaurant_id=restaurant_id, digest=mf.sha256)
            if data is None:
                continue
            b64 = base64.b64encode(data).decode()
            if is_image:
                msg_type = OutboundMessageType.IMAGE
                payload: dict = {
                    "data": b64,
                    "content_type": mf.content_type,
                    "caption": mf.original_filename or "Menu",
                }
            else:
                msg_type = OutboundMessageType.DOCUMENT
                payload = {
                    "data": b64,
                    "content_type": mf.content_type,
                    "filename": mf.original_filename or "menu.pdf",
                    "caption": "Our menu",
                }
            await enqueue_message(
                session,
                restaurant_id=restaurant_id,
                to_phone=inbound.from_phone,
                msg_type=msg_type,
                payload=payload,
                idempotency_key=f"greeting-file-{mf.sha256[:16]}-{conv.id}-{inbound.wa_message_id}",
            )
            files_sent += 1

    conv.state = {**conv.state, "dialogue_state": "menu_sent"}

    if files_sent > 0:
        # Short prompt so the customer knows to reply with a dish
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="greeting-prompt",
            body="Here's our menu! 😊 Reply with a dish name to order.",
        )
    else:
        # No image/PDF on file — send the full text menu
        menu_text = await _render_menu(session, restaurant_id)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="greeting-menu",
            body=menu_text,
        )
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="conversation",
        entity_id=str(conv.id),
        action="state_transition",
        before={"dialogue_state": "greeting"},
        after={"dialogue_state": "menu_sent"},
    )


def _set_state(conv: Conversation, **updates) -> None:
    """Merge keys into conv.state (JSONB) without losing existing keys."""
    conv.state = {**conv.state, **updates}


async def _send_text(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
) -> None:
    import time

    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="text",
        payload={"body": body},
        ts=int(time.time()),
    )


async def _send_buttons(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
    buttons: list[dict],
) -> None:
    import time

    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={"body": body, "buttons": buttons},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="buttons",
        payload={"body": body, "buttons": buttons},
        ts=int(time.time()),
    )


async def _send_cta_url(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
    button_label: str,
    url: str,
) -> None:
    """Send a tappable URL button (CTA URL) to the customer — e.g. the live
    tracking link as a "Track your rider" button instead of a raw link. The
    customer is mid-order (24h window open), so a free-form interactive button
    delivers without a pre-approved template."""
    import time

    payload = {"body": body, "button_label": button_label, "url": url}
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.CTA_URL,
        payload=payload,
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="cta_url",
        payload={"type": "cta_url", **payload},
        ts=int(time.time()),
    )


async def _send_location_request(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
) -> None:
    """Ask for the delivery pin via WhatsApp's NATIVE location-request message — a
    "Send location" button that opens the customer's map picker so they share a
    real GPS pin (→ LOCATION inbound).

    A plain reply button can't trigger location sharing: tapping it just sends a
    button reply, which had no handler and looped back to the same prompt. The
    location_request_message is the correct mechanism.
    """
    import time

    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.LOCATION_REQUEST,
        payload={"body": body},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="location_request",
        payload={"body": body},
        ts=int(time.time()),
    )


async def _handle_collecting_items(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Parse dish name/number + qty from free text; add, disambiguate, or retry."""
    from app.ordering.models import Order
    from app.ordering.service import (
        add_item,
        create_draft_order,
        get_or_create_customer,
        parse_qty_and_text,
    )

    if inbound.type != MessageType.TEXT:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="need-text",
            body="Please type the name or number of a dish from the menu.",
        )
        return

    text = (inbound.payload.get("text") or "").strip()
    qty, dish_query = parse_qty_and_text(text)

    # "done" → proceed to delivery details (only if at least one item exists).
    if dish_query.lower() in ("done", "checkout", "that's all", "thats all"):
        draft_order_id = conv.state.get("draft_order_id")
        if not draft_order_id:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="empty-cart",
                body="Your cart is empty. Please add at least one dish before proceeding.",
            )
            return
        _set_state(conv, dialogue_state="address_capture")
        await _send_location_request(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ask-location",
            body="Great! Please share your delivery location 📍 — tap the button below to send your pin.",
        )
        return

    # "What is X?" dish question → describer.
    if dish_query.lower().startswith("what is "):
        from app.llm.factory import get_describer

        item_name = dish_query[8:].strip().rstrip("?")
        desc = get_describer().describe(item_name, "")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="dish-desc", body=desc,
        )
        return

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)

    if result.confidence == MatchConfidence.NO_MATCH:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-match",
            body="Sorry, I couldn't find that dish. Please reply with the dish "
                 "name from the menu, or try a different spelling.",
        )
        return

    if result.confidence == MatchConfidence.AMBIGUOUS:
        # Let LLM arbiter resolve ambiguity — avoids ping-pong with the customer.
        from app.llm.factory import get_arbiter
        try:
            dish = await get_arbiter().arbitrate(dish_query, result.candidates[:3])
        except Exception:
            dish = None
        if dish is None:
            options = " or ".join(
                f"{d.name} (AED {_aed(d.price_aed)})"
                for d in result.candidates[:3]
            )
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ambiguous",
                body=f"Did you mean {options}? Just reply with the dish name.",
            )
            return
        # Arbiter resolved — fall through to add item below.

    # DIRECT match or arbiter-resolved → add to draft order.
    dish = dish if result.confidence == MatchConfidence.AMBIGUOUS else result.candidates[0]
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        order = await create_draft_order(
            session, restaurant_id=restaurant_id, customer_id=customer.id,
        )
        _set_state(conv, draft_order_id=order.id)

    await add_item(session, order=order, dish=dish, qty=qty)
    _set_state(conv, dialogue_state="collecting_items")

    price = _aed(dish.price_aed)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="item-added",
        body=(
            f"Added {qty}x {dish.name} (AED {price}).\n"
            f"Reply with more items, or send 'done' to proceed to delivery details."
        ),
    )


async def _fee_settings_for(session: AsyncSession, restaurant_id: int) -> dict | None:
    """Load the restaurant's configured delivery-fee tiers (Settings → Fees) in the
    shape ``calculate_fee`` expects, so the bot charges the manager's real tiers
    instead of the hardcoded spec defaults. Returns None when unconfigured."""
    from app.identity.models import Restaurant
    from app.ordering.fees import fee_settings_from_restaurant

    restaurant = await session.get(Restaurant, restaurant_id)
    return fee_settings_from_restaurant(restaurant.settings if restaurant else None)


async def _road_distance_km(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> float:
    """Distance (km) restaurant → customer via the configured geo provider.

    Uses the GeoPort (``google_maps`` → traffic-aware road distance) so the fee
    and radius the customer is quoted match real driving distance, not a
    straight line. The provider's HTTP client is sync, so it's run in a thread
    to avoid blocking the event loop. The provider already degrades to haversine
    internally on any API failure; this wrapper adds a final haversine fallback
    so a provider/config error can never break ordering.
    """
    import asyncio

    from app.geo.factory import get_geo_provider
    from app.geo.haversine import distance_km as _haversine

    try:
        return await asyncio.to_thread(
            get_geo_provider().distance_km, lat1, lng1, lat2, lng2
        )
    except Exception:  # noqa: BLE001 - never let geo break ordering
        return _haversine(lat1, lng1, lat2, lng2)


def _hours_info(restaurant) -> str:
    """Grounded opening-hours line for the AI prompt.

    Unconfigured hours mean "always open" — so instruct the model NOT to invent
    specific open/close times (it was answering '11 AM to 11 PM' from nowhere).
    When configured, state the live open/closed status.
    """
    open_hours = (restaurant.settings or {}).get("open_hours") if restaurant else None
    if not open_hours or not open_hours.get("days"):
        return (
            "No fixed opening hours are posted — do NOT state specific open/close "
            "times; assume we're available to take orders now."
        )
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.conversation.hours import (
        _fmt_time,
        _window_for,
        is_open,
        next_opening_label,
    )

    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    parts = []
    for wd in range(7):
        window = _window_for(open_hours, wd)
        if window:
            parts.append(f"{labels[wd]} {_fmt_time(window[0])}–{_fmt_time(window[1])}")
        else:
            parts.append(f"{labels[wd]} closed")
    schedule = "; ".join(parts)

    now = datetime.now(ZoneInfo("Asia/Dubai"))
    if is_open(open_hours, now):
        status = "currently OPEN"
    else:
        nxt = next_opening_label(open_hours, now)
        status = f"currently CLOSED, next opening {nxt}" if nxt else "currently closed"
    return f"Opening hours — {schedule}. We are {status}."


async def _finalize_with_stored_address(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    stored,
    *,
    rest_lat: float,
    rest_lng: float,
) -> None:
    """Attach a returning customer's saved address to the draft and summarise."""
    from datetime import datetime, timezone

    from app.ordering.fees import UndeliverableError, calculate_fee, radius_km
    from app.ordering.models import Order

    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-draft-saved",
            body="Your cart is empty. Please send 'hi' to start a new order.",
        )
        return

    dist = None
    fee = Decimal("0.00")
    if stored.latitude is not None and stored.longitude is not None:
        dist = await _road_distance_km(rest_lat, rest_lng, stored.latitude, stored.longitude)
        settings = await _fee_settings_for(session, restaurant_id)
        try:
            fee = calculate_fee(dist, settings)
        except UndeliverableError:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="undeliverable-saved",
                body="Sorry, your saved address is outside our delivery area "
                     f"(maximum {radius_km(settings):g} km). Please share a new location.",
            )
            return

    order.address_id = stored.id
    order.distance_km = dist
    order.delivery_fee_aed = fee
    order.total = order.subtotal + fee
    stored.last_used_at = datetime.now(timezone.utc)
    await session.flush()

    _set_state(conv, dialogue_state="order_confirmation", pending_order_id=order.id)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _handle_address_capture(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Capture delivery address: location pin (fee/radius check) or text address."""
    from app.identity.models import Restaurant
    from app.ordering.fees import UndeliverableError, calculate_fee, radius_km
    from app.ordering.service import get_last_address, get_or_create_customer

    restaurant = await session.get(Restaurant, restaurant_id)
    rest_lat = restaurant.lat if restaurant else 25.2048
    rest_lng = restaurant.lng if restaurant else 55.2708

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )

    # Button reply on a previously-offered saved address.
    if inbound.type == MessageType.BUTTON_REPLY:
        btn_id = inbound.payload.get("id", "")
        if btn_id == "use_saved_address":
            stored = await get_last_address(session, customer.id)
            if stored is not None:
                await _finalize_with_stored_address(
                    session, conv, inbound, restaurant_id, stored,
                    rest_lat=rest_lat, rest_lng=rest_lng,
                )
                return
        if btn_id == "new_address":
            _set_state(conv, address_offer_made=True)
            await _send_location_request(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ask-location",
                body="Please share your delivery location 📍 — tap the button below to send your pin.",
            )
            return

    # Returning customer: offer the saved address once before asking for a pin.
    if not conv.state.get("address_offer_made"):
        stored = await get_last_address(session, customer.id)
        if stored is not None:
            _set_state(conv, address_offer_made=True)
            label = ", ".join(
                p for p in (stored.room_apartment, stored.building) if p
            ) or "your saved address"
            await _send_buttons(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="offer-saved-addr",
                body=f"Welcome back! Deliver to your saved address ({label})?",
                buttons=[
                    {"id": "use_saved_address", "title": "Use saved address"},
                    {"id": "new_address", "title": "New address"},
                ],
            )
            return

    if inbound.type == MessageType.LOCATION:
        lat = inbound.payload["latitude"]
        lon = inbound.payload["longitude"]
        dist = await _road_distance_km(rest_lat, rest_lng, lat, lon)
        settings = await _fee_settings_for(session, restaurant_id)
        try:
            fee = calculate_fee(dist, settings)
        except UndeliverableError:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="undeliverable",
                body="Sorry, your location is outside our delivery area "
                     f"(maximum {radius_km(settings):g} km). We can't deliver there.",
            )
            return

        await get_or_create_customer(
            session, restaurant_id=restaurant_id, phone=inbound.from_phone,
        )
        _set_state(
            conv,
            pin_lat=lat, pin_lon=lon,
            distance_km=dist, delivery_fee=str(fee),
            dialogue_state="address_text_pending",
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ask-text-addr",
            body="Got it! Please send your room/apartment number and building, "
                 "separated by a comma.\nExample: 101, Tower A",
        )
        return

    # Text address: expect "room/apartment, building".
    text = (inbound.payload.get("text") or "").strip()
    if "," not in text:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="addr-format",
            body="Please include a comma between your room/apartment and building.\n"
                 "Example: 101, Tower A",
        )
        return

    room_apartment, building = (p.strip() for p in text.split(",", 1))
    _set_state(
        conv,
        pending_room=room_apartment,
        pending_building=building,
        dialogue_state="receiver_details",
    )
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="ask-receiver",
        body=f"Address noted: room/apartment number {room_apartment} building {building}.\n"
             f"Who should the rider ask for? Please reply with the receiver's name.",
    )


async def _handle_receiver_details(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Capture the receiver name, persist the address + order, then summarise."""
    from app.ordering.fees import calculate_fee
    from app.ordering.models import Order
    from app.ordering.service import get_or_create_customer, upsert_address

    receiver_name = (inbound.payload.get("text") or "").strip()
    if not receiver_name:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ask-receiver-again",
            body="Please reply with the receiver's name.",
        )
        return

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )
    addr = await upsert_address(
        session,
        customer_id=customer.id,
        latitude=conv.state.get("pin_lat"),
        longitude=conv.state.get("pin_lon"),
        room_apartment=conv.state.get("pending_room", ""),
        building=conv.state.get("pending_building", ""),
        receiver_name=receiver_name,
        confirmed=True,
    )

    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-draft",
            body="Your cart is empty. Please send 'hi' to start a new order.",
        )
        return

    dist = conv.state.get("distance_km")
    if conv.state.get("delivery_fee"):
        fee = Decimal(conv.state.get("delivery_fee", "0.00"))
    else:
        fee = calculate_fee(
            dist if dist is not None else 0.0,
            await _fee_settings_for(session, restaurant_id),
        )
    order.address_id = addr.id
    order.distance_km = dist
    order.delivery_fee_aed = fee
    order.total = order.subtotal + fee
    await session.flush()

    _set_state(conv, dialogue_state="order_confirmation", pending_order_id=order.id)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _send_order_summary(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    order,
) -> None:
    """Render order summary with totals + ETA and confirm/cancel buttons."""
    from app.ordering.models import CustomerAddress, OrderItem
    from app.weather.factory import get_weather_port

    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    item_lines = "\n".join(
        f"  {it.qty}x {it.dish_name}"
        f"{f' ({it.variant_name})' if it.variant_name else ''} — "
        f"AED {_aed(it.price_aed * it.qty)}"
        for it in items
    )

    # Show the delivery address back to the customer so they can verify it before
    # confirming (room/apartment, building, receiver — pin already captured).
    address_block = ""
    if order.address_id is not None:
        addr = await session.get(CustomerAddress, order.address_id)
        if addr is not None:
            parts = [p for p in (addr.room_apartment, addr.building) if p]
            addr_line = ", ".join(parts)
            if addr.receiver_name:
                addr_line = f"{addr_line} (for {addr.receiver_name})" if addr_line else f"For {addr.receiver_name}"
            if addr_line:
                address_block = f"Deliver to: {addr_line}\n"

    # Weather disclosure: if a delay is active, disclose at confirmation time so
    # that a later weather-caused delay does NOT trigger an automatic coupon.
    weather_note = ""
    if get_weather_port().is_delay_active():
        order.weather_delay_disclosed = True
        weather_note = (
            "\nNote: severe weather may delay delivery beyond the usual time."
        )
        await session.flush()

    summary = (
        f"Order summary:\n{item_lines}\n\n"
        f"Subtotal: AED {_aed(order.subtotal)}\n"
        f"Delivery fee: AED {_aed(order.delivery_fee_aed)}\n"
        f"Total: AED {_aed(order.total)}\n"
        f"Payment: COD (cash on delivery)\n"
        f"{address_block}"
        f"ETA: 40 minutes{weather_note}\n\n"
        f"Confirm your order?"
    )
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-summary", body=summary,
        buttons=[
            {"id": "confirm_order", "title": "Confirm order"},
            {"id": "cancel_order", "title": "Cancel"},
        ],
    )


async def _handle_order_confirmation(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Handle confirm/cancel buttons on the order summary."""
    from app.ordering.fsm import OrderStatus
    from app.ordering.fsm import transition as fsm_transition
    from app.ordering.models import Order
    from app.ordering.service import finalize_confirmation

    order_id = conv.state.get("pending_order_id")
    order = await session.get(Order, order_id) if order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-pending-order",
            body="There is no order to confirm. Send 'hi' to start a new order.",
        )
        return

    btn_id = inbound.payload.get("id", "") if inbound.type == MessageType.BUTTON_REPLY else ""

    if btn_id == "confirm_order":
        await finalize_confirmation(session, order=order, actor="customer")
        _set_state(conv, dialogue_state="order_placed")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-confirmed",
            body=(
                f"Order confirmed! Order #{order.order_number}.\n"
                f"Total: AED {_aed(order.total)} "
                f"(COD — cash on delivery).\n"
                f"Your food will arrive within 40 minutes."
            ),
        )
        return

    if btn_id == "cancel_order":
        if order.status in (OrderStatus.DRAFT, OrderStatus.PENDING_CONFIRMATION):
            await fsm_transition(session, order, OrderStatus.CANCELLED, actor="customer")
        _set_state(conv, dialogue_state="cancelled", draft_order_id=None, pending_order_id=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-cancelled",
            body="No problem — your order has been cancelled. Send 'hi' to start again.",
        )
        return

    # Unknown input while awaiting confirmation → re-prompt with the summary.
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _handle_modify_intent(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Start modify flow: lookup recent modifiable order (conv.state pending/ modify_order_id or by phone like status query).
    If before ready, set modify_items + empty proposed; prompt for new items (SLA restart noted).
    """
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order, OrderItem

    order = None
    mod_id = conv.state.get("modify_order_id") or conv.state.get("pending_order_id")
    if mod_id:
        order = await session.get(Order, mod_id)

    if order is None:
        customer = await session.scalar(
            select(Customer).where(
                Customer.restaurant_id == restaurant_id,
                Customer.phone == inbound.from_phone,
            )
        )
        if customer:
            terminal = {
                str(OrderStatus.DELIVERED), str(OrderStatus.CANCELLED),
                str(OrderStatus.UNDELIVERABLE), str(OrderStatus.RESOLD),
                str(OrderStatus.WRITTEN_OFF),
            }
            order = await session.scalar(
                select(Order)
                .where(
                    Order.restaurant_id == restaurant_id,
                    Order.customer_id == customer.id,
                    Order.status.notin_(terminal),
                )
                .order_by(Order.created_at.desc())
                .limit(1)
            )

    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-no-order",
            body="You don't have any active orders to modify. Send 'hi' to place a new order.",
        )
        return

    # Mirror service _NON_MODIFIABLE_STATUSES (strings for safety, no private cross)
    non_mod_strs = {
        "ready", "assigned", "picked_up", "arriving", "delivered", "cancelled",
        "undeliverable", "on_resale", "resold", "written_off",
    }
    if str(order.status) in non_mod_strs:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-blocked",
            body=f"Order #{order.order_number} cannot be modified (status: {order.status}). Modifications allowed only before ready per spec.",
        )
        return

    _set_state(conv, dialogue_state="modify_items", modify_order_id=order.id, modify_proposed=[])
    # Use a real dish from this order as the example so the hint is never a
    # dish the restaurant doesn't serve (multi-tenant: no hardcoded dish names).
    example_dish = await session.scalar(
        select(OrderItem.dish_name).where(OrderItem.order_id == order.id).limit(1)
    )
    example = f"'2x {example_dish}'" if example_dish else "the dish name and quantity"
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="modify-start",
        body=(
            f"Sure, let's modify order #{order.order_number}. "
            f"Reply with updated dishes (e.g. {example}), or 'done' when ready to review changes. "
            f"After you confirm, the 40-min SLA clock restarts."
        ),
    )


async def _handle_modify_items(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Collect proposed replacement items for modify (re-uses _handle_collecting_items logic:
    parse_qty_and_text, find_dish_matches + confidence paths, 'what is' describer, 'done' gate).
    Stores serializable proposed list in conv.state['modify_proposed']; no DB mutation until confirm.
    """
    from app.ordering.service import parse_qty_and_text

    if inbound.type != MessageType.TEXT:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="need-text-mod",
            body="Please type the name or number of a dish from the menu to update your order.",
        )
        return

    text = (inbound.payload.get("text") or "").strip()
    qty, dish_query = parse_qty_and_text(text)
    lower_q = dish_query.lower()

    if lower_q in ("done", "checkout", "that's all", "thats all"):
        mod_id = conv.state.get("modify_order_id")
        proposed = conv.state.get("modify_proposed", []) or []
        if not mod_id or not proposed:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-no-proposed",
                body="No changes proposed yet. Reply with dishes or send 'hi' to start over.",
            )
            return
        _set_state(conv, dialogue_state="modify_confirm")
        await _send_modify_summary(session, conv, inbound, restaurant_id, mod_id, proposed)
        return

    if lower_q.startswith("what is "):
        from app.llm.factory import get_describer
        item_name = dish_query[8:].strip().rstrip("?")
        desc = get_describer().describe(item_name, "")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="dish-desc-mod", body=desc,
        )
        return

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)

    if result.confidence == MatchConfidence.NO_MATCH:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-match-mod",
            body="Sorry, I couldn't find that dish. Please reply with the dish name from the menu, or try a different spelling.",
        )
        return

    if result.confidence == MatchConfidence.AMBIGUOUS:
        options = " or ".join(
            f"{d.name} (AED {_aed(d.price_aed)})"
            for d in result.candidates[:3]
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ambiguous-mod",
            body=f"Did you mean {options}? Please reply with the dish number.",
        )
        return

    # Direct match: accumulate in proposed (replaces cart-add in collecting_items)
    dish = result.candidates[0]
    proposed = list(conv.state.get("modify_proposed", []) or [])
    proposed.append({
        "dish_id": dish.id,
        "dish_number": dish.dish_number,
        "name": dish.name,
        "price_aed": str(dish.price_aed),
        "qty": qty,
    })
    _set_state(conv, dialogue_state="modify_items", modify_proposed=proposed)

    price = _aed(dish.price_aed)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="item-proposed",
        body=(
            f"Added {qty}x {dish.name} (AED {price}) to your modification.\n"
            f"Reply with more items, or send 'done' to review and confirm (SLA restarts on confirm)."
        ),
    )


async def _send_modify_summary(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    order_id: int,
    proposed: list[dict],
) -> None:
    """Show current vs proposed + totals; buttons for confirm_modify / cancel_modify."""
    from app.ordering.models import Order, OrderItem

    order = await session.get(Order, order_id)
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-mod-order", body="Order not found.",
        )
        return

    current_items = list((
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all())
    curr_lines = "\n".join(
        f"  {it.qty}x {it.dish_name} — "
        f"AED {_aed(it.price_aed * it.qty)}"
        for it in current_items
    ) or "  (none)"

    prop_lines = "\n".join(
        f"  {p['qty']}x {p.get('name', '?')} — "
        f"AED {_aed(Decimal(str(p['price_aed'])) * p['qty'])}"
        for p in proposed
    ) or "  (none)"

    new_sub = sum(Decimal(str(p["price_aed"])) * p["qty"] for p in proposed)
    new_total = new_sub + (order.delivery_fee_aed or Decimal("0"))

    body = (
        f"Current order #{order.order_number}:\n{curr_lines}\n\n"
        f"Proposed new items:\n{prop_lines}\n\n"
        f"New subtotal: AED {_aed(new_sub)}\n"
        f"Delivery: AED {_aed(order.delivery_fee_aed or 0)}\n"
        f"New total: AED {_aed(new_total)}\n\n"
        f"Confirm these changes? (COD, 40-min SLA restarts after your confirm)"
    )
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="modify-summary",
        body=body,
        buttons=[
            {"id": "confirm_modify", "title": "Confirm changes"},
            {"id": "cancel_modify", "title": "Keep original"},
        ],
    )


async def _handle_modify_confirm(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Confirm handler for modify: load order WITH FOR UPDATE (per spec §4.2.8 and fsm concurrency note),
    build dish list, call ordering.service.modify_order (handles items replace, recalc, SLA restart, audit).
    Bounded context: engine only calls service, no direct model writes. Full flow wired (intent, states, confirm).
    """
    from app.menu.models import Dish
    from app.ordering.models import Order
    from app.ordering.service import modify_order

    mod_id = conv.state.get("modify_order_id")
    if not mod_id:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-mod-pending",
            body="No modification in progress. Send 'hi' to start a new order.",
        )
        return

    # for_update per spec §4.2.8 (modify only before ready) and fsm concurrency (race with kitchen ready). Full modify dialogue implemented.
    order = await session.get(Order, mod_id, with_for_update=True) if mod_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-mod-order",
            body="Order not found for modification.",
        )
        return

    btn_id = inbound.payload.get("id", "") if inbound.type == MessageType.BUTTON_REPLY else ""

    if btn_id == "confirm_modify":
        proposed = conv.state.get("modify_proposed", []) or []
        if not proposed:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-empty",
                body="No proposed changes. Modification cancelled.",
            )
            _set_state(conv, dialogue_state="order_placed", modify_order_id=None, modify_proposed=None)
            return

        new_items: list[dict] = []
        for p in proposed:
            dish = await session.get(Dish, p["dish_id"])
            if dish is not None:
                new_items.append({"dish": dish, "qty": p.get("qty", 1), "notes": None})

        if new_items:
            await modify_order(session, order=order, new_items=new_items, actor="customer")
            # commit by caller (webhook/router)

        _set_state(
            conv,
            dialogue_state="order_placed",
            modify_order_id=None,
            modify_proposed=None,
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-confirmed",
            body=(
                f"Order #{order.order_number} updated!\n"
                f"New total: AED {_aed(order.total)} (COD).\n"
                f"The 40-minute delivery window restarts now."
            ),
        )
        return

    if btn_id == "cancel_modify":
        _set_state(conv, dialogue_state="order_placed", modify_order_id=None, modify_proposed=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-cancelled",
            body="Modification cancelled — original order unchanged. Send 'hi' if needed.",
        )
        return

    # re-prompt
    proposed = conv.state.get("modify_proposed", []) or []
    await _send_modify_summary(session, conv, inbound, restaurant_id, mod_id, proposed)


async def _handle_restaurant_location_request(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant,
) -> None:
    """Send the restaurant's location as a native WhatsApp pin + a short text.

    Read-only: does NOT touch the dialogue phase or any draft order, so asking
    "what's your location, I'll come direct" never spins up an order or pushes the
    customer into address capture (the old AI behaviour)."""
    import time

    if restaurant is None or restaurant.lat is None or restaurant.lng is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="rest-loc-missing",
            body="Sorry, we don't have our exact location pin set up yet. "
                 "Please contact us for directions.",
        )
        return

    name = restaurant.name or "Restaurant"
    payload = {
        "latitude": restaurant.lat,
        "longitude": restaurant.lng,
        "name": name,
    }
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.LOCATION,
        payload=payload,
        idempotency_key=f"rest-loc-{conv.id}-{inbound.wa_message_id}",
    )
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="location",
        payload={"type": "location", **payload},
        ts=int(time.time()),
    )
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="rest-loc-note",
        body=f"📍 Here's *{name}* — tap the pin above for directions. See you soon! 🛵",
    )


async def _handle_status_query(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Reply to 'where is my order' with the current order status and ETA.

    For en-route statuses (assigned / picked_up / arriving) the reply is
    built by ``build_tracking_reply`` which uses the rider's latest GPS ping
    and the geo provider to compute a live ETA.
    """
    from datetime import datetime, timezone

    from app.dispatch.tracking import build_tracking_reply
    from app.geo.factory import get_geo_provider
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == inbound.from_phone,
        )
    )
    if not customer:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="status-no-customer",
            body="I don't see any recent orders for this number. "
                 "Send 'hi' to start a new order.",
        )
        return

    # "Where is my order" means the customer's LATEST order. Report the most
    # recent PLACED order (DRAFT is an incomplete/abandoned cart, never placed —
    # excluded). Crucially we do NOT skip terminal orders: if their latest order
    # was delivered we must say "delivered", not dig up an older still-open order
    # and report it (which read as "ready in 40 min" right after a delivery).
    order = await session.scalar(
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.customer_id == customer.id,
            Order.status != str(OrderStatus.DRAFT),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )

    if not order:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="status-no-order",
            body="You don't have any orders yet. "
                 "Send 'hi' to place a new order.",
        )
        return

    # Terminal outcomes get a clear, final message (no ETA / no tracking link).
    _terminal_messages = {
        str(OrderStatus.DELIVERED): (
            f"Your order #{order.order_number} was delivered. Enjoy! 🎉\n\n"
            "Send 'hi' to place a new order."
        ),
        str(OrderStatus.CANCELLED): (
            f"Your order #{order.order_number} was cancelled. "
            "Send 'hi' to place a new order."
        ),
        str(OrderStatus.UNDELIVERABLE): (
            f"Sorry, your order #{order.order_number} couldn't be delivered. "
            "Please contact the restaurant for help."
        ),
        str(OrderStatus.RESOLD): (
            f"Your order #{order.order_number} was cancelled. "
            "Send 'hi' to place a new order."
        ),
        str(OrderStatus.WRITTEN_OFF): (
            f"Your order #{order.order_number} was closed. "
            "Send 'hi' to place a new order."
        ),
    }
    if str(order.status) in _terminal_messages:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="status-terminal", body=_terminal_messages[str(order.status)],
        )
        return

    _en_route = {
        str(OrderStatus.ASSIGNED),
        str(OrderStatus.PICKED_UP),
        str(OrderStatus.ARRIVING),
    }

    if str(order.status) in _en_route:
        # Delegate to build_tracking_reply for live rider ETA via GPS + geo provider.
        body = await build_tracking_reply(
            session, order=order, geo=get_geo_provider()
        )
        # Re-share the live tracking link so "where is my order" / "can I see the
        # live location" always hands back the clickable map — as a tappable
        # "Track your rider" button (CTA URL), mirroring the rider's button,
        # instead of a raw link.
        from app.dispatch.models import OrderTrackingSession
        from app.dispatch.tracking_live import build_tracking_url

        tracking = await session.scalar(
            select(OrderTrackingSession).where(OrderTrackingSession.order_id == order.id)
        )
        if tracking is not None and tracking.tracking_token:
            await _send_cta_url(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="status-reply",
                body=f"{body}\n\nTrack your order live on the map below.",
                button_label="Track my order",
                url=build_tracking_url(tracking.tracking_token),
            )
            return
    else:
        status_messages = {
            str(OrderStatus.DRAFT): "Your order is being assembled.",
            str(OrderStatus.PENDING_CONFIRMATION): "Your order is waiting for your confirmation.",
            str(OrderStatus.CONFIRMED): (
                f"Your order #{order.order_number} is confirmed and will be ready "
                f"in about 40 minutes."
            ),
            str(OrderStatus.PREPARING): (
                f"Your order #{order.order_number} is being prepared in the kitchen."
            ),
            str(OrderStatus.READY): (
                f"Your order #{order.order_number} is ready and waiting for the rider."
            ),
            str(OrderStatus.ON_RESALE): (
                "Your order was cancelled. Please contact the restaurant for more information."
            ),
        }
        body = status_messages.get(str(order.status), f"Order status: {order.status}.")

        if order.sla_deadline:
            remaining = int(
                (order.sla_deadline - datetime.now(timezone.utc)).total_seconds() / 60
            )
            if 0 < remaining <= 40 and str(order.status) in (
                str(OrderStatus.CONFIRMED),
                str(OrderStatus.PREPARING),
                str(OrderStatus.READY),
            ):
                body += f" Estimated time remaining: ~{remaining} minutes."

    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="status-reply", body=body,
    )


async def _fetch_conversation_history(
    session: AsyncSession, conversation_id: int, limit: int = 20
) -> list[dict]:
    """Fetch last N messages as Claude-compatible history (alternating roles)."""
    from app.conversation.models import Message

    rows = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc())
                .limit(limit)
            )
        ).all()
    )
    rows.reverse()
    raw: list[dict] = []
    for m in rows:
        if m.type == "text":
            content = m.payload.get("text") or m.payload.get("body") or ""
        else:
            content = f"[{m.type}]"
        if not content:
            continue
        role = "user" if m.direction == "inbound" else "assistant"
        raw.append({"role": role, "content": content})
    # Claude requires strictly alternating user/assistant — merge consecutive same-role
    merged: list[dict] = []
    for item in raw:
        if merged and merged[-1]["role"] == item["role"]:
            merged[-1]["content"] += "\n" + item["content"]
        else:
            merged.append({"role": item["role"], "content": item["content"]})
    return merged


async def _order_has_items(session: AsyncSession, order_id: int) -> bool:
    from app.ordering.models import OrderItem

    item_id = await session.scalar(
        select(OrderItem.id).where(OrderItem.order_id == order_id).limit(1)
    )
    return item_id is not None


async def _resolve_draft_order(
    session: AsyncSession, conv: Conversation, restaurant_id: int, phone: str
):
    """Return the live draft order for this conversation, resilient to a stale or
    missing draft_order_id pointer in conv.state.

    The cart is a DRAFT Order row; conv.state only holds a foreign-key handle
    (draft_order_id). If that pointer is lost or points at a vanished row (e.g. a
    retried/duplicated webhook, or state that didn't persist across requests), the
    customer's items are still in the DB on their most-recent draft order. Recover
    it and re-link conv.state instead of telling them "your cart is empty".
    Returns the Order, or None only when the customer genuinely has no draft items.
    """
    from app.ordering.models import Customer, Order

    draft_order_id = conv.state.get("draft_order_id")
    if draft_order_id:
        order = await session.get(Order, draft_order_id)
        if order is not None and await _order_has_items(session, order.id):
            return order

    # Pointer is stale/missing — fall back to the customer's latest non-empty draft.
    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id, Customer.phone == phone
        )
    )
    if customer is None:
        return None
    candidates = (
        await session.scalars(
            select(Order)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.customer_id == customer.id,
                Order.status == "draft",
            )
            .order_by(Order.id.desc())
            .limit(5)
        )
    ).all()
    for order in candidates:
        if await _order_has_items(session, order.id):
            if order.id != draft_order_id:
                _logger.warning(
                    "recovered stale draft pointer: conv=%s phone=%s "
                    "state_draft=%s -> draft=%s",
                    conv.id, phone, draft_order_id, order.id,
                )
                _set_state(conv, draft_order_id=order.id)
            return order
    return None


async def _build_cart_summary(session: AsyncSession, conv) -> str:
    from app.ordering.models import Order, OrderItem

    draft_order_id = conv.state.get("draft_order_id")
    if not draft_order_id:
        return ""
    order = await session.get(Order, draft_order_id)
    if order is None:
        return ""
    items = list(
        (await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    )
    if not items:
        return ""
    lines = [
        f"{it.qty}x {it.dish_name}"
        f"{f' ({it.variant_name})' if it.variant_name else ''} "
        f"(AED {_aed(it.price_aed * it.qty)})"
        for it in items
    ]
    return ", ".join(lines) + f" | Subtotal: AED {_aed(order.subtotal)}"


def _cart_tail(cart: str) -> str:
    """Trailing cart line for edit confirmations so the customer always sees the
    current cart right after a remove / quantity change."""
    return f"\n\n🛒 {cart}" if cart else "\n\n🛒 Your cart is now empty."


async def _build_history(
    session: AsyncSession,
    conv: Conversation,
    limit: int = 10,
) -> list[dict]:
    """Fetch last `limit` messages and build OpenAI-style history list."""
    from app.conversation.models import Message

    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    ).all()
    rows = list(reversed(rows))  # oldest first

    history: list[dict] = []
    for msg in rows:
        role = "user" if msg.direction == "inbound" else "assistant"
        payload = msg.payload or {}

        if msg.type == "text":
            content = payload.get("text") or payload.get("body") or ""
        elif msg.type == "location":
            lat = payload.get("latitude", "")
            lng = payload.get("longitude", "")
            content = f"[customer shared location pin: {lat},{lng}]"
        elif msg.type == "button_reply":
            title = payload.get("title") or payload.get("id") or "button"
            content = f"[tapped: {title}]"
        elif msg.type == "buttons":
            content = payload.get("body") or "[buttons sent]"
        else:
            content = f"[{msg.type}]"

        if content:
            history.append({"role": role, "content": content})

    # OpenAI requires first message to be user role
    if history and history[0]["role"] == "assistant":
        history.insert(0, {"role": "user", "content": "hi"})

    return history


_PHASE_MAP = {
    "greeting": "ordering",
    "menu_sent": "ordering",
    "collecting_items": "ordering",
    "cancelled": "ordering",
    "modify_items": "ordering",
    "modify_confirm": "ordering",
    "address_capture": "address_capture",
    "address_text_pending": "address_capture",
    "receiver_details": "address_capture",
    "order_confirmation": "awaiting_confirmation",
    "order_placed": "post_order",
    "post_order": "post_order",
}

_VALID_PHASES = frozenset({"ordering", "address_capture", "awaiting_confirmation", "post_order"})

_PHASE_ACTIONS: dict[str, frozenset] = {
    "ordering": frozenset({
        "add_item", "remove_item", "update_qty", "proceed_to_address",
        "cancel_order", "status_query", "show_menu", "no_action",
    }),
    "address_capture": frozenset({
        "send_location_request", "save_address_text", "use_saved_address",
        "proceed_to_confirmation", "cancel_order", "no_action",
    }),
    "awaiting_confirmation": frozenset({
        "confirm_order", "request_modification", "cancel_order", "no_action",
    }),
    "post_order": frozenset({
        "status_query", "request_modification", "cancel_order", "no_action",
    }),
}


def _resolve_phase(conv: Conversation) -> str:
    """Return the current dialogue_phase, mapping legacy dialogue_state if needed."""
    state = conv.state or {}
    if "dialogue_phase" in state and state["dialogue_phase"] in _VALID_PHASES:
        return state["dialogue_phase"]
    old_state = state.get("dialogue_state", "greeting")
    return _PHASE_MAP.get(old_state, "ordering")


def _is_valid_action_for_phase(action: str, phase: str) -> bool:
    """Return True if action is allowed in the given phase."""
    allowed = _PHASE_ACTIONS.get(phase, frozenset())
    return action in allowed


async def _build_context(
    session: AsyncSession,
    conv: Conversation,
    restaurant_id: int,
    phase: str,
    restaurant,
) -> dict:
    """Build phase-specific context dict for the AI agent."""
    ctx: dict = {}

    # Restaurant location label — grounds "where are you located?" in the REAL
    # saved coordinates (Settings → location) so the LLM can't invent an area.
    # Dynamic: change the pin in Settings → new coords → new label here.
    if restaurant is not None and restaurant.lat is not None and restaurant.lng is not None:
        from app.geo.cache import reverse_geocode_cached

        ctx["restaurant_location"] = (
            await reverse_geocode_cached(restaurant.lat, restaurant.lng) or "unknown"
        )
    else:
        ctx["restaurant_location"] = "unknown"

    # Real delivery-fee tiers (grounded) + opening hours, so the bot recites the
    # truth instead of inventing fees/times when asked.
    from app.ordering.fees import delivery_info_text

    ctx["delivery_info"] = delivery_info_text(restaurant.settings if restaurant else None)
    ctx["hours_info"] = _hours_info(restaurant)
    # Contact number the bot can hand out for anything it can't handle (complaints,
    # special arrangements, off-topic asks) — "please call us on …".
    ctx["restaurant_phone"] = (restaurant.phone if restaurant else "") or ""

    if phase == "ordering":
        ctx["menu_text"] = await _render_menu(session, restaurant_id)
        ctx["cart_summary"] = await _build_cart_summary(session, conv)

    elif phase == "address_capture":
        ctx["cart_summary"] = await _build_cart_summary(session, conv)
        ctx["location_received"] = conv.state.get("pin_lat") is not None
        ctx["apt_room"] = conv.state.get("pending_room", "")
        ctx["building"] = conv.state.get("pending_building", "")
        ctx["receiver_name"] = conv.state.get("pending_receiver", "")
        from app.ordering.fees import radius_km
        ctx["max_radius_km"] = radius_km(await _fee_settings_for(session, restaurant_id))

        from app.ordering.models import Customer, CustomerAddress
        customer = await session.scalar(
            select(Customer).where(
                Customer.restaurant_id == restaurant_id,
                Customer.phone == conv.phone,
            )
        )
        saved = ""
        # Only surface the saved address to the AI until it's been offered once
        # (deterministically, via buttons). After that, address_offer_made is set
        # and we drop it so the AI never re-offers / loops on it.
        if customer and not conv.state.get("address_offer_made"):
            addr = await session.scalar(
                select(CustomerAddress)
                .where(CustomerAddress.customer_id == customer.id)
                .order_by(CustomerAddress.last_used_at.desc())
                .limit(1)
            )
            if addr:
                saved = f"Apt {addr.room_apartment}, {addr.building}"
                ctx["saved_address_id"] = addr.id
        ctx["saved_address"] = saved

    elif phase == "awaiting_confirmation":
        from app.ordering.models import Order, OrderItem
        from app.weather.factory import get_weather_port

        order_id = conv.state.get("pending_order_id") or conv.state.get("draft_order_id")
        order = await session.get(Order, order_id) if order_id else None
        if order:
            items = (await session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id)
            )).all()
            item_lines = "\n".join(
                f"  {it.qty}x {it.dish_number}. {it.dish_name} — "
                f"AED {_aed(it.price_aed * it.qty)}"
                for it in items
            )
            weather_note = ""
            if get_weather_port().is_delay_active():
                order.weather_delay_disclosed = True
                await session.flush()
                weather_note = "\n⚠️ Weather may cause delays beyond usual ETA."
            ctx["order_summary"] = (
                f"{item_lines}\n\n"
                f"Subtotal: AED {_aed(order.subtotal)}\n"
                f"Delivery fee: AED {_aed(order.delivery_fee_aed)}\n"
                f"Total: AED {_aed(order.total)}\n"
                f"Payment: COD (cash on delivery)\n"
                f"ETA: ~40 minutes{weather_note}"
            )
            ctx["order_id"] = order.id

    elif phase == "post_order":
        from app.ordering.fsm import OrderStatus
        from app.ordering.models import Customer, Order

        customer = await session.scalar(
            select(Customer).where(
                Customer.restaurant_id == restaurant_id,
                Customer.phone == conv.phone,
            )
        )
        ctx["order_number"] = ""
        ctx["order_status"] = "unknown"
        ctx["rider_eta"] = ""
        if customer:
            terminal = {
                str(OrderStatus.DELIVERED), str(OrderStatus.CANCELLED),
                str(OrderStatus.UNDELIVERABLE), str(OrderStatus.RESOLD),
                str(OrderStatus.WRITTEN_OFF),
            }
            order = await session.scalar(
                select(Order)
                .where(
                    Order.restaurant_id == restaurant_id,
                    Order.customer_id == customer.id,
                    Order.status.notin_(terminal),
                )
                .order_by(Order.created_at.desc())
                .limit(1)
            )
            if order:
                ctx["order_number"] = str(order.order_number or "")
                ctx["order_status"] = str(order.status)

    return ctx


def _variant_question(dish) -> str:
    """One-line size question listing each variant's name + price, e.g.
    "Which size for Chicken Biryani — 1 serve (AED 18) or 4 serve (AED 60)?"."""
    opts = " or ".join(
        f"{v.get('name')} (AED {_aed(Decimal(str(v.get('price_aed'))))})"
        for v in (dish.variants or [])
    )
    return f"Which size for {dish.name} — {opts}?"


async def _add_dish_to_cart(
    session: AsyncSession,
    conv,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    dish,
    qty: int,
    notes: str | None,
    variant: dict | None = None,
):
    """Ensure a draft order exists for this conversation and add the dish (optionally
    a chosen serving-size variant) to it. Shared by the direct add path and the
    variant-resolution path so order/state setup stays identical."""
    from app.ordering.models import Order
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone
    )
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None:
        order = await create_draft_order(session, restaurant_id=restaurant_id, customer_id=customer.id)
        # New order starts: clear address/location state left over from a previous
        # order so a returning customer is re-offered their saved address every
        # time, and the fee/distance is recomputed for THIS order rather than
        # reused from the last one.
        _set_state(
            conv, draft_order_id=order.id, address_offer_made=None,
            saved_address_id=None, pin_lat=None, pin_lon=None,
            distance_km=None, delivery_fee=None,
        )
    await add_item(session, order=order, dish=dish, qty=qty, notes=notes, variant=variant)
    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
    return order


async def _execute_ai_add_item(
    session: AsyncSession,
    conv,
    inbound: InboundMessage,
    restaurant_id: int,
    dish_query: str,
    qty: int,
    special_note: str = "",
) -> str:
    """Find and add a dish. Returns "added", "no_match", or "awaiting_variant"
    (a size question was just sent and the item is deferred until the reply)."""
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH:
        return "no_match"
    if result.confidence == MatchConfidence.AMBIGUOUS:
        from app.llm.factory import get_arbiter
        try:
            dish = await get_arbiter().arbitrate(dish_query, result.candidates[:3])
        except Exception:
            dish = None
        if dish is None:
            dish = result.candidates[0]
    else:
        dish = result.candidates[0]

    # Serving-size variants: if the dish has them and the customer hasn't already
    # named a size (in the dish query or the note), ask ONE question and defer the
    # add. The matcher resolves "family biryani"/"4 serve" directly so a customer
    # who already said the size skips the question.
    variants = getattr(dish, "variants", None) or []
    if variants:
        variant = resolve_variant(dish, dish_query)
        if variant is None and special_note:
            variant = resolve_variant(dish, special_note)
        if variant is None:
            _set_state(
                conv,
                awaiting_variant={"dish_id": dish.id, "qty": qty, "notes": special_note or None},
                variant_retries=0,
            )
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="variant-ask", body=_variant_question(dish),
            )
            return "awaiting_variant"
        await _add_dish_to_cart(
            session, conv, inbound, restaurant_id,
            dish=dish, qty=qty, notes=special_note or None, variant=variant,
        )
        return "added"

    await _add_dish_to_cart(
        session, conv, inbound, restaurant_id,
        dish=dish, qty=qty, notes=special_note or None,
    )
    return "added"


async def _handle_variant_reply(
    session: AsyncSession,
    conv,
    inbound: InboundMessage,
    restaurant_id: int,
) -> bool:
    """Resolve a pending serving-size question from the customer's text reply.

    On a recognized size → add the item and confirm. On an unrecognized reply →
    re-ask ONCE, then default to the first listed (cheapest) variant rather than
    looping forever. Returns True if it handled the message (caller should stop)."""
    pending = conv.state.get("awaiting_variant")
    if not pending or inbound.type != MessageType.TEXT:
        return False
    from app.menu.models import Dish

    dish = await session.get(Dish, pending.get("dish_id"))
    if dish is None or not (dish.variants or []):
        _set_state(conv, awaiting_variant=None, variant_retries=None)
        return False

    text = (inbound.payload.get("text") or "").strip()
    variant = resolve_variant(dish, text)
    if variant is None:
        retries = int(conv.state.get("variant_retries") or 0)
        if retries < 1:
            _set_state(conv, variant_retries=retries + 1)
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="variant-reask",
                body="Sorry, I didn't catch the size. " + _variant_question(dish),
            )
            return True
        # Give up gracefully: default to the first listed variant.
        variant = dish.variants[0]

    qty = int(pending.get("qty") or 1)
    notes = pending.get("notes")
    await _add_dish_to_cart(
        session, conv, inbound, restaurant_id,
        dish=dish, qty=qty, notes=notes, variant=variant,
    )
    _set_state(conv, awaiting_variant=None, variant_retries=None)
    line_total = Decimal(str(variant["price_aed"])) * qty
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="variant-added",
        body=f"Added {qty}x {dish.name} ({variant['name']}) — AED {_aed(line_total)} ✅",
    )
    return True


async def _resolve_cart_dish(session: AsyncSession, *, order_id: int, candidates):
    """Pick the matched candidate that is ACTUALLY in the cart, so "remove biryani"
    / "make it 4" target the dish the customer added even when the name matches
    several menu items. Returns the in-cart Dish candidate, or None if none of the
    candidates are in the cart."""
    from app.ordering.models import OrderItem

    if not candidates:
        return None
    ids = {c.id for c in candidates}
    in_cart = set(
        (
            await session.scalars(
                select(OrderItem.dish_id).where(
                    OrderItem.order_id == order_id,
                    OrderItem.dish_id.in_(ids),
                )
            )
        ).all()
    )
    for c in candidates:
        if c.id in in_cart:
            return c
    return None


async def _execute_ai_remove_item(
    session: AsyncSession, conv: Conversation, restaurant_id: int,
    dish_query: str, qty: int | None = None,
) -> tuple[str, str | None]:
    """Remove a dish from the draft cart. ``qty=None`` removes the whole dish;
    a number removes that many units (capped at what's in the cart).

    Returns ``(outcome, dish_name)`` where outcome is "removed" (dish gone),
    "reduced" (some units left), "not_in_cart" (matched a menu dish but it wasn't
    in the cart), or "no_match" (couldn't match the query)."""
    from app.ordering.models import Order, OrderItem
    from app.ordering.service import remove_item

    draft_order_id = conv.state.get("draft_order_id")
    if not draft_order_id or not dish_query:
        return ("no_match", None)
    order = await session.get(Order, draft_order_id)
    if order is None:
        return ("no_match", None)
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH or not result.candidates:
        return ("no_match", None)
    dish = await _resolve_cart_dish(session, order_id=order.id, candidates=result.candidates[:5])
    if dish is None:
        return ("not_in_cart", result.candidates[0].name)
    # Units of this dish currently in the cart (so "remove" with no number — or a
    # number ≥ what's there — clears the whole line).
    in_cart_units = sum(
        i.qty for i in (
            await session.scalars(
                select(OrderItem).where(
                    OrderItem.order_id == order.id, OrderItem.dish_id == dish.id
                )
            )
        ).all()
    )
    to_remove = in_cart_units if qty is None or qty >= in_cart_units else qty
    removed = await remove_item(session, order=order, dish=dish, qty=to_remove)
    if removed <= 0:
        return ("not_in_cart", dish.name)
    return ("removed" if removed >= in_cart_units else "reduced", dish.name)


async def _execute_ai_update_qty(
    session: AsyncSession, conv: Conversation, restaurant_id: int,
    dish_query: str, qty: int
) -> tuple[str, str | None]:
    """Set a cart dish to an exact quantity (``qty <= 0`` removes it).

    Returns ``(outcome, dish_name)``: "updated", "removed", "not_in_cart", or
    "no_match"."""
    from app.ordering.models import Order
    from app.ordering.service import set_item_qty

    draft_order_id = conv.state.get("draft_order_id")
    if not draft_order_id or not dish_query:
        return ("no_match", None)
    order = await session.get(Order, draft_order_id)
    if order is None:
        return ("no_match", None)
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH or not result.candidates:
        return ("no_match", None)
    dish = await _resolve_cart_dish(session, order_id=order.id, candidates=result.candidates[:5])
    if dish is None:
        return ("not_in_cart", result.candidates[0].name)
    await set_item_qty(session, order=order, dish_id=dish.id, qty=qty)
    return ("removed" if qty <= 0 else "updated", dish.name)


async def _execute_save_address(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage,
    restaurant_id: int, apt_room: str, building: str, receiver_name: str, restaurant,
) -> None:
    """Store address, attach to draft order, transition to awaiting_confirmation."""
    from app.ordering.fees import calculate_fee
    from app.ordering.service import get_or_create_customer, upsert_address

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone
    )
    addr = await upsert_address(
        session,
        customer_id=customer.id,
        latitude=conv.state.get("pin_lat"),
        longitude=conv.state.get("pin_lon"),
        room_apartment=apt_room,
        building=building,
        receiver_name=receiver_name,
        confirmed=True,
    )
    order = await _resolve_draft_order(
        session, conv, restaurant_id, inbound.from_phone
    )
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-draft-addr",
            body="Your cart is empty. Send 'hi' to start a new order.",
        )
        return
    dist = conv.state.get("distance_km")
    fee = calculate_fee(
        dist if dist is not None else 0.0,
        await _fee_settings_for(session, restaurant_id),
    )
    order.address_id = addr.id
    order.distance_km = dist
    order.delivery_fee_aed = fee
    order.total = order.subtotal + fee
    await session.flush()
    _set_state(conv, dialogue_phase="awaiting_confirmation",
               dialogue_state="order_confirmation", pending_order_id=order.id)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _resolve_saved_address_id(
    session: AsyncSession, restaurant_id: int, phone: str
) -> int | None:
    """Return the id of the customer's most-recently-used saved address, or None."""
    from app.ordering.models import Customer, CustomerAddress

    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == phone,
        )
    )
    if customer is None:
        return None
    addr = await session.scalar(
        select(CustomerAddress)
        .where(CustomerAddress.customer_id == customer.id)
        .order_by(CustomerAddress.last_used_at.desc())
        .limit(1)
    )
    return addr.id if addr else None


async def _offer_saved_address_if_any(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> bool:
    """Returning customer → offer the saved address UP FRONT with Use/New buttons,
    deterministically (the rule engine decides, the AI just talks). Returns True if
    an offer was sent.

    Offering before they type avoids the "type address → get offered saved → retype"
    double entry. Sets address_offer_made so it's shown once and the AI won't
    re-offer (saved_address is dropped from its context afterwards).
    """
    from app.ordering.models import Customer, CustomerAddress

    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == conv.phone,
        )
    )
    if customer is None:
        return False
    addr = await session.scalar(
        select(CustomerAddress)
        .where(CustomerAddress.customer_id == customer.id)
        .order_by(CustomerAddress.last_used_at.desc())
        .limit(1)
    )
    if addr is None:
        return False

    label = ", ".join(
        p for p in (addr.room_apartment, addr.building) if p
    ) or "your saved address"
    _set_state(conv, address_offer_made=True, saved_address_id=addr.id)
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="offer-saved-addr",
        body=f"Welcome back! Deliver to your saved address ({label})?",
        buttons=[
            {"id": "use_saved_address", "title": "Use saved address"},
            {"id": "new_address", "title": "New address"},
        ],
    )
    return True


async def _attach_saved_address_to_order(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage,
    restaurant_id: int, address_id: int, restaurant,
) -> None:
    """Reuse saved address — attach to draft order and transition to confirmation."""
    from app.ordering.fees import calculate_fee
    from app.ordering.models import CustomerAddress

    addr = await session.get(CustomerAddress, address_id)
    if addr is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="saved-addr-gone",
            body="Couldn't load your saved address. Please share your location 📍",
        )
        return
    order = await _resolve_draft_order(
        session, conv, restaurant_id, inbound.from_phone
    )
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-draft-saved",
            body="Your cart is empty. Send 'hi' to start a new order.",
        )
        return
    dist_km = await _road_distance_km(
        restaurant.lat, restaurant.lng, addr.latitude, addr.longitude
    )
    from app.ordering.fees import fee_settings_from_restaurant
    fee = calculate_fee(dist_km, fee_settings_from_restaurant(restaurant.settings))
    order.address_id = addr.id
    order.distance_km = dist_km
    order.delivery_fee_aed = fee
    order.total = order.subtotal + fee
    await session.flush()
    _set_state(conv, dialogue_phase="awaiting_confirmation",
               dialogue_state="order_confirmation", pending_order_id=order.id)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _execute_confirm_order(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> None:
    """Finalize order confirmation and transition to post_order."""
    from app.ordering.models import Order
    from app.ordering.service import finalize_confirmation

    order_id = conv.state.get("pending_order_id") or conv.state.get("draft_order_id")
    order = await session.get(Order, order_id) if order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-order-confirm",
            body="No order to confirm. Send 'hi' to start again.",
        )
        return
    await finalize_confirmation(session, order=order, actor="customer")
    _set_state(conv, dialogue_phase="post_order", dialogue_state="order_placed")
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-confirmed",
        body=(
            f"Order confirmed! 🎉 Order #{order.order_number}\n"
            f"Total: AED {_aed(order.total)} (COD — cash on delivery)\n"
            f"Your food will arrive within ~40 minutes. We'll keep you posted! 🛵"
        ),
    )


async def _execute_cancel_order(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> None:
    """Cancel the current draft/pending order."""
    from app.ordering.fsm import OrderStatus
    from app.ordering.fsm import transition as fsm_transition
    from app.ordering.models import Order

    for key in ("pending_order_id", "draft_order_id"):
        order_id = conv.state.get(key)
        if order_id:
            order = await session.get(Order, order_id)
            if order and str(order.status) in (
                str(OrderStatus.DRAFT), str(OrderStatus.PENDING_CONFIRMATION),
                str(OrderStatus.CONFIRMED),
            ):
                await fsm_transition(session, order, OrderStatus.CANCELLED, actor="customer")
            break
    _set_state(conv, dialogue_phase="ordering", dialogue_state="greeting",
               draft_order_id=None, pending_order_id=None)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-cancelled",
        body="No problem — your order has been cancelled. Send 'hi' whenever you're ready to order again 😊",
    )


_DEFAULT_MAX_ITEM_QTY = 10


def _max_item_qty(restaurant) -> int:
    """Per-restaurant single-line quantity threshold. Above it, a request is an
    anomaly (e.g. "100000 lemon mints") and is escalated to a human rather than
    auto-added. Manager-configurable in OPS Settings (settings.max_item_qty);
    defaults to 10."""
    try:
        return int((getattr(restaurant, "settings", None) or {}).get(
            "max_item_qty", _DEFAULT_MAX_ITEM_QTY
        ))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_ITEM_QTY


async def _escalate_large_qty(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    qty: int,
    dish_query: str,
) -> None:
    """Hand the chat to a human and tell the customer we'll confirm. Used when a
    requested quantity exceeds the restaurant's anomaly threshold — we never
    auto-add an unusually large line; a manager confirms it from the dashboard."""
    conv.manual_takeover = True
    item = (dish_query or "").strip() or "that"
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="qty-anomaly",
        body=(
            f"That's a large quantity ({qty}x {item})! 🤔 I've flagged your order "
            "for our team to confirm — someone will be with you shortly to finalise it. 😊"
        ),
    )


async def _dispatch_action(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    result,
    phase: str,
    restaurant,
) -> None:
    """Execute the action returned by the AI agent."""
    action = result.action
    data = result.action_data or {}
    reply = result.message or ""

    # Phase guard — wrong-phase action falls back to no_action
    if not _is_valid_action_for_phase(action, phase):
        action = "no_action"

    # Anti-hallucination safety net: if the AI dumped a (fabricated) menu into its
    # reply during ordering, swap in the REAL DB menu before it goes out.
    if phase == "ordering" and _looks_like_menu(reply):
        reply = await _render_menu(session, restaurant_id)

    # ── ordering actions ──────────────────────────────────────────────────
    if action == "show_menu":
        # Render the REAL menu from the DB — never let the LLM reproduce it
        # (it hallucinated entire fake menus). Ignore result.message.
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="show-menu", body=await _render_menu(session, restaurant_id),
        )
        return

    if action == "add_item":
        dish_query = data.get("dish_query", "")
        qty = int(data.get("qty") or 1)
        special_note = data.get("special_note", "")
        if dish_query and qty > _max_item_qty(restaurant):
            await _escalate_large_qty(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                qty=qty, dish_query=dish_query,
            )
            return
        if dish_query:
            status = await _execute_ai_add_item(
                session, conv, inbound, restaurant_id, dish_query, qty, special_note
            )
            if status == "added" and reply:
                await _send_text(session, conv=conv, inbound=inbound,
                                 restaurant_id=restaurant_id, prefix="ai-add", body=reply)
            elif status == "no_match":
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="ai-no-match",
                    body=f"Sorry, I couldn't find '{dish_query}' in our menu. "
                         "Try the exact dish name or check the menu spelling.",
                )
            # status == "awaiting_variant": the size question was already sent;
            # suppress the AI reply so the customer sees only the one question.
        else:
            if reply:
                await _send_text(session, conv=conv, inbound=inbound,
                                 restaurant_id=restaurant_id, prefix="ai-reply", body=reply)
        return

    if action == "remove_item":
        dish_query = data.get("dish_query", "")
        raw_qty = data.get("qty")
        rm_qty = int(raw_qty) if raw_qty is not None else None
        outcome, dish_name = await _execute_ai_remove_item(
            session, conv, restaurant_id, dish_query, rm_qty
        )
        cart = await _build_cart_summary(session, conv)
        if outcome == "removed":
            body = f"Done — removed {dish_name} ✅{_cart_tail(cart)}"
        elif outcome == "reduced":
            body = f"Done — removed {rm_qty}x {dish_name} ✅{_cart_tail(cart)}"
        elif outcome == "not_in_cart":
            body = f"{dish_name} isn't in your cart.{_cart_tail(cart)}"
        else:  # no_match
            body = reply or (
                f"I couldn't find '{dish_query}' to remove. Tell me the dish name "
                "and I'll take it off 😊"
            )
        await _send_text(session, conv=conv, inbound=inbound,
                         restaurant_id=restaurant_id, prefix="ai-remove", body=body)
        return

    if action == "update_qty":
        dish_query = data.get("dish_query", "")
        qty = int(data.get("qty") or 1)
        if dish_query and qty > _max_item_qty(restaurant):
            await _escalate_large_qty(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                qty=qty, dish_query=dish_query,
            )
            return
        outcome, dish_name = await _execute_ai_update_qty(
            session, conv, restaurant_id, dish_query, qty
        )
        cart = await _build_cart_summary(session, conv)
        if outcome == "updated":
            body = f"Updated — {qty}x {dish_name} ✅{_cart_tail(cart)}"
        elif outcome == "removed":
            body = f"Done — removed {dish_name} ✅{_cart_tail(cart)}"
        elif outcome == "not_in_cart":
            body = f"{dish_name} isn't in your cart yet — want me to add {qty}? 😊"
        else:  # no_match
            body = reply or (
                f"I couldn't find '{dish_query}' in your cart to change. "
                "Which dish should I update?"
            )
        await _send_text(session, conv=conv, inbound=inbound,
                         restaurant_id=restaurant_id, prefix="ai-qty", body=body)
        return

    if action == "proceed_to_address":
        cart = await _build_cart_summary(session, conv)
        if not cart:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ai-empty-cart",
                body="Your cart is empty — please add at least one dish first! 😊",
            )
            return
        _set_state(conv, dialogue_phase="address_capture", dialogue_state="address_capture")
        # Returning customer → offer their saved address up front (one tap to reuse,
        # or "New address" to enter once). Prevents the type-then-offered-then-retype
        # double entry. New customers fall through to the location-pin ask below.
        if not conv.state.get("address_offer_made"):
            if await _offer_saved_address_if_any(session, conv, inbound, restaurant_id):
                return
        # New customer, no saved address: DETERMINISTICALLY request the WhatsApp
        # location pin. We do NOT forward the LLM's reply here — the model tends to
        # ask for a free-text address, which yields NO coordinates: dispatch then
        # can't route the rider to the customer (it falls back to the restaurant
        # location) and the fee/radius check has no real distance. The pin is
        # mandatory; the follow-up apt/building/receiver collection stays AI-driven.
        await _send_location_request(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-proceed-addr-loc",
            body="Great! Please share your delivery location 📍 — tap the button below "
                 "to send your pin so the rider reaches you exactly.",
        )
        return

    # ── address_capture actions ───────────────────────────────────────────
    if action == "send_location_request":
        _set_state(conv, dialogue_phase="address_capture", dialogue_state="address_capture")
        await _send_location_request(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="loc-request",
            body=reply or "Please share your delivery location 📍 — tap the button below to send your pin.",
        )
        return

    if action == "use_saved_address":
        saved_id = conv.state.get("saved_address_id")
        if saved_id:
            _set_state(conv, pending_address_id=saved_id, dialogue_phase="awaiting_confirmation",
                       dialogue_state="order_confirmation")
            await _attach_saved_address_to_order(session, conv, inbound, restaurant_id,
                                                  saved_id, restaurant)
        else:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="no-saved-addr",
                body="I couldn't find your saved address. Please share your location 📍",
            )
        return

    if action == "save_address_text":
        apt_room = data.get("apt_room", "")
        building = data.get("building", "")
        receiver_name = data.get("receiver_name", "")
        # A text address carries NO coordinates. Without a shared location pin the
        # order would have no real drop-off: dispatch falls back to the restaurant
        # location and the fee/radius check is meaningless. So if no pin has been
        # shared yet, re-request the location instead of saving the address.
        if conv.state.get("pin_lat") is None:
            _set_state(conv, dialogue_phase="address_capture",
                       dialogue_state="address_capture")
            await _send_location_request(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="need-location-pin",
                body="Almost there! Please share your delivery location 📍 first — "
                     "tap the button below to send your pin so the rider can reach you "
                     "exactly. Then I'll take your apartment/building and receiver name.",
            )
            return
        if apt_room and building and receiver_name:
            await _execute_save_address(session, conv, inbound, restaurant_id,
                                        apt_room, building, receiver_name, restaurant)
        else:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="addr-incomplete",
                body=reply or "I need all three: apartment number, building name, and receiver's name.",
            )
        return

    if action == "proceed_to_confirmation":
        _set_state(conv, dialogue_phase="awaiting_confirmation",
                   dialogue_state="order_confirmation")
        if reply:
            await _send_text(session, conv=conv, inbound=inbound,
                             restaurant_id=restaurant_id, prefix="ai-confirm", body=reply)
        return

    # ── awaiting_confirmation actions ─────────────────────────────────────
    if action == "confirm_order":
        await _execute_confirm_order(session, conv, inbound, restaurant_id)
        return

    if action == "request_modification":
        # Delegate to the full modify FSM flow (find order, set modify_items state, prompt)
        await _handle_modify_intent(session, conv, inbound, restaurant_id)
        return

    if action == "cancel_order":
        await _execute_cancel_order(session, conv, inbound, restaurant_id)
        return

    # ── post_order actions ────────────────────────────────────────────────
    if action == "status_query":
        await _handle_status_query(session, conv, inbound, restaurant_id)
        return

    # ── no_action (all phases) ────────────────────────────────────────────
    if reply:
        await _send_text(session, conv=conv, inbound=inbound,
                         restaurant_id=restaurant_id, prefix="ai-reply", body=reply)


async def _handle_location_pin(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant,
) -> None:
    """Process a location pin in address_capture phase.

    Validates deliverability (distance ≤ radius AND within a fee tier), then sends
    a DETERMINISTIC confirmation + asks for the apartment/room. This step is not
    delegated to the LLM: the model would sometimes reply with non-progressing
    filler ("let me check if we deliver…") and the conversation stalled after the
    customer shared their pin. The follow-up apt/building/receiver collection
    stays AI-driven.
    """
    from app.ordering.fees import UndeliverableError, calculate_fee, radius_km

    lat = float(inbound.payload.get("latitude", 0))
    lng = float(inbound.payload.get("longitude", 0))
    # Radius is driven by the restaurant's largest fee tier (single source of
    # truth — same threshold calculate_fee enforces below).
    settings = await _fee_settings_for(session, restaurant_id)
    max_km = radius_km(settings)

    dist_km = await _road_distance_km(restaurant.lat, restaurant.lng, lat, lng)

    async def _send_out_of_range() -> None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="out-of-range",
            body=(
                f"Sorry, your location is {dist_km:.1f} km away. "
                f"We deliver within {max_km:g} km. "
                "Unfortunately we can't deliver to you at this time 😔"
            ),
        )
        _set_state(conv, dialogue_phase="ordering", dialogue_state="greeting",
                   draft_order_id=None)

    if dist_km > max_km:
        await _send_out_of_range()
        return

    # Authoritative deliverability + fee from the restaurant's tiers.
    try:
        fee = calculate_fee(dist_km, settings)
    except UndeliverableError:
        await _send_out_of_range()
        return

    _set_state(
        conv,
        pin_lat=lat,
        pin_lon=lng,
        distance_km=dist_km,
        delivery_fee=str(fee),
        dialogue_phase="address_capture",
        dialogue_state="address_capture",
    )

    fee_line = "Delivery is free 🎉" if fee == 0 else f"Delivery fee: AED {Decimal(fee).normalize():f}"
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="location-confirmed",
        body=(
            f"Got it — we deliver to your area! 🚚 {fee_line}\n\n"
            "To finish, reply with your *apartment/room*, *building*, and "
            "*receiver name* — e.g. _101, Tower A, Ahmed_"
        ),
    )


# A bare "no more / that's it / done" reply to the "Anything else?" prompt must
# move the order to checkout — never re-add a dish. The LLM occasionally defaults
# to repeating the last add_item here, which loops ("Butter Chicken added!" on
# every "No"). This deterministic guard catches the common English/Hinglish
# closing phrases before the model runs, so the loop can't happen for them.
_CLOSING_PHRASES: frozenset[str] = frozenset({
    "no", "no more", "nope", "na", "nah", "np", "no thanks", "no thank you",
    "nothing", "nothing else", "nothing more", "that's all", "thats all",
    "that's it", "thats it", "thats all thanks", "done", "im done", "i'm done",
    "all done", "finish", "finished", "complete", "checkout", "check out",
    "proceed", "place order", "place the order", "order", "all good", "im good",
    "i'm good", "good", "bas", "bus", "khalas", "khalaas", "khallas", "enough",
})


def _normalise_closing(text: str | None) -> str:
    """Lowercase + strip punctuation/emoji/extra spaces so "No.", "Np!", and
    "That's all 🙏" all normalise to a comparable closing phrase."""
    import re

    if not text:
        return ""
    t = re.sub(r"[^\w\s']", " ", text.lower())
    return re.sub(r"\s+", " ", t).strip()


async def _handle_customer_ai(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant=None,
) -> None:
    """Phase-aware AI handler: owns the entire customer conversation."""
    from app.identity.models import Restaurant as RestaurantModel
    from app.llm.factory import get_conversation_agent
    from app.llm.port import ConversationAgentResult

    if restaurant is None:
        restaurant = await session.get(RestaurantModel, restaurant_id)

    restaurant_name = restaurant.name if restaurant else "Restaurant"
    phase = _resolve_phase(conv)
    history = await _build_history(session, conv, limit=10)
    context = await _build_context(session, conv, restaurant_id, phase, restaurant)

    # Deterministic closing-intent guard: in the ordering phase, a bare closing
    # reply with a non-empty cart goes straight to address capture — bypassing
    # the LLM so it can never loop by re-adding the last dish (observed bug).
    if (
        phase == "ordering"
        and inbound.type == MessageType.TEXT
        and _normalise_closing(inbound.payload.get("text")) in _CLOSING_PHRASES
        and (context.get("cart_summary") or "").strip()
    ):
        await _dispatch_action(
            session, conv, inbound, restaurant_id,
            ConversationAgentResult(
                message="Great! Let's get your delivery details 😊",
                action="proceed_to_address", action_data={},
            ),
            phase, restaurant,
        )
        return

    # Store saved_address_id in conv.state for use_saved_address action
    if "saved_address_id" in context:
        _set_state(conv, saved_address_id=context["saved_address_id"])

    agent = get_conversation_agent()
    try:
        result = await agent.respond(
            restaurant_name=restaurant_name,
            dialogue_phase=phase,
            history=history,
            context=context,
        )
    except Exception:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-fallback",
            body="Sorry, having a moment 😅 Type the dish name to order, or send 'hi' to start.",
        )
        return

    await _dispatch_action(
        session, conv, inbound, restaurant_id, result, phase, restaurant
    )


async def _resolve_counterpart(
    session: AsyncSession, restaurant_id: int, phone: str
):
    """Return ("rider", rider) if the phone is a rider for this tenant, else ("customer", None)."""
    from app.identity.models import Rider

    rider = await session.scalar(
        select(Rider).where(
            Rider.restaurant_id == restaurant_id, Rider.phone == phone
        )
    )
    return ("rider", rider) if rider is not None else ("customer", None)


async def _handle_rider_inbound(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    rider,
) -> None:
    """Rider-side handlers: location pings (button actions added in Task 11)."""
    from app.dispatch.rider_location import update_rider_location

    if inbound.type == MessageType.LOCATION:
        await update_rider_location(
            session,
            rider=rider,
            latitude=float(inbound.payload["latitude"]),
            longitude=float(inbound.payload["longitude"]),
        )
        # Geofence check per spec §4.4 + transcript: if near current stop (~100m), send dual "Delivered" | "Delivered and Next Order Location"
        # Button click is ONLY way to reveal next location (flow integrity). Power bank provided per ops policy for all-day location.
        from app.dispatch.rider_flow import check_and_send_near_dual_if_applicable
        await check_and_send_near_dual_if_applicable(session, restaurant_id=restaurant_id, rider=rider)
        return

    if inbound.type == MessageType.BUTTON_REPLY:
        # Accept either payload key shape ("button_id" from dispatch buttons,
        # "id" from the shared button helper).
        button_id = inbound.payload.get("button_id") or inbound.payload.get("id", "")
        # Payloads can be stale/malformed (reassigned batch, a test send, a
        # double-tap) — parse defensively and let the handlers fall back rather
        # than crashing on int("test") or silently no-op'ing.
        arg = button_id.split(":", 1)[1] if ":" in button_id else ""
        arg_id = int(arg) if arg.isdigit() else None
        if button_id.startswith("picked:"):
            from app.dispatch.rider_flow import handle_orders_picked

            await handle_orders_picked(
                session,
                restaurant_id=restaurant_id,
                rider=rider,
                batch_id=arg_id,
                trigger_msg_id=inbound.wa_message_id,
            )
        elif button_id.startswith(("delivered:", "delivered_next:")):
            from app.dispatch.rider_flow import handle_delivered

            if arg_id is not None:
                await handle_delivered(
                    session,
                    restaurant_id=restaurant_id,
                    rider=rider,
                    order_id=arg_id,
                    trigger_msg_id=inbound.wa_message_id,
                )
        return
    # Other rider message types (e.g. free text) are ignored — flow is button-only.


async def handle_inbound(
    session: AsyncSession,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Main entry point: load conversation → record message → dispatch state handler."""
    counterpart, rider = await _resolve_counterpart(
        session, restaurant_id, inbound.from_phone
    )
    conv = await get_or_create_conversation(
        session,
        restaurant_id=restaurant_id,
        phone=inbound.from_phone,
        counterpart=counterpart,
    )
    # Heal stale counterpart — phone may have been registered as a rider after
    # an initial customer-side conversation was already created.
    if conv.counterpart != counterpart:
        conv.counterpart = counterpart

    await record_message(
        session,
        conversation_id=conv.id,
        direction="inbound",
        wa_message_id=inbound.wa_message_id,
        msg_type=str(inbound.type),
        payload=inbound.payload,
        ts=inbound.timestamp,
    )

    # Opt-out — exact STOP keywords + natural-language phrases.
    # Checked before any dialogue processing so AI never sees opt-out messages.
    from app.marketing.optout import is_optout_intent, is_stop_keyword, record_opt_out
    _opt_text = inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""
    _is_kw = is_stop_keyword(_opt_text)
    _is_nl = not _is_kw and is_optout_intent(_opt_text)
    if _is_kw or _is_nl:
        await record_opt_out(
            session,
            restaurant_id=restaurant_id,
            phone=inbound.from_phone,
            source="stop_keyword" if _is_kw else "natural_language",
        )
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "You've been unsubscribed from marketing messages. Reply START to re-subscribe."},
            idempotency_key=f"stop-ack-{inbound.wa_message_id}",
        )
        return  # do not process further

    # Manual takeover: bot is silent, human handles it
    if conv.manual_takeover:
        return

    # Rider conversations bypass the customer dialogue entirely.
    if counterpart == "rider":
        await _handle_rider_inbound(session, conv, inbound, restaurant_id, rider)
        return

    # ── Customer conversation (full AI) ────────────────────────────────────
    from app.identity.models import Restaurant as RestaurantModel
    restaurant = await session.get(RestaurantModel, restaurant_id)

    # A pure greeting ("hi", "As salam walekum", "hello") means START FRESH — in
    # ANY state, not just on first contact. Drop any stale/abandoned draft so an
    # old, never-purchased cart can never silently carry into the new order. This
    # matches the "Send 'hi' to start a new order" copy used throughout. A message
    # that mixes a greeting with an order ("hi, one biryani") is NOT a pure
    # greeting and falls through to the ordering flow so the dish still lands.
    if inbound.type == MessageType.TEXT and _is_pure_greeting(inbound.payload.get("text")):
        if conv.state.get("draft_order_id") is not None:
            _logger.info("greeting reset abandoned draft for conv=%s", conv.id)
        _set_state(conv, dialogue_state="greeting", dialogue_phase="ordering",
                   draft_order_id=None, pending_order_id=None,
                   awaiting_variant=None, variant_retries=None)
        await _handle_greeting(session, conv, inbound, restaurant_id)
        return

    # A pending serving-size question takes the next text reply (e.g. "4 serve")
    # before the AI runs, so the answer prices the deferred item instead of being
    # re-interpreted as a new order. Greeting/STOP above already pre-empt this.
    if conv.state.get("awaiting_variant"):
        if await _handle_variant_reply(session, conv, inbound, restaurant_id):
            return

    # Location pin → address capture handler (needs geo validation before AI).
    # Pings outside address_capture (e.g. repeated live-location updates after
    # address is confirmed) are silently dropped — no AI call, no reply.
    if inbound.type == MessageType.LOCATION:
        phase = _resolve_phase(conv)
        if phase == "address_capture":
            await _handle_location_pin(session, conv, inbound, restaurant_id, restaurant)
        return

    # Modify FSM states: route to dedicated handlers (preserves SLA-restart and audit logic)
    state_key = conv.state.get("dialogue_state", "")
    if state_key == "modify_items":
        await _handle_modify_items(session, conv, inbound, restaurant_id)
        return
    if state_key == "modify_confirm":
        await _handle_modify_confirm(session, conv, inbound, restaurant_id)
        return

    # Saved-address offer buttons → handled deterministically (not via the AI) so the
    # customer's choice is honoured exactly and a typed address is never asked twice.
    if inbound.type == MessageType.BUTTON_REPLY:
        btn_id = inbound.payload.get("id", "")
        if btn_id == "use_saved_address":
            saved_id = conv.state.get("saved_address_id") or await _resolve_saved_address_id(
                session, restaurant_id, inbound.from_phone
            )
            if saved_id:
                await _attach_saved_address_to_order(
                    session, conv, inbound, restaurant_id, saved_id, restaurant
                )
                return
        if btn_id == "new_address":
            _set_state(conv, address_offer_made=True,
                       dialogue_phase="address_capture", dialogue_state="address_capture")
            await _send_location_request(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ask-new-address",
                body="Please share your delivery location 📍 — tap the button below to send your pin.",
            )
            return
        if btn_id == "share_location":
            # Native location-request buttons no longer produce a button reply, but
            # a stale (pre-update) reply button could still arrive — re-send the
            # native request instead of falling through to the AI (which looped).
            _set_state(conv, dialogue_phase="address_capture", dialogue_state="address_capture")
            await _send_location_request(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="share-loc-retry",
                body="Please tap the button below to share your delivery location 📍, "
                     "or use 📎 → Location.",
            )
            return

    # Explicit menu request → render the REAL menu deterministically in ANY phase.
    # Outside the ordering phase the LLM has no show_menu action, so it emits
    # filler like "Sure! Here's our menu 🍛" with no dishes (or fabricates one).
    # After a completed order (post_order) a menu request means "order again", so
    # reset to a fresh ordering session so the next dish pick is valid.
    if inbound.type == MessageType.TEXT:
        text = (inbound.payload.get("text") or "").strip().lower()
        if _is_menu_request(text):
            if _resolve_phase(conv) == "post_order":
                _set_state(
                    conv,
                    dialogue_phase="ordering",
                    dialogue_state="collecting_items",
                    draft_order_id=None,
                    pending_order_id=None,
                )
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="menu-request", body=await _render_menu(session, restaurant_id),
            )
            return
        # "Where is my order / can I see the live location" → answer with the
        # current status + ETA + the live tracking link, deterministically.
        if _is_tracking_query(text):
            await _handle_status_query(session, conv, inbound, restaurant_id)
            return
        # "What's your location / I'll come direct" → send the restaurant's pin
        # deterministically (the LLM has no pin and would ask the CUSTOMER for
        # theirs). Skip while capturing the delivery address so we don't talk over
        # that flow — there "share location" means the customer's own pin.
        if _resolve_phase(conv) != "address_capture" and _is_restaurant_location_request(text):
            await _handle_restaurant_location_request(
                session, conv, inbound, restaurant_id, restaurant
            )
            return

    # All remaining text + button_reply → AI
    await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
