import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.conversation.models import Conversation
from app.conversation.service import get_or_create_conversation, record_message
from app.ordering.matching import (
    MatchConfidence,
    bundle_variant_for_qty,
    find_dish_matches,
    resolve_variant,
)
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


# A price mention: any currency token followed by a number (e.g. "AED 28", "Rs.5", "$3").
# Bullet style is IGNORED on purpose — the LLM dumps menus with emoji bullets ("🍗 X,
# AED 20"), plain "1x X AED 20", or "• X — AED 28"; all must be caught.
_PRICE_TOKEN = _re.compile(r"(?:AED|aed|Rs\.?|₹|\$)\s*\d", _re.IGNORECASE)
# Lines that legitimately carry a price but are NOT a menu (order/cart summary lines).
# Excluded so a reply that mentions ONE dish plus a total isn't mistaken for a menu.
_SUMMARY_LINE = _re.compile(
    r"\b(total|subtotal|delivery|fee|eta|payment|deliver to|cod|cash on delivery)\b",
    _re.IGNORECASE,
)


def _looks_like_menu(text: str) -> bool:
    """True if an AI reply appears to list dishes+prices (≥2 priced items).

    Safety net: the LLM sometimes fabricates a menu / a multi-item cart in free text
    (often with emoji bullets that older bullet-only detection missed). Any such reply
    is replaced with the REAL, mode-correct menu before it reaches the customer. We
    count price mentions OUTSIDE order/cart-summary lines, so a single dish answer or a
    legit total line is never mistaken for a menu, but two or more priced dishes are.
    """
    count = 0
    for line in (text or "").splitlines():
        if _SUMMARY_LINE.search(line):
            continue
        count += len(_PRICE_TOKEN.findall(line))
        if count >= 2:
            return True
    return False


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


def _is_cart_query(text: str) -> bool:
    """True for 'what's in my cart / show my order' style messages (lowercased).

    Answered deterministically with the real cart so the model can't mis-handle it
    (e.g. re-send the catalogue). Kept tight, and never matches an edit/cancel
    ('cancel my order', 'clear cart', 'add to cart') which are real actions."""
    t = text.strip().lower()
    if not t or len(t) > 45:
        return False
    if any(w in t for w in ("cancel", "clear", "empty", "remove", "delete", "add ")):
        return False
    if "cart" in t:                       # "my cart", "what's in my cart", "show cart"
        return True
    return any(p in t for p in (
        "what's in my order", "whats in my order", "my current order", "current order",
        "what did i order", "show my order", "what's my order", "my order so far",
    ))


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


def _is_complaint(text: str | None) -> bool:
    """True for a post-delivery complaint about an order that already arrived.

    Conservative on purpose: only fires on clear dissatisfaction keywords so it
    never hijacks a normal status query or a new order. A match opens a human
    ticket — the AI never compensates (per the ticket design).
    """
    if not text:
        return False
    t = text.strip().lower()
    if not t or len(t) > 280:
        return False
    phrases = (
        "complaint", "complain", "refund", "money back", "i want my money",
        "cold food", "was cold", "is cold", "stale", "undercooked", "overcooked",
        "raw", "burnt", "burned", "spoiled", "rotten", "smell bad", "smells bad",
        "hair in", "insect", "plastic in", "foreign object", "food poisoning",
        "made me sick", "got sick", "wrong order", "wrong item", "wrong dish",
        "missing item", "item missing", "is missing", "didn't get", "did not get",
        "never arrived", "never received", "didn't receive", "did not receive",
        "not delivered", "rider was rude", "very rude", "so rude", "disgusting",
        "terrible", "horrible", "worst", "spilled", "leaked", "damaged",
        "bad quality", "poor quality", "not fresh", "i am not happy",
        "i'm not happy", "not satisfied", "very disappointed", "disappointed with",
    )
    return any(p in t for p in phrases)


def _is_tier_query(text: str | None) -> bool:
    """True for 'what tier am I / how do I reach Gold / my loyalty status' questions."""
    if not text:
        return False
    t = text.strip().lower()
    if not t or len(t) > 80:
        return False
    phrases = (
        "my tier", "what tier", "loyalty", "reach gold", "reach silver", "become gold",
        "how to reach", "my status", "member status", "am i gold", "am i silver",
        "next tier", "loyalty status", "my membership", "vip status",
    )
    return any(p in t for p in phrases)


def _is_resale_accept(text: str | None) -> bool:
    """True when the customer accepts a pending resale offer in words."""
    if not text:
        return False
    t = text.strip().lower()
    if not t or len(t) > 40:
        return False
    if t in {"yes", "yeah", "ok", "okay", "sure", "yes please"}:
        return True
    return any(p in t for p in ("grab", "take it", "i want it", "claim", "deal"))


def _is_claim_coupon(text: str | None) -> bool:
    """True when the customer asks to use/claim a coupon by intent (not the code).

    e.g. "claim my coupon", "use my coupon", "apply my discount". Only acted on at
    the order-summary step, and only if the customer actually has a coupon.
    """
    if not text:
        return False
    t = text.strip().lower()
    if not t or len(t) > 60:
        return False
    phrases = (
        "claim my coupon", "claim coupon", "use my coupon", "use coupon",
        "apply my coupon", "apply coupon", "redeem my coupon", "redeem coupon",
        "use my discount", "apply my discount", "use my voucher", "claim my voucher",
        "i have a coupon", "i have a voucher", "my coupon",
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


# Natural-language phrases that mean "don't phone me" — captured as a persistent
# customer contact preference and shown to the rider on every stop. Kept deliberately
# tight (must mention call/phone/ring) so ordinary words never trigger it.
_DO_NOT_CALL_PATTERNS = (
    "dont call", "don't call", "do not call", "no call", "no calls", "without calling",
    "dont phone", "don't phone", "do not phone", "no phone call", "dont ring",
    "don't ring", "do not ring", "no ringing", "message instead", "text instead",
    "just message", "just text", "only message", "only text", "message dont call",
    "dont call just", "please dont call", "kindly dont call",
)


def _mentions_do_not_call(text: str | None) -> bool:
    """True if the customer asked not to be phoned (rider should message only)."""
    if not text:
        return False
    t = " ".join(text.lower().split())
    t = t.replace("’", "'")  # normalise curly apostrophe
    return any(p in t for p in _DO_NOT_CALL_PATTERNS)


# Phrases that RE-ENABLE calling — clear a previously-set do_not_call preference.
_CAN_CALL_PATTERNS = (
    "you can call", "you may call", "u can call", "can call me", "please call",
    "pls call", "do call", "feel free to call", "calling is fine", "call is fine",
    "ok to call", "okay to call", "call me is fine", "you can phone", "call is ok",
    "calls are fine", "you can ring",
)


def _mentions_can_call(text: str | None) -> bool:
    """True if the customer said calling is OK (undo a prior 'don't call')."""
    if not text:
        return False
    t = " ".join(text.lower().split())
    t = t.replace("’", "'")
    return any(p in t for p in _CAN_CALL_PATTERNS)


# Dish-info questions ("what's special in X", "what's in X", "tell me about X") are
# answered with the dish's stored menu description VERBATIM when present, else a short
# human one-liner. Longest prefixes first so "what's special in" wins over "what's".
_DISH_INFO_PREFIXES = (
    "what's special in ", "what is special in ", "whats special in ",
    "what's special about ", "what is special about ", "whats special about ",
    "what is special with ", "what's special with ",
    "tell me more about ", "tell me about ", "more about ", "details of ",
    "details about ", "info on ", "info about ", "describe ",
    "what's in ", "what is in ", "whats in ",
    "what's ", "what is ", "whats ", "what about ",
)


def _dish_info_question(text: str | None) -> str | None:
    """If the message is a 'tell me about <dish>' style question, return the dish-name
    part (stripped of filler); else None. Caller guards against menu requests and only
    answers when it resolves to a real dish, so a non-dish 'what is …' falls through."""
    if not text:
        return None
    t = " ".join(text.lower().split()).replace("’", "'")
    for p in _DISH_INFO_PREFIXES:
        if t.startswith(p):
            name = t[len(p):].strip().rstrip("?").strip()
            for lead in ("the ", "a ", "an ", "this ", "that ", "your ", "our "):
                if name.startswith(lead):
                    name = name[len(lead):].strip()
            for tail in (" dish", " please", " pls", " like"):
                if name.endswith(tail):
                    name = name[: -len(tail)].strip()
            return name or None
    return None


def _trim_description(text: str) -> str:
    """Spec: customer-facing descriptions are at most 3 lines and carry no price."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[:3]).strip()


async def _answer_dish_info(
    session: AsyncSession, restaurant_id: int, name: str | None
) -> str | None:
    """Reply text for a dish-info question, or None to fall through to the AI.

    Shows the dish's stored menu description verbatim when it has one; otherwise a
    brief, human one-liner (never a price, ≤3 lines). Returns None when the query
    doesn't resolve to a single dish, so ordinary questions never get hijacked."""
    if not name:
        return None
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=name)
    if result.confidence != MatchConfidence.DIRECT or not result.candidates:
        return None
    dish = result.candidates[0]
    # Catalogue mode: never describe a text-menu dish that isn't in the catalogue.
    if await _catalog_excludes_dish(session, restaurant_id, dish):
        return None
    desc = (getattr(dish, "description", None) or "").strip()
    if desc:
        return _trim_description(desc)
    # No stored description → a short, human line so we still say *something*.
    line = ""
    try:
        from app.llm.factory import get_describer
        line = (get_describer().describe(dish.name, "") or "").strip()
    except Exception:
        line = ""
    if not line:
        line = f"{dish.name} is one of our favourites! Want me to add it? 😊"
    return _trim_description(line)


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


async def _render_catalog_menu(session: AsyncSession, restaurant_id: int) -> str:
    """Render the SYNCED Meta catalogue as categorized text.

    In catalogue mode this is the bot's menu knowledge — so it only ever talks about /
    recommends products that are actually in the catalogue (never a text-menu dish the
    customer can't order)."""
    from app.catalog.models import CatalogProduct

    products = (
        await session.scalars(
            select(CatalogProduct)
            .where(
                CatalogProduct.restaurant_id == restaurant_id,
                CatalogProduct.is_active.is_(True),
            )
            .order_by(CatalogProduct.category, CatalogProduct.name)
        )
    ).all()
    if not products:
        return "Our catalogue is currently empty. Please try again later."

    lines: list[str] = ["👋 *Welcome! Here's our menu*"]
    current_category: str | None = None
    for p in products:
        if p.category != current_category:
            current_category = p.category
            if current_category:
                lines.append(f"\n{_category_emoji(current_category)} *{current_category}*")
        price = _aed(p.price_aed) if p.price_aed is not None else "?"
        lines.append(f"• {p.name}: AED {price}")
    lines.append("\nJust tell me what you'd like and I'll add it to your order 😊")
    return "\n".join(lines)


async def _catalog_mode_on(session: AsyncSession, restaurant_id: int) -> bool:
    """True if this restaurant is in catalogue ordering mode."""
    from app.identity.models import Restaurant

    rest = await session.get(Restaurant, restaurant_id)
    return bool(rest is not None and (rest.settings or {}).get("catalog_ordering_enabled"))


async def _catalog_excludes_dish(session: AsyncSession, restaurant_id: int, dish) -> bool:
    """In CATALOGUE mode, True when ``dish`` is NOT part of the synced Meta catalogue —
    so the bot won't describe, recommend, or let a customer type-order a text-menu item
    that isn't actually orderable. Always False in text mode (no restriction)."""
    from app.identity.models import Restaurant

    rest = await session.get(Restaurant, restaurant_id)
    if rest is None or not (rest.settings or {}).get("catalog_ordering_enabled"):
        return False
    rid = getattr(dish, "catalog_retailer_id", None)
    if not rid:
        return True  # no catalogue link → not in the catalogue
    from app.catalog.models import CatalogProduct

    found = await session.scalar(
        select(CatalogProduct.id)
        .where(
            CatalogProduct.restaurant_id == restaurant_id,
            CatalogProduct.retailer_id == rid,
            CatalogProduct.is_active.is_(True),
        )
        .limit(1)
    )
    return found is None


async def _catalog_filter_candidates(session: AsyncSession, restaurant_id: int, candidates):
    """In CATALOGUE mode, drop candidates that aren't in the catalogue so a 'did you mean'
    prompt never shows a non-catalogue (text-menu) dish. No-op in text mode."""
    kept = []
    for d in candidates:
        if not await _catalog_excludes_dish(session, restaurant_id, d):
            kept.append(d)
    return kept


async def _render_menu(session: AsyncSession, restaurant_id: int) -> str:
    """Render the active menu as categorized text.

    Catalogue mode: the menu knowledge is the synced Meta catalogue, NOT the text-menu
    dishes — so the bot never offers items the customer can't order from the catalogue.
    """
    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu

    _rest = await session.get(Restaurant, restaurant_id)
    if _rest is not None and (_rest.settings or {}).get("catalog_ordering_enabled"):
        return await _render_catalog_menu(session, restaurant_id)

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
        lines.append(f"• {dish.name}: AED {price}")

    lines.append("\nJust tell me what you'd like and I'll add it to your order 😊")
    return "\n".join(lines)


async def _send_menu_or_catalog(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    prefix: str,
) -> bool:
    """Show the menu under the restaurant's STRICT mode (catalogue OR text, no mixing).

    * Catalogue mode (``catalog_ordering_enabled``): send the WhatsApp catalogue cards.
      NEVER the text list. If the cards can't be sent, ask the customer to type their
      order instead (the engine still parses typed items).
    * Text mode (default): send the OPS-managed text menu.

    Returns True if the catalogue was sent, False otherwise.
    """
    from app.identity.models import Restaurant

    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is not None and (restaurant.settings or {}).get("catalog_ordering_enabled"):
        from app.catalog.service import send_catalog

        sent = await send_catalog(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            idempotency_key=f"{prefix}-catalog-{conv.id}-{inbound.wa_message_id}",
        )
        if sent:
            _set_state(conv, dialogue_state="menu_sent")
            return True
        # Catalogue mode is strict — no text-menu fallback.
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix=f"{prefix}-nocat",
            body="Our catalogue is just loading 🙏 Please type what you'd like and I'll add it right away 😊",
        )
        _set_state(conv, dialogue_state="menu_sent")
        return False
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=prefix, body=await _render_menu(session, restaurant_id),
    )
    return False


async def _handle_greeting(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Send uploaded menu files (image/PDF) then a short prompt; fall back to text menu.

    Two STRICT, mutually exclusive modes (no mixing):
      * Catalogue mode (``catalog_ordering_enabled``): send the WhatsApp catalogue product
        cards and nothing else. The customer taps the catalogue and sends a basket, which
        joins this same conversation's cart. NEVER falls back to the text/image menu — if
        the catalogue can't be sent, we ask the customer to type their order instead.
      * Text mode (default): send the OPS-managed menu (image/PDF files + text list).
    """
    import base64

    from app.config import get_settings
    from app.identity.models import Restaurant
    from app.menu.models import Menu, MenuFile
    from app.menu.storage import FileBlobStore

    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is not None and (restaurant.settings or {}).get("catalog_ordering_enabled"):
        # Catalogue mode — strict. Send the cards; if they can't be sent, ask the
        # customer to type (the engine still parses typed items) but show NO text menu.
        from app.catalog.service import send_catalog

        sent = await send_catalog(
            session, restaurant_id=restaurant_id, to_phone=inbound.from_phone,
            idempotency_key=f"greeting-catalog-{conv.id}-{inbound.wa_message_id}",
        )
        if not sent:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="greeting-nocat",
                body="Our catalogue is just loading 🙏 Please type what you'd like and I'll add it right away 😊",
            )
        _set_state(conv, dialogue_state="menu_sent")
        return

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
    # Offer any cancelled-but-cooked food to this customer (fast, discounted).
    await _maybe_offer_resale(session, conv, inbound, restaurant_id)


async def _maybe_offer_resale(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> bool:
    """If a resale (cancelled-after-cooking) order is available to this customer,
    pitch it: ready now, delivered fast, at the restaurant's configured discount.
    Stores the offer id in conv.state so a 'grab'/button reply can accept it.
    Returns True if an offer was sent."""
    from app.identity.models import Restaurant
    from app.ordering.models import OrderItem
    from app.ordering.resale import resale_offer_for_customer

    restaurant = await session.get(Restaurant, restaurant_id)
    settings = (restaurant.settings or {}) if restaurant else {}
    offer = await resale_offer_for_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone, settings=settings,
    )
    if offer is None:
        return False
    order = offer["order"]
    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    dish_line = ", ".join(f"{i.qty}x {i.dish_name}" for i in items) or "a freshly-made meal"
    _set_state(conv, resale_offer_id=order.id)
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=f"resale-offer-{order.id}",
        body=(
            f"⚡ Ready *right now* — skip the wait!\n"
            f"{dish_line}\n"
            f"Just AED {_aed(offer['discounted_subtotal'])} "
            f"(save AED {_aed(offer['discount_aed'])}) — already cooked, delivered fast. 🛵"
        ),
        buttons=[{"id": f"resale_accept:{order.id}", "title": "Grab it ⚡"}],
    )
    return True


async def _handle_resale_accept(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int,
    order_id: int,
) -> None:
    """Customer accepted a resale offer. If they have a saved address, sell it now
    (mark RESOLD, spawn discounted ready order, dispatch to their address). Else ask
    them to share their location to claim it."""
    from app.identity.models import Restaurant
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Order
    from app.ordering.resale import accept_resale
    from app.ordering.service import get_last_address, get_or_create_customer

    resale_order = await session.get(Order, order_id)
    if resale_order is None or str(resale_order.status) != str(OrderStatus.ON_RESALE):
        _set_state(conv, resale_offer_id=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="resale-gone",
            body="Sorry, that deal was just taken 😕 Reply with a dish to order fresh.",
        )
        return
    customer = await get_or_create_customer(session, restaurant_id=restaurant_id, phone=inbound.from_phone)
    addr = await get_last_address(session, customer.id)
    if addr is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="resale-need-loc",
            body="Great choice! 📍 Share your delivery location and I'll send it right over.",
        )
        return
    restaurant = await session.get(Restaurant, restaurant_id)
    settings = (restaurant.settings or {}) if restaurant else {}
    new_order = await accept_resale(
        session, resale_order=resale_order, customer_id=customer.id, address_id=addr.id,
        settings=settings, distance_km=resale_order.distance_km,
    )
    _set_state(conv, resale_offer_id=None, dialogue_phase="post_order", dialogue_state="order_placed")
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=f"resale-accepted-{new_order.id}",
        body=(
            f"Yours! 🎉 Order #{new_order.order_number} — AED {_aed(new_order.total)} (COD).\n"
            f"It's already cooked and on its way fast. 🛵"
        ),
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
        # SAFETY GATE: never proceed to checkout on a missing, finalised, or empty cart
        # — doing so silently drops the order (kitchen gets nothing). Verify the draft
        # still exists, is still a draft, and actually has items.
        draft_order_id = conv.state.get("draft_order_id")
        order = await session.get(Order, draft_order_id) if draft_order_id else None
        if order is None or str(order.status) != "draft" or not await _order_has_items(
            session, order.id
        ):
            _set_state(conv, dialogue_state="collecting_items")
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
            body="Great! Please share your delivery location 📍. Tap the button below to send your pin.",
        )
        return

    # "What is X?" dish question → stored menu description (verbatim) when present,
    # else a short generated line via the describer.
    if dish_query.lower().startswith("what is "):
        item_name = dish_query[8:].strip().rstrip("?")
        desc = await _answer_dish_info(session, restaurant_id, item_name)
        if desc is None:
            # Catalogue mode: never invent a description for an item we can't confirm is
            # in the catalogue — redirect instead of describing a non-catalogue dish.
            if await _catalog_mode_on(session, restaurant_id):
                desc = "I can only help with items on our catalogue 🛍️ Tap the catalogue to see what's available."
            else:
                from app.llm.factory import get_describer
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
            # Catalogue mode: only offer candidates that are actually in the catalogue.
            cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
            if not cands:
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="not-in-catalog",
                    body="That isn't on our catalogue 🛍️ Please tap the catalogue to add items.",
                )
                return
            options = " or ".join(
                f"{d.name} (AED {_aed(d.price_aed)})" for d in cands[:3]
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
    # Catalogue mode: only catalogue items are orderable. A typed text-menu dish that
    # isn't in the catalogue is treated as not found (no text-menu leak).
    if await _catalog_excludes_dish(session, restaurant_id, dish):
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="not-in-catalog",
            body="That isn't on our catalogue 🛍️ Please tap the catalogue to add items.",
        )
        return
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    # A pointer that survived a placed/cancelled order is not a live cart — start fresh
    # rather than appending new items onto an already-finalised order.
    if order is not None and str(order.status) != "draft":
        order = None
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
            parts.append(f"{labels[wd]} {_fmt_time(window[0])} to {_fmt_time(window[1])}")
        else:
            parts.append(f"{labels[wd]} closed")
    schedule = "; ".join(parts)

    now = datetime.now(ZoneInfo("Asia/Dubai"))
    if is_open(open_hours, now):
        status = "currently OPEN"
    else:
        nxt = next_opening_label(open_hours, now)
        status = f"currently CLOSED, next opening {nxt}" if nxt else "currently closed"
    return f"Opening hours: {schedule}. We are {status}."


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
                body="Please share your delivery location 📍. Tap the button below to send your pin.",
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
    await _send_order_summary(
        session, conv, inbound, restaurant_id, order, allow_new_address=True
    )


async def _redeem_context(
    session: AsyncSession, *, restaurant_id: int, customer_id: int
) -> tuple[Decimal, list]:
    """Return (wallet_available, redeemable_coupons-for-this-customer).

    Used to decide whether to show the redeem option at checkout — only customers
    who actually have wallet credit or a coupon issued to them ever see it.
    """
    from datetime import datetime, timezone

    from app.coupons.models import Coupon
    from app.wallet import service as wallet_service

    acc = await wallet_service.get_or_create_account(
        session, restaurant_id=restaurant_id, customer_id=customer_id
    )
    wallet_available = await wallet_service.available(session, account_id=acc.id)

    now = datetime.now(timezone.utc)
    coupons = (
        await session.scalars(
            select(Coupon).where(
                Coupon.restaurant_id == restaurant_id,
                Coupon.customer_id == customer_id,
                Coupon.status.in_(("issued", "active")),
            )
        )
    ).all()
    active = [c for c in coupons if c.expires_at is None or c.expires_at > now]
    return wallet_available, active


async def _send_order_summary(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    order,
    *,
    allow_new_address: bool = False,
) -> None:
    """Render order summary with totals + ETA and confirm/cancel buttons.

    When ``allow_new_address`` is True (returning customer whose saved address was
    auto-attached), a "Use new address" button is added so they can switch the
    drop-off without us having to ask "use saved address?" as a separate step.
    """
    from app.ordering.models import CustomerAddress, OrderItem
    from app.weather.factory import get_weather_port

    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    item_lines = "\n".join(
        f"  {it.qty}x {it.dish_name}"
        f"{f' ({it.variant_name})' if it.variant_name else ''}: "
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

    # Redeem options — shown ONLY when the customer actually has wallet credit or a
    # coupon issued to them. No credit + no coupon → no redeem line at all.
    redeem_block = ""
    wallet_available, active_coupons = await _redeem_context(
        session, restaurant_id=restaurant_id, customer_id=order.customer_id
    )
    redeem_lines = []
    if wallet_available > Decimal("0.00"):
        redeem_lines.append(
            f"💳 You have AED {_aed(wallet_available)} wallet credit — "
            f"it'll be applied automatically."
        )
    if active_coupons:
        redeem_lines.append("🏷️ Have a coupon? Send the code to apply it.")
    if redeem_lines:
        redeem_block = "\n" + "\n".join(redeem_lines) + "\n"

    summary = (
        f"Order summary:\n{item_lines}\n\n"
        f"Subtotal: AED {_aed(order.subtotal)}\n"
        f"Delivery fee: AED {_aed(order.delivery_fee_aed)}\n"
        f"Total: AED {_aed(order.total)}\n"
        f"Payment: COD (cash on delivery)\n"
        f"{address_block}"
        f"ETA: 40 minutes{weather_note}\n"
        f"{redeem_block}\n"
        f"Confirm your order?"
    )
    buttons = [{"id": "confirm_order", "title": "Confirm order"}]
    if allow_new_address:
        # WhatsApp caps interactive replies at 3 buttons; this keeps us at exactly 3.
        buttons.append({"id": "use_new_address", "title": "Use new address"})
    buttons.append({"id": "cancel_order", "title": "Cancel order"})
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-summary", body=summary,
        buttons=buttons,
    )


async def _redeem_coupon_at_checkout(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    code: str,
) -> None:
    """Apply a coupon the customer typed at the order-summary step.

    Redeems against the pending order, reduces the total, and re-sends the summary
    so the customer sees the new total before confirming. Caller has verified the
    code belongs to this customer.
    """
    from app.coupons.service import CouponError, validate_and_redeem
    from app.ordering.models import Order

    order_id = conv.state.get("pending_order_id")
    order = await session.get(Order, order_id) if order_id else None
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="coupon-no-order",
            body="There's no order to apply a coupon to right now.",
        )
        return
    try:
        redemption = await validate_and_redeem(
            session,
            restaurant_id=restaurant_id,
            code=code,
            customer_id=order.customer_id,
            order_id=order.id,
            order_subtotal_aed=order.subtotal,
            idempotency_key=f"order:{order.id}:coupon",
        )
    except CouponError as e:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="coupon-rejected",
            body=f"Sorry, I couldn't apply that coupon ({e}). You can still confirm your order.",
        )
        return
    discount = redemption.discount_applied_aed
    order.coupon_id = redemption.coupon_id
    order.total = max(order.total - discount, order.delivery_fee_aed)
    await session.flush()
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=f"coupon-applied-{redemption.id}",
        body=f"Coupon applied — AED {_aed(discount)} off! 🎉 Here's your updated order:",
    )
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


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
        # SAFETY GATE: never confirm an empty order (kitchen can't fulfil it).
        if not await _order_has_items(session, order.id):
            _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="confirm-empty",
                body="Your cart is empty, so there's nothing to confirm. Please add a dish to order 😊",
            )
            return
        await finalize_confirmation(session, order=order, actor="customer")
        # Drop the cart pointers now the order is placed — a later order must start a
        # fresh draft, not reuse this (now confirmed) order's id.
        _set_state(conv, dialogue_state="order_placed",
                   draft_order_id=None, pending_order_id=None)
        from app.ordering.payments import cod_due_aed

        due = cod_due_aed(order)
        if order.wallet_applied_aed and order.wallet_applied_aed > 0:
            payment_line = (
                f"Total: AED {_aed(order.total)}\n"
                f"Wallet credit applied: AED {_aed(order.wallet_applied_aed)}\n"
                f"Pay on delivery: AED {_aed(due)} (COD)\n"
            )
        else:
            payment_line = f"Total: AED {_aed(order.total)} (COD, cash on delivery).\n"
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-confirmed",
            body=(
                f"Order confirmed! Order #{order.order_number}.\n"
                f"{payment_line}"
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
            body="No problem, your order has been cancelled. Send 'hi' to start again.",
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
        item_name = dish_query[8:].strip().rstrip("?")
        desc = await _answer_dish_info(session, restaurant_id, item_name)
        if desc is None:
            if await _catalog_mode_on(session, restaurant_id):
                desc = "I can only help with items on our catalogue 🛍️ Tap the catalogue to see what's available."
            else:
                from app.llm.factory import get_describer
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
        # Catalogue mode: only offer candidates that are actually in the catalogue.
        cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
        if not cands:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="not-in-catalog-mod",
                body="That isn't on our catalogue 🛍️ Please tap the catalogue to choose items.",
            )
            return
        options = " or ".join(
            f"{d.name} (AED {_aed(d.price_aed)})" for d in cands[:3]
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ambiguous-mod",
            body=f"Did you mean {options}? Please reply with the dish number.",
        )
        return

    # Direct match: accumulate in proposed (replaces cart-add in collecting_items)
    dish = result.candidates[0]
    # Catalogue mode: can't modify an order to add a non-catalogue (text-menu) item.
    if await _catalog_excludes_dish(session, restaurant_id, dish):
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="not-in-catalog-mod",
            body="That isn't on our catalogue 🛍️ Please tap the catalogue to choose items.",
        )
        return
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
        f"  {it.qty}x {it.dish_name}: "
        f"AED {_aed(it.price_aed * it.qty)}"
        for it in current_items
    ) or "  (none)"

    prop_lines = "\n".join(
        f"  {p['qty']}x {p.get('name', '?')}: "
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

        # SAFETY GATE: if every proposed dish has since vanished (e.g. removed from the
        # menu), the modify cannot run. Don't claim the order was "updated" — that's a
        # silent no-op that misleads the customer. Keep the original order and say so.
        if not new_items:
            _set_state(conv, dialogue_state="order_placed", modify_order_id=None, modify_proposed=None)
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-unavailable",
                body=("Those items are no longer available, so your order was not changed. "
                      f"Your original Order #{order.order_number} still stands."),
            )
            return

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
            body="Modification cancelled. Original order unchanged. Send 'hi' if needed.",
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
        body=f"📍 Here's *{name}*. Tap the pin above for directions. See you soon! 🛵",
    )


async def _handle_complaint(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant,
) -> None:
    """Open a HUMAN complaint ticket and acknowledge — the AI never resolves it.

    Resolves the customer + their latest order, creates a Ticket, replies with a
    fixed acknowledgement, and notifies the manager. Compensation (refund /
    replacement / mark-resolved) is a manager action via the dashboard.
    """
    from app.ordering.models import Customer, Order
    from app.tickets.service import create_ticket
    from app.whatsapp.port import OutboundMessageType

    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == inbound.from_phone,
        )
    )
    if customer is None:
        # No record — let the AI handle it (it will hand out the contact number).
        await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
        return

    latest_order = await session.scalar(
        select(Order)
        .where(Order.customer_id == customer.id, Order.restaurant_id == restaurant_id)
        .order_by(Order.id.desc())
        .limit(1)
    )
    text = (inbound.payload.get("text") or "").strip()
    ticket = await create_ticket(
        session,
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        order_id=latest_order.id if latest_order else None,
        source_message=text or None,
    )
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=f"complaint-ack-{ticket.id}",
        body="I'm really sorry to hear that 🙏 I've logged this and our team will "
             "look into it and get back to you shortly.",
    )
    # Notify the manager (best-effort; idempotent on the ticket).
    if restaurant is not None and getattr(restaurant, "phone", None):
        order_ref = latest_order.order_number if latest_order else "—"
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=restaurant.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={
                "body": f"⚠️ New complaint ticket #{ticket.id} (order {order_ref}) "
                        f"from {customer.phone}: \"{text[:160]}\". Open the dashboard to resolve."
            },
            idempotency_key=f"ticket:{ticket.id}:mgr-alert",
        )


async def _handle_tier_query(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant,
) -> None:
    """Answer 'what tier am I / how do I reach Gold' from the restaurant's loyalty
    settings — deterministic, no LLM. No-op-to-AI if loyalty disabled / no customer."""
    from app.loyalty.service import tier_progress_text
    from app.ordering.models import Customer

    settings = (restaurant.settings or {}) if restaurant else {}
    if not (settings.get("loyalty", {}) or {}).get("enabled"):
        await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
        return
    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id, Customer.phone == inbound.from_phone
        )
    )
    if customer is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="tier-no-customer",
            body="Place your first order to start earning loyalty rewards! 😊",
        )
        return
    body = tier_progress_text(
        settings, total_orders=customer.total_orders, total_spend=customer.total_spend,
        last_order_at=customer.last_order_at,
    )
    if customer.loyalty_tier:
        body = f"You're a {customer.loyalty_tier.title()} member 🌟\n{body}"
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="tier-progress", body=body,
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
        if m.type in ("text", "audio"):
            # Voice notes (type "audio") carry their transcript under "text".
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
        if (
            order is not None
            and str(order.status) == "draft"
            and await _order_has_items(session, order.id)
        ):
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


def _cart_expired(order, restaurant) -> bool:
    """True if a draft cart has been quiet past the restaurant's cart_expiry_minutes —
    used so a returning customer's stale cart is started fresh rather than resumed."""
    from datetime import datetime, timezone

    settings = (getattr(restaurant, "settings", None) or {}) if restaurant else {}
    expiry_min = int(settings.get("cart_expiry_minutes", 60))
    last = getattr(order, "updated_at", None)
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 60.0 >= expiry_min


async def _offer_resume_cart(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> None:
    """Returning customer still has an in-progress cart → show it and ask whether to
    continue it or start a new order, instead of silently wiping or appending."""
    cart = await _build_cart_summary(session, conv)
    _set_state(conv, dialogue_phase="ordering", dialogue_state="resume_offer")
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="resume-cart",
        body=(
            "Welcome back! 👋 You still have an order in progress:\n\n"
            f"🛒 {cart}\n\nContinue this order, or start a new one?"
        ),
        buttons=[
            {"id": "resume_cart", "title": "Continue order"},
            {"id": "new_cart", "title": "Start new"},
        ],
    )


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

        if msg.type in ("text", "audio"):
            # Voice notes (type "audio") carry their transcript under "text".
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
        "add_item", "remove_item", "update_qty", "clear_cart", "proceed_to_address",
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
                f"  {it.qty}x {it.dish_number}. {it.dish_name}: "
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


async def _ensure_draft_order(
    session: AsyncSession, conv, inbound: InboundMessage, restaurant_id: int
):
    """Return this conversation's draft order, creating one if needed.

    On creation, clears address/location state left over from a previous order so a
    returning customer is re-offered their saved address and the fee/distance is
    recomputed for THIS order rather than reused from the last one."""
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Order
    from app.ordering.service import create_draft_order, get_or_create_customer

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone
    )
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    # Only an order that is STILL a draft is this conversation's live cart. A pointer
    # left over from a placed/cancelled order (we don't clear it everywhere) must NOT
    # be reused — otherwise new items append to an already-confirmed order and the
    # summary renders a stale cart. Treat a non-draft pointer as "no cart" → fresh draft.
    if order is not None and str(order.status) != str(OrderStatus.DRAFT):
        order = None
    if order is None:
        order = await create_draft_order(session, restaurant_id=restaurant_id, customer_id=customer.id)
        _set_state(
            conv, draft_order_id=order.id, address_offer_made=None,
            saved_address_declined=None, saved_address_id=None,
            pin_lat=None, pin_lon=None, distance_km=None, delivery_fee=None,
        )
    return order


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
    """Ensure a draft order exists and add the dish (optionally a chosen serving-size
    variant) to it. Shared by the direct add path and the variant paths."""
    from app.ordering.service import add_item

    order = await _ensure_draft_order(session, conv, inbound, restaurant_id)
    await add_item(session, order=order, dish=dish, qty=qty, notes=notes, variant=variant)
    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
    return order


def _parse_bundle_choice(inbound: InboundMessage) -> str | None:
    """Read a yes/no answer to a bundle offer → "bundle", "separate", or None."""
    if inbound.type != MessageType.TEXT:
        return None
    t = (inbound.payload.get("text") or "").strip().lower()
    if not t:
        return None
    if any(w in t for w in (
        "separate", "single", "individual", "apart", "two plate", "2 plate",
        "no thanks", "nope", "don't", "dont",
    )):
        return "separate"
    if any(w in t for w in (
        "yes", "yeah", "yep", "sure", "ok", "okay", "combo", "bundle", "together",
        "share", "haan", "aiwa", "add that", "do it",
    )):
        return "bundle"
    # A bare "no" (not part of "no thanks", handled above) → keep separate.
    if t in ("no", "naa", "nah"):
        return "separate"
    return None


async def _offer_bundle_choice(
    session: AsyncSession, conv, inbound: InboundMessage, restaurant_id: int,
    *, dish, qty: int, notes: str | None, bundle: dict,
) -> None:
    """Ask (in plain text) whether to use a serving-size bundle for this quantity,
    or keep the items separate. Defers the add until the customer answers."""
    single_total = _aed(Decimal(str(dish.price_aed)) * qty)
    bundle_price = _aed(Decimal(str(bundle["price_aed"])))
    _set_state(conv, awaiting_bundle={
        "dish_id": dish.id, "qty": qty, "notes": notes,
        "bundle_name": bundle["name"], "bundle_price": str(bundle["price_aed"]),
    })
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="bundle-offer",
        body=(
            f"We have a {dish.name} ({bundle['name']}) for AED {bundle_price} "
            f"(vs AED {single_total} for {qty} separate). Add the combo? "
            f"Reply yes, or no to keep them separate 😊"
        ),
    )


async def _handle_bundle_choice(
    session: AsyncSession, conv, inbound: InboundMessage, restaurant_id: int
) -> bool:
    """Apply a pending bundle offer from the customer's yes/no reply.

    "yes" → one bundle at its price; "no"/unclear → the items stay separate
    (single × qty). Returns True if it handled the message."""
    pending = conv.state.get("awaiting_bundle")
    if not pending:
        return False
    from sqlalchemy import delete as sa_delete

    from app.menu.models import Dish
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item

    dish = await session.get(Dish, pending.get("dish_id"))
    if dish is None:
        _set_state(conv, awaiting_bundle=None)
        return False

    qty = int(pending.get("qty") or 1)
    notes = pending.get("notes")
    choice = _parse_bundle_choice(inbound)  # default (None) → keep separate
    order = await _ensure_draft_order(session, conv, inbound, restaurant_id)

    # Replace any existing lines for this dish (e.g. the single from "make it 2")
    # with the chosen representation.
    await session.execute(
        sa_delete(OrderItem).where(
            OrderItem.order_id == order.id, OrderItem.dish_id == dish.id
        )
    )
    await session.flush()

    if choice == "bundle":
        bundle = {"name": pending["bundle_name"], "price_aed": pending["bundle_price"]}
        await add_item(session, order=order, dish=dish, qty=1, notes=notes, variant=bundle)
        label = f"{dish.name} ({bundle['name']})"
    else:
        await add_item(session, order=order, dish=dish, qty=qty, notes=notes)
        label = f"{qty}x {dish.name}"

    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items",
               awaiting_bundle=None)
    cart = await _build_cart_summary(session, conv)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="bundle-applied", body=f"Added {label} ✅{_cart_tail(cart)}",
    )
    return True


# Menu categories whose variants are SIZES the customer picks (drinks), not
# bigger-portion serving bundles like food. For these the bot ASKS which size when
# none is named, instead of defaulting to a base serve.
_DRINK_CATEGORY_HINTS = (
    "drink", "beverage", "juice", "soda", "water", "tea", "coffee", "shake",
    "smoothie", "mocktail", "lassi", "cola", "soft drink", "mojito", "mint",
)


def _is_size_choice_dish(dish) -> bool:
    """True for drink-style dishes whose variants are sizes (Large/Small) to pick,
    detected by the dish's menu category. Food (no/other category) is unaffected."""
    cat = (getattr(dish, "category", None) or "").lower()
    return any(h in cat for h in _DRINK_CATEGORY_HINTS)


def _variant_options_text(dish) -> str:
    """Human list of a dish's sizes, e.g. 'Large (AED 12) or Small (AED 8)'."""
    parts = [
        f"{v['name']} (AED {_aed(Decimal(str(v['price_aed'])))})"
        for v in (getattr(dish, "variants", None) or [])
    ]
    return " or ".join(parts)


async def _offer_size_choice(
    session: AsyncSession, conv, inbound: InboundMessage, restaurant_id: int,
    *, dish, qty: int, notes: str | None,
) -> None:
    """Ask which size for a drink-style dish (its variants are sizes). Defers the
    add until the customer answers — same shape as the serving-size bundle offer."""
    _set_state(conv, awaiting_size={
        "dish_id": dish.id, "qty": qty, "notes": notes, "retries": 0,
    })
    qty_part = f"your {qty} {dish.name}s" if qty > 1 else f"the {dish.name}"
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="size-offer",
        body=f"Sure! What size for {qty_part}: {_variant_options_text(dish)}? 😊",
    )


async def _handle_size_choice(
    session: AsyncSession, conv, inbound: InboundMessage, restaurant_id: int
) -> bool:
    """Apply the customer's size reply to a pending drink size offer. Re-asks once
    if the reply doesn't match a size, then defaults to the first size so the
    conversation never loops. Returns True if it handled the message."""
    pending = conv.state.get("awaiting_size")
    if not pending:
        return False
    from app.menu.models import Dish
    from app.ordering.service import add_item

    dish = await session.get(Dish, pending.get("dish_id"))
    if dish is None or not getattr(dish, "variants", None):
        _set_state(conv, awaiting_size=None)
        return False

    qty = int(pending.get("qty") or 1)
    notes = pending.get("notes")
    text = inbound.payload.get("text") if inbound.type == MessageType.TEXT else None
    variant = resolve_variant(dish, text) if text else None
    if variant is None:
        retries = int(pending.get("retries") or 0)
        if retries < 1:
            _set_state(conv, awaiting_size={**pending, "retries": retries + 1})
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="size-reask",
                body=f"Sorry, which size: {_variant_options_text(dish)}? 😊",
            )
            return True
        variant = dish.variants[0]  # give up asking → first size, never loop

    order = await _ensure_draft_order(session, conv, inbound, restaurant_id)
    await add_item(session, order=order, dish=dish, qty=qty, notes=notes, variant=variant)
    _set_state(conv, awaiting_size=None, dialogue_phase="ordering",
               dialogue_state="collecting_items")
    cart = await _build_cart_summary(session, conv)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="size-applied",
        body=f"Added {qty}x {dish.name} ({variant['name']}) ✅{_cart_tail(cart)}",
    )
    return True


async def _execute_ai_add_item(
    session: AsyncSession,
    conv,
    inbound: InboundMessage,
    restaurant_id: int,
    dish_query: str,
    qty: int,
    special_note: str = "",
    *,
    suppress_offers: bool = False,
) -> str:
    """Find and add a dish. Returns "added" or "no_match".

    Serving-size variants are OPT-IN bigger portions on top of the base single
    serve. The customer is never interrogated: ordering a dish plainly adds the
    single serve at the base price. A bigger portion is applied only when the
    customer NAMES it ("family biryani", "4 serve") — the matcher resolves it.

    ``suppress_offers`` skips the interactive size/bundle sub-dialogs and adds the
    base serve directly. It is used by the multi-dish path (several dishes named in
    one message), where pausing to ask a size/bundle question for one dish would
    abandon the remaining dishes — better to add them all and let the customer
    adjust than to silently drop them."""
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

    # Catalogue mode: a typed item not in the catalogue is not orderable → no match
    # (the caller reports "couldn't find", with no text-menu leak).
    if await _catalog_excludes_dish(session, restaurant_id, dish):
        return "no_match"

    # Pick a serving size: an explicitly-named one wins ("family biryani") and is
    # added straight away. Otherwise, if the ordered quantity matches a bundle
    # ("2" → the 2-serve size), ASK whether to use the bundle or keep the items
    # separate before adding. No variants / no match → base single serve.
    variant = None
    if getattr(dish, "variants", None):
        variant = resolve_variant(dish, dish_query)
        if variant is None and special_note:
            variant = resolve_variant(dish, special_note)
        if variant is None and not suppress_offers:
            # Drinks: variants are SIZES — ask which one (there's no default "single
            # serve" like food). Food: a quantity that matches a serving-size bundle
            # gets the combo offer instead.
            if _is_size_choice_dish(dish):
                await _offer_size_choice(
                    session, conv, inbound, restaurant_id,
                    dish=dish, qty=qty, notes=special_note or None,
                )
                return "awaiting_size"
            bundle = bundle_variant_for_qty(dish, qty)
            if bundle is not None:
                await _offer_bundle_choice(
                    session, conv, inbound, restaurant_id,
                    dish=dish, qty=qty, notes=special_note or None, bundle=bundle,
                )
                return "awaiting_bundle"

    await _add_dish_to_cart(
        session, conv, inbound, restaurant_id,
        dish=dish, qty=qty, notes=special_note or None, variant=variant,
    )
    return "added"


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
    # Catalogue mode: never name or act on a non-catalogue (text-menu) dish — drop
    # excluded candidates so a "not in cart" reply can't leak a text-menu item.
    cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
    if not cands:
        return ("no_match", None)
    dish = await _resolve_cart_dish(session, order_id=order.id, candidates=cands[:5])
    if dish is None:
        return ("not_in_cart", cands[0].name)
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
    session: AsyncSession, conv: Conversation, inbound: InboundMessage,
    restaurant_id: int, dish_query: str, qty: int, *, suppress_offers: bool = False,
) -> tuple[str, str | None]:
    """Set a cart dish to an exact quantity (``qty <= 0`` removes it).

    If the new quantity matches a serving-size bundle (e.g. 2 → a "2 serve" size),
    ASK whether to use the bundle or keep the items separate (outcome
    "awaiting_bundle"); otherwise set it to single×qty. Returns
    ``(outcome, dish_name)`` where outcome is "updated", "removed", "awaiting_bundle",
    "not_in_cart", or "no_match".

    ``suppress_offers`` skips the bundle question and sets the quantity directly —
    used by the multi-dish path (several quantities changed in one message), where
    pausing to ask about one dish's bundle would abandon the rest."""
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
    # Catalogue mode: never name or offer a non-catalogue (text-menu) dish — drop
    # excluded candidates so "isn't in your cart yet, want me to add?" can't leak one.
    cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
    if not cands:
        return ("no_match", None)
    dish = await _resolve_cart_dish(session, order_id=order.id, candidates=cands[:5])
    if dish is None:
        return ("not_in_cart", cands[0].name)
    if qty <= 0:
        await set_item_qty(session, order=order, dish_id=dish.id, qty=0)
        return ("removed", dish.name)

    # If the new quantity matches a bundle, ask before pricing it differently.
    bundle = bundle_variant_for_qty(dish, qty)
    if bundle is not None and not suppress_offers:
        await _offer_bundle_choice(
            session, conv, inbound, restaurant_id,
            dish=dish, qty=qty, notes=None, bundle=bundle,
        )
        return ("awaiting_bundle", dish.name)

    await set_item_qty(session, order=order, dish_id=dish.id, qty=qty)
    return ("updated", dish.name)


async def _apply_confirmation_edit(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage,
    restaurant_id: int, restaurant, action: str, data: dict,
) -> None:
    """Apply an add/remove/quantity change to the order being confirmed, then re-show
    the deterministic summary.

    At the confirm step a dish edit used to be dropped by the phase guard (add/remove/
    update aren't "confirmation" actions) — the customer's "add a special biryani also"
    silently did nothing. Here we edit the still-draft pending order in place and
    re-render the summary, so confirm-time edits just work without the modify sub-flow."""
    from app.ordering.models import Order

    oid = conv.state.get("pending_order_id") or conv.state.get("draft_order_id")
    order = await session.get(Order, oid) if oid else None
    if order is None or str(order.status) != "draft":
        # No editable order — re-show whatever summary we can rather than dropping it.
        if order is not None:
            await _send_order_summary(session, conv, inbound, restaurant_id, order)
        return

    # draft_order_id must name the order being confirmed so the edit helpers (which
    # read draft_order_id) target it; at confirm time it normally already does.
    if conv.state.get("draft_order_id") != order.id:
        _set_state(conv, draft_order_id=order.id)

    note: str | None = None
    if action == "add_item":
        items = data.get("items") or []
        if not items and data.get("dish_query"):
            items = [{"dish_query": data.get("dish_query", ""),
                      "qty": data.get("qty"), "special_note": data.get("special_note", "")}]
        not_found = []
        for it in items:
            dq = it.get("dish_query", "")
            if not dq:
                continue
            iqty = int(it.get("qty") or 1)
            if iqty > _max_item_qty(restaurant):
                continue
            status = await _execute_ai_add_item(
                session, conv, inbound, restaurant_id, dq, iqty,
                it.get("special_note", ""), suppress_offers=True,
            )
            if status == "no_match":
                not_found.append(dq)
        if not_found:
            # Warm, honest, grounded: name only what the customer asked for (never an
            # invented dish), say we don't have it, and point them back to the real menu.
            names = ", ".join(not_found)
            note = (
                f"Sorry, we don't have {names} on our menu 🙏 "
                "Want to add something else, or say 'menu' to see what we have? 😊"
            )
    elif action == "remove_item":
        raw_qty = data.get("qty")
        await _execute_ai_remove_item(
            session, conv, restaurant_id, data.get("dish_query", ""),
            int(raw_qty) if raw_qty is not None else None,
        )
    elif action == "update_qty":
        outcome, _name = await _execute_ai_update_qty(
            session, conv, inbound, restaurant_id,
            data.get("dish_query", ""), int(data.get("qty") or 1),
        )
        if outcome == "awaiting_bundle":
            # A bundle question was sent; the answer re-enters the cart flow.
            return

    # Stay at the confirm step and re-show the now-updated, DB-backed summary.
    _set_state(conv, dialogue_phase="awaiting_confirmation", dialogue_state="order_confirmation")
    if note:
        await _send_text(session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                         prefix="confirm-edit-note", body=note)
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


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
    await _send_order_summary(
        session, conv, inbound, restaurant_id, order, allow_new_address=True
    )


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
    # SAFETY GATE: never confirm an order with no items — that places an empty order
    # the kitchen can't fulfil. Send the customer back to adding items instead.
    if not await _order_has_items(session, order.id):
        _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="confirm-empty",
            body="Your cart is empty, so there's nothing to confirm. Please add a dish to order 😊",
        )
        return
    await finalize_confirmation(session, order=order, actor="customer")
    # Drop the cart pointers now the order is placed — a later order must start a
    # fresh draft, not reuse this (now confirmed) order's id.
    _set_state(conv, dialogue_phase="post_order", dialogue_state="order_placed",
               draft_order_id=None, pending_order_id=None)
    from app.ordering.payments import cod_due_aed

    due = cod_due_aed(order)
    if order.wallet_applied_aed and order.wallet_applied_aed > 0:
        payment_line = (
            f"Total: AED {_aed(order.total)}\n"
            f"Wallet credit applied: AED {_aed(order.wallet_applied_aed)}\n"
            f"Pay on delivery: AED {_aed(due)} (COD)\n"
        )
    else:
        payment_line = f"Total: AED {_aed(order.total)} (COD, cash on delivery)\n"
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-confirmed",
        body=(
            f"Order confirmed! 🎉 Order #{order.order_number}\n"
            f"{payment_line}"
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
        body="No problem, your order has been cancelled. Send 'hi' whenever you're ready to order again 😊",
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
    """Big-order guard. An unusually large single line (e.g. "100000 lemon mints") is
    NEVER auto-added. The bot STAYS ACTIVE (no manual-takeover mute, so the customer is
    never left in silence) and simply asks for a realistic quantity, pointing genuine
    bulk orders to the phone. Previously this muted the chat, which trapped customers
    (and testing) in dead air until a manager flipped it back in the dashboard."""
    from app.identity.models import Restaurant

    item = (dish_query or "").strip() or "that"
    rest = await session.get(Restaurant, restaurant_id)
    phone = (rest.phone if rest else "") or ""
    call_line = (
        f" For a genuine bulk order, please call us on {phone} and the team will set it up."
        if phone else
        " For a genuine bulk order, let us know and the team will set it up."
    )
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="qty-anomaly",
        body=(
            f"That's a big order ({qty}x {item})! 😊 I can't add that many automatically. "
            f"How many would you actually like?{call_line}"
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

    # Confirm-step edits: "add a special biryani also" / "make it 2" / "remove the
    # mint" must EDIT the order being confirmed and re-show the summary — not be
    # dropped by the phase guard (these aren't confirmation actions) nor narrated
    # without applying. Handle them before the guard runs.
    if phase == "awaiting_confirmation" and action in ("add_item", "remove_item", "update_qty"):
        await _apply_confirmation_edit(
            session, conv, inbound, restaurant_id, restaurant, action, data
        )
        return

    # Phase guard — wrong-phase action falls back to no_action
    if not _is_valid_action_for_phase(action, phase):
        action = "no_action"

    # Anti-hallucination safety net: if the AI dumped a (fabricated) menu into its
    # reply, swap in the REAL menu before it goes out. Runs in EVERY phase — the model
    # can be asked "show me the menu" mid-confirmation, where it would otherwise echo a
    # menu from history (in catalogue mode that history may hold the old text menu).
    # _render_menu is catalogue-bounded when catalogue mode is on, so this can never
    # leak a text-menu item.
    if _looks_like_menu(reply):
        reply = await _render_menu(session, restaurant_id)

    # ── ordering actions ──────────────────────────────────────────────────
    if action == "show_menu":
        # Catalogue first (when enabled), else the REAL text menu from the DB — never
        # let the LLM reproduce it (it hallucinated entire fake menus). Ignore message.
        await _send_menu_or_catalog(
            session, conv, inbound, restaurant_id, prefix="show-menu",
        )
        return

    if action == "add_item":
        items = data.get("items") or []
        # Multi-dish message: add EVERY dish the customer named in one message. A
        # single add_item used to add one dish and silently drop the rest, while the
        # LLM's reply narrated a full cart that the DB never held. We add each dish
        # (suppressing per-dish size/bundle prompts so the loop never abandons the
        # remaining dishes) and then echo the REAL cart from the DB — so the reply
        # can never again claim items that were not actually saved.
        if len(items) >= 2:
            added: list[str] = []
            not_found: list[str] = []
            too_many: list[str] = []
            for it in items:
                iq = it.get("dish_query", "")
                if not iq:
                    continue
                iqty = int(it.get("qty") or 1)
                if iqty > _max_item_qty(restaurant):
                    too_many.append(iq)
                    continue
                status = await _execute_ai_add_item(
                    session, conv, inbound, restaurant_id, iq, iqty,
                    it.get("special_note", ""), suppress_offers=True,
                )
                if status == "added":
                    added.append(iq)
                elif status == "no_match":
                    not_found.append(iq)
            cart = await _build_cart_summary(session, conv)
            if added:
                # The cart tail already lists every item, so the lead is just a short
                # confirmation. Strip any 🛒 cart line the model added (else the cart
                # shows twice), and drop a reply that is empty or got swapped to the
                # full menu by the anti-hallucination guard above (never re-dump it).
                lead = "\n".join(
                    ln for ln in reply.splitlines() if not ln.strip().startswith("🛒")
                ).strip()
                if not lead or _looks_like_menu(lead):
                    lead = "Got it! 😊"
                body = f"{lead}{_cart_tail(cart)}"
            else:
                body = ("Sorry, none of those are on our menu 🙏 "
                        "Say 'menu' to see what we have, or tell me another dish 😊")
            notes = []
            if not_found:
                notes.append("we don't have " + ", ".join(not_found) + " on our menu")
            if too_many:
                notes.append(
                    "that's a large quantity for " + ", ".join(too_many)
                    + ", please call us to arrange a big order"
                )
            if notes:
                body = f"{body}\n\n({'; '.join(notes)})"
            await _send_text(session, conv=conv, inbound=inbound,
                             restaurant_id=restaurant_id, prefix="ai-add-multi", body=body)
            return

        # Single dish — named via the items list (length 1) or the flat dish_query.
        if len(items) == 1 and not data.get("dish_query"):
            dish_query = items[0].get("dish_query", "")
            qty = int(items[0].get("qty") or 1)
            special_note = items[0].get("special_note", "")
        else:
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
                    body=f"Sorry, we don't have {dish_query} on our menu 🙏 "
                         "Want to try another dish, or say 'menu' to see everything we have? 😊",
                )
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
            body = f"Done! Removed {dish_name} ✅{_cart_tail(cart)}"
        elif outcome == "reduced":
            body = f"Done! Removed {rm_qty}x {dish_name} ✅{_cart_tail(cart)}"
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
        items = data.get("items") or []
        # Multi-dish quantity change in one message ("make it 2 chicken and 2 lemon
        # mint"): set EVERY named dish (suppressing the per-dish bundle prompt so the
        # loop never abandons the rest), then echo the real cart. A single update_qty
        # used to apply to one dish and silently drop the other quantities.
        if len(items) >= 2:
            updated: list[str] = []
            not_found: list[str] = []
            too_many: list[str] = []
            for it in items:
                iq = it.get("dish_query", "")
                if not iq:
                    continue
                iqty = int(it.get("qty") or 1)
                if iqty > _max_item_qty(restaurant):
                    too_many.append(iq)
                    continue
                outcome, dish_name = await _execute_ai_update_qty(
                    session, conv, inbound, restaurant_id, iq, iqty, suppress_offers=True
                )
                if outcome in ("updated", "removed"):
                    updated.append(dish_name or iq)
                elif outcome in ("no_match", "not_in_cart"):
                    not_found.append(iq)
            cart = await _build_cart_summary(session, conv)
            body = (f"Updated! ✅{_cart_tail(cart)}" if updated
                    else "I couldn't change those — tell me the dish and quantity 😊")
            notes = []
            if not_found:
                notes.append("not in your cart: " + ", ".join(not_found))
            if too_many:
                notes.append("that's a large quantity for " + ", ".join(too_many))
            if notes:
                body = f"{body}\n\n({'; '.join(notes)})"
            await _send_text(session, conv=conv, inbound=inbound,
                             restaurant_id=restaurant_id, prefix="ai-qty-multi", body=body)
            return

        dish_query = data.get("dish_query", "") or (items[0].get("dish_query", "") if items else "")
        qty = int((data.get("qty") if data.get("qty") is not None else (items[0].get("qty") if items else None)) or 1)
        if dish_query and qty > _max_item_qty(restaurant):
            await _escalate_large_qty(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                qty=qty, dish_query=dish_query,
            )
            return
        outcome, dish_name = await _execute_ai_update_qty(
            session, conv, inbound, restaurant_id, dish_query, qty
        )
        if outcome == "awaiting_bundle":
            # The bundle question was already sent; wait for the yes/no reply.
            return
        cart = await _build_cart_summary(session, conv)
        if outcome == "updated":
            body = f"Updated! {qty}x {dish_name} ✅{_cart_tail(cart)}"
        elif outcome == "removed":
            body = f"Done! Removed {dish_name} ✅{_cart_tail(cart)}"
        elif outcome == "not_in_cart":
            body = f"{dish_name} isn't in your cart yet. Want me to add {qty}? 😊"
        else:  # no_match
            body = reply or (
                f"I couldn't find '{dish_query}' in your cart to change. "
                "Which dish should I update?"
            )
        await _send_text(session, conv=conv, inbound=inbound,
                         restaurant_id=restaurant_id, prefix="ai-qty", body=body)
        return

    if action == "clear_cart":
        # Empty the WHOLE draft cart (not a single remove) so the customer can start
        # over. Keeps the same draft order, just drops every line + zeroes the totals.
        from sqlalchemy import delete as sa_delete

        from app.ordering.models import Order, OrderItem

        draft_order_id = conv.state.get("draft_order_id")
        order = await session.get(Order, draft_order_id) if draft_order_id else None
        if order is not None and str(order.status) == "draft":
            await session.execute(sa_delete(OrderItem).where(OrderItem.order_id == order.id))
            order.subtotal = Decimal("0.00")
            order.total = order.delivery_fee_aed
            await session.flush()
            _set_state(conv, dialogue_state="collecting_items", abandoned_nudged=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-clear-cart",
            body="Cleared your cart 🧹 What would you like to order?",
        )
        return

    if action == "proceed_to_address":
        cart = await _build_cart_summary(session, conv)
        if not cart:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ai-empty-cart",
                body="Your cart is empty. Please add at least one dish first! 😊",
            )
            return
        _set_state(conv, dialogue_phase="address_capture", dialogue_state="address_capture")
        # ALWAYS check for a saved address BEFORE asking for a location pin: a returning
        # customer auto-attaches their saved address and jumps straight to the order
        # summary (which shows the address) with a "Use new address" button — a repeat
        # order is one tap, never a re-shared pin. We gate ONLY on whether the customer
        # explicitly chose a NEW address for THIS order (saved_address_declined), NOT on
        # the broader address_offer_made flag, which can go stale across orders (e.g. a
        # catalogue basket) and would wrongly skip the check. New customers / declined /
        # no saved address fall through to the location-pin ask below.
        if not conv.state.get("saved_address_declined"):
            saved_id = await _resolve_saved_address_id(
                session, restaurant_id, inbound.from_phone
            )
            if saved_id:
                _set_state(conv, address_offer_made=True, saved_address_id=saved_id)
                await _attach_saved_address_to_order(
                    session, conv, inbound, restaurant_id, saved_id, restaurant
                )
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
            body="Great! Please share your delivery location 📍. Tap the button below "
                 "to send your pin so the rider reaches you exactly.",
        )
        return

    # ── address_capture actions ───────────────────────────────────────────
    if action == "send_location_request":
        _set_state(conv, dialogue_phase="address_capture", dialogue_state="address_capture")
        await _send_location_request(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="loc-request",
            body=reply or "Please share your delivery location 📍. Tap the button below to send your pin.",
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
                body="Almost there! Please share your delivery location 📍 first. "
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
    if phase == "awaiting_confirmation":
        # The order is fixed unless the customer explicitly modifies/cancels — but an
        # honest question at the confirm step ("where are you?", "why is the fee AED 5?")
        # deserves a real answer, not a silent summary re-loop. So: send the AI's
        # informational reply FIRST, then ALWAYS re-show the DETERMINISTIC DB summary as
        # the final word.
        #
        # This preserves the anti-hallucination guarantee: the model used to narrate
        # changes it never applied ("updated to 2x, total 97") while the DB stayed put,
        # so the customer confirmed a DIFFERENT order than the reply implied. Because the
        # true, DB-backed summary (with the Confirm button) is always the LAST message
        # the customer sees, they can only ever confirm what is really in the order — the
        # reply can inform, but it can never be the thing they act on.
        from app.ordering.models import Order
        oid = conv.state.get("pending_order_id") or conv.state.get("draft_order_id")
        order = await session.get(Order, oid) if oid else None
        if reply:
            await _send_text(session, conv=conv, inbound=inbound,
                             restaurant_id=restaurant_id, prefix="ai-reply", body=reply)
        if order is not None:
            await _send_order_summary(session, conv, inbound, restaurant_id, order)
        return

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
            f"Got it! We deliver to your area 🚚 {fee_line}\n\n"
            "To finish, reply with your *apartment/room*, *building*, and "
            "*receiver name*, e.g. _101, Tower A, Ahmed_"
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

    # Dish-info question ("what's special in the biryani?") → answer with the dish's
    # menu description (verbatim) when present, else a short human line. Deterministic
    # so the manager's wording shows exactly. Only fires when it resolves to a real
    # dish and isn't a menu request — otherwise it falls through to the AI (no break).
    if (
        phase == "ordering"
        and inbound.type == MessageType.TEXT
        and not _is_menu_request(inbound.payload.get("text") or "")
    ):
        _info_name = _dish_info_question(inbound.payload.get("text"))
        if _info_name:
            _info_reply = await _answer_dish_info(session, restaurant_id, _info_name)
            if _info_reply:
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="dish-info", body=_info_reply,
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


async def _transcribe_voice_note(inbound: InboundMessage) -> str | None:
    """Download a WhatsApp voice note and transcribe it to text. Returns the
    transcript, or None on any failure (missing id, download/transcription error,
    empty result). STT is best-effort — it never raises into the dialogue flow."""
    media_id = inbound.payload.get("audio_id")
    if not media_id:
        return None
    try:
        from app.speech.factory import get_transcriber
        from app.whatsapp.factory import get_whatsapp_provider

        provider = get_whatsapp_provider()
        audio, mime = await provider.download_media(media_id)
        transcript = await get_transcriber().transcribe(audio, mime=mime)
        return (transcript or "").strip() or None
    except Exception:
        _logger.exception("voice transcription failed (%s)", inbound.wa_message_id)
        return None


async def _try_catalog_typed_order(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage,
    restaurant_id: int, restaurant,
) -> bool:
    """In CATALOGUE mode, deterministically ADD a clearly-typed single dish BEFORE the
    AI runs, so a plain "one chicken biryani" is reliably added to the cart instead of
    being misclassified by the model as a menu request (which re-sends the catalogue
    cards with no text reply). Returns True if it handled (added) the message, False to
    fall through to the AI for anything that isn't an unambiguous single catalogue dish:
    questions, "done", menu requests, ambiguous/unknown items, multi-item messages.

    Scoped to catalogue mode only, so text-mode ordering (with its size/bundle offers and
    multi-item parsing in the AI path) is completely unchanged."""
    from app.ordering.models import Order
    from app.ordering.service import (
        add_item, create_draft_order, get_or_create_customer, parse_qty_and_text,
    )

    if inbound.type != MessageType.TEXT or _resolve_phase(conv) != "ordering":
        return False
    if not await _catalog_mode_on(session, restaurant_id):
        return False
    text = (inbound.payload.get("text") or "").strip()
    if not text or "?" in text or _is_menu_request(text.lower()):
        return False  # questions / menu requests → AI

    # Strip leading politeness/filler so "ok add one mutton biryani", "please give me 2
    # biryani", "i want chicken" parse down to the real dish + quantity.
    fillers = (
        "i would like", "i'd like", "id like", "i'll have", "ill have", "can i get",
        "could i get", "let me get", "i want", "i need", "give me", "get me", "gimme",
        "please", "kindly", "okay", "okey", "ok", "pls", "add", "want",
    )
    body = text
    changed = True
    while changed:
        changed = False
        low0 = body.lower()
        for f in fillers:
            if low0.startswith(f + " "):
                body = body[len(f) + 1:].strip()
                changed = True
                break
    if not body:
        return False

    qty, dish_query = parse_qty_and_text(body)
    dq = dish_query.strip().lower()
    # Control words and obvious non-orders → AI (never intercept "done", greetings, etc.).
    if (not dq or dq in {
            "done", "checkout", "that's all", "thats all", "no", "yes", "nope", "yep",
            "ok", "okey", "okay", "cancel", "menu", "hi", "hello", "hlo", "bas", "nothing"}
            or dq.split()[0] in {
                "what", "how", "where", "why", "who", "when", "do", "does", "can",
                "could", "is", "are", "tell", "show"}):
        return False

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence != MatchConfidence.DIRECT or not result.candidates:
        return False  # ambiguous / no match → AI (gives the warm reply or disambiguates)
    dish = result.candidates[0]
    if await _catalog_excludes_dish(session, restaurant_id, dish):
        # Typed an item that isn't in the catalogue → answer honestly and
        # deterministically here (never let it fall to the AI, which sometimes
        # re-sends the whole catalogue instead of saying we don't have it).
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="catalog-typed-unavailable",
            body=(f"Sorry, we don't have {dish.name} on our menu 🙏 "
                  "Tap the catalogue to see what's available, or tell me another dish 😊"),
        )
        return True

    add_qty = qty or 1
    if add_qty > _max_item_qty(restaurant):
        await _escalate_large_qty(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            qty=add_qty, dish_query=dish.name,
        )
        return True

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone
    )
    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is not None and str(order.status) != "draft":
        order = None
    if order is None:
        order = await create_draft_order(
            session, restaurant_id=restaurant_id, customer_id=customer.id
        )
        _set_state(
            conv, draft_order_id=order.id, address_offer_made=None,
            saved_address_declined=None, saved_address_id=None,
            pin_lat=None, pin_lon=None, distance_km=None, delivery_fee=None,
        )
    await add_item(session, order=order, dish=dish, qty=add_qty)
    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
    cart = await _build_cart_summary(session, conv)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="catalog-typed-add",
        body=f"Added {add_qty}x {dish.name} ✅{_cart_tail(cart)}",
    )
    return True


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

    # Voice note → transcribe BEFORE recording, so the audit row AND the AI history
    # built from recorded messages both carry the transcript (history renders a
    # non-text message as "[audio]" otherwise — the AI would "hear" the literal
    # word "audio"). The row stays type "audio" for audit; downstream the in-memory
    # inbound is swapped to TEXT so every handler runs unchanged.
    _voice_transcript = (
        await _transcribe_voice_note(inbound)
        if inbound.type == MessageType.AUDIO
        else None
    )

    await record_message(
        session,
        conversation_id=conv.id,
        direction="inbound",
        wa_message_id=inbound.wa_message_id,
        msg_type=str(inbound.type),
        payload=(
            {**inbound.payload, "text": _voice_transcript}
            if _voice_transcript
            else inbound.payload
        ),
        ts=inbound.timestamp,
    )

    if inbound.type == MessageType.AUDIO:
        if not _voice_transcript:
            await enqueue_message(
                session,
                restaurant_id=restaurant_id,
                to_phone=inbound.from_phone,
                msg_type=OutboundMessageType.TEXT,
                payload={"body": "Sorry, I couldn't catch that 🎙️. Could you type it, "
                                 "or send another voice note?"},
                idempotency_key=f"stt-fail-{inbound.wa_message_id}",
            )
            return
        inbound.type = MessageType.TEXT
        inbound.payload = {"text": _voice_transcript}

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

    # "Don't call me" — capture as a persistent contact preference on the customer so
    # every rider stop shows a "do not call, message only" flag. Saying calling is OK
    # again clears it. Non-intercepting: we update the flag and let the message
    # continue through the normal flow (it may also carry an order, e.g. "one biryani,
    # please don't call"). "Don't call" wins if a message somehow says both.
    if inbound.type == MessageType.TEXT:
        _dnc_text = inbound.payload.get("text")
        _set_dnc = _mentions_do_not_call(_dnc_text)
        _clear_dnc = not _set_dnc and _mentions_can_call(_dnc_text)
        if _set_dnc or _clear_dnc:
            from app.ordering.service import get_or_create_customer
            _cust = await get_or_create_customer(
                session, restaurant_id=restaurant_id, phone=inbound.from_phone
            )
            _current = bool((_cust.tags or {}).get("do_not_call"))
            if _set_dnc and not _current:
                _cust.tags = {**(_cust.tags or {}), "do_not_call": True}
                _logger.info("customer %s set do_not_call preference", _cust.id)
            elif _clear_dnc and _current:
                _cust.tags = {**(_cust.tags or {}), "do_not_call": False}
                _logger.info("customer %s cleared do_not_call preference", _cust.id)

    # A pure greeting ("hi", "As salam walekum", "hello") means START FRESH — in
    # ANY state, not just on first contact. Drop any stale/abandoned draft so an
    # old, never-purchased cart can never silently carry into the new order. This
    # matches the "Send 'hi' to start a new order" copy used throughout. A message
    # that mixes a greeting with an order ("hi, one biryani") is NOT a pure
    # greeting and falls through to the ordering flow so the dish still lands.
    if inbound.type == MessageType.TEXT and _is_pure_greeting(inbound.payload.get("text")):
        # A returning customer with a non-empty, not-yet-expired draft is ASKED whether
        # to continue or start fresh (instead of silently wiping the cart). An expired
        # or empty cart just starts fresh.
        from app.ordering.models import Order as _Order

        _draft_id = conv.state.get("draft_order_id")
        _draft = await session.get(_Order, _draft_id) if _draft_id else None
        if (
            _draft is not None
            and str(_draft.status) == "draft"
            and await _order_has_items(session, _draft.id)
            and not _cart_expired(_draft, restaurant)
        ):
            await _offer_resume_cart(session, conv, inbound, restaurant_id)
            return
        if _draft_id is not None:
            _logger.info("greeting reset abandoned draft for conv=%s", conv.id)
        _set_state(conv, dialogue_state="greeting", dialogue_phase="ordering",
                   draft_order_id=None, pending_order_id=None, awaiting_bundle=None,
                   awaiting_size=None)
        await _handle_greeting(session, conv, inbound, restaurant_id)
        return

    # A pending bundle offer ("2 serve for AED 30 — add it?") takes the next reply
    # (yes/no) before the AI runs, so the answer applies the bundle or keeps the
    # items separate instead of being re-interpreted as a new order.
    if conv.state.get("awaiting_bundle"):
        if await _handle_bundle_choice(session, conv, inbound, restaurant_id):
            return

    # A pending drink size offer ("Large or Small?") takes the next reply before the
    # AI runs, so the size answer is applied instead of read as a new order.
    if conv.state.get("awaiting_size"):
        if await _handle_size_choice(session, conv, inbound, restaurant_id):
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
        if btn_id.startswith("resale_accept:"):
            arg = btn_id.split(":", 1)[1]
            if arg.isdigit():
                await _handle_resale_accept(session, conv, inbound, restaurant_id, int(arg))
            return
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
            _set_state(conv, address_offer_made=True, saved_address_declined=True,
                       dialogue_phase="address_capture", dialogue_state="address_capture")
            await _send_location_request(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ask-new-address",
                body="Please share your delivery location 📍. Tap the button below to send your pin.",
            )
            return
        if btn_id == "use_new_address":
            # "Use new address" on the order summary → drop the auto-attached saved
            # address and capture a fresh one. The cart (draft order) is preserved;
            # only the delivery location changes, so we re-request the location pin.
            _set_state(conv, address_offer_made=True, saved_address_declined=True,
                       saved_address_id=None, pending_address_id=None,
                       dialogue_phase="address_capture", dialogue_state="address_capture")
            await _send_location_request(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="use-new-address",
                body="No problem! Please share your new delivery location 📍. "
                     "Tap the button below to send your pin.",
            )
            return
        if btn_id == "resume_cart":
            # Continue the in-progress cart from the resume prompt.
            cart = await _build_cart_summary(session, conv)
            _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="resume-continue",
                body=(
                    "Great, picking up where you left off 😊"
                    f"{_cart_tail(cart)}\n\nAdd more items, or say 'done' to check out."
                ),
            )
            return
        if btn_id == "new_cart":
            # Start fresh from the resume prompt: empty the old cart (so it can't be
            # resurrected) and drop the pointer, then greet.
            from sqlalchemy import delete as sa_delete

            from app.ordering.models import OrderItem as _OrderItem

            _did = conv.state.get("draft_order_id")
            if _did:
                await session.execute(sa_delete(_OrderItem).where(_OrderItem.order_id == _did))
            _set_state(conv, dialogue_state="greeting", dialogue_phase="ordering",
                       draft_order_id=None, pending_order_id=None, awaiting_bundle=None,
                       awaiting_size=None, abandoned_nudged=None)
            await _handle_greeting(session, conv, inbound, restaurant_id)
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
            # Catalogue first (when enabled), text menu otherwise.
            await _send_menu_or_catalog(
                session, conv, inbound, restaurant_id, prefix="menu-request",
            )
            return
        # "What's in my cart / show my order" → show the REAL cart deterministically,
        # in ANY mode, so the model can never mishandle it (e.g. re-send the catalogue).
        if _is_cart_query(text):
            cart = await _build_cart_summary(session, conv)
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="cart-query",
                body=(f"🛒 Here's your cart:\n\n{cart}\n\nReply with more items, "
                      "or send 'done' to check out 😊")
                if cart else
                "Your cart is empty right now 🛒 Tell me what you'd like to add 😊",
            )
            return
        # "Where is my order / can I see the live location" → answer with the
        # current status + ETA + the live tracking link, deterministically.
        if _is_tracking_query(text):
            await _handle_status_query(session, conv, inbound, restaurant_id)
            return
        # Post-delivery complaint → open a HUMAN ticket (AI never compensates).
        # Only in post_order so it never hijacks ordering / status. Checked after
        # the tracking query so "where is my order" stays a status reply.
        if _resolve_phase(conv) == "post_order" and _is_complaint(text):
            await _handle_complaint(session, conv, inbound, restaurant_id, restaurant)
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
        # "What tier am I / how do I reach Gold" → deterministic answer from loyalty
        # settings (falls through to AI if loyalty is disabled).
        if _is_tier_query(text):
            await _handle_tier_query(session, conv, inbound, restaurant_id, restaurant)
            return
        # Accept a pending resale offer by text ("grab", "yes", "i want it").
        pending_resale = conv.state.get("resale_offer_id")
        if pending_resale and _is_resale_accept(text):
            await _handle_resale_accept(session, conv, inbound, restaurant_id, int(pending_resale))
            return
        # Coupon code typed at the order-summary step → apply it. We only treat the
        # message as a coupon when it EXACTLY matches a code issued to this customer,
        # so normal chat is never misread as a coupon.
        if _resolve_phase(conv) == "awaiting_confirmation":
            from app.ordering.models import Customer

            customer = await session.scalar(
                select(Customer).where(
                    Customer.restaurant_id == restaurant_id,
                    Customer.phone == inbound.from_phone,
                )
            )
            if customer is not None:
                _, active_coupons = await _redeem_context(
                    session, restaurant_id=restaurant_id, customer_id=customer.id
                )
                typed = text.strip().upper()
                match = next((c for c in active_coupons if c.code.upper() == typed), None)
                if match is not None:
                    await _redeem_coupon_at_checkout(
                        session, conv, inbound, restaurant_id, match.code
                    )
                    return
                # "claim my coupon" by intent: apply the only one, or ask which.
                if _is_claim_coupon(text):
                    if not active_coupons:
                        await _send_text(
                            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                            prefix="coupon-none",
                            body="You don't have any coupons to claim right now 😊",
                        )
                    elif len(active_coupons) == 1:
                        await _redeem_coupon_at_checkout(
                            session, conv, inbound, restaurant_id, active_coupons[0].code
                        )
                    else:
                        codes = ", ".join(c.code for c in active_coupons)
                        await _send_text(
                            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                            prefix="coupon-pick",
                            body=f"You have a few coupons: {codes}. Send the code you'd like to use.",
                        )
                    return

    # Catalogue mode: a clearly-typed single dish is ADDED deterministically here, so a
    # plain "one chicken biryani" reliably goes to the cart instead of the model
    # sometimes re-sending the catalogue cards. Anything else falls through to the AI.
    if await _try_catalog_typed_order(session, conv, inbound, restaurant_id, restaurant):
        return

    # All remaining text + button_reply → AI
    await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
