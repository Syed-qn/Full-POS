import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.conversation.models import Conversation
from app.conversation.service import get_or_create_conversation, record_message
from app.llm.action_schema import LEGACY_PHASE_ACTIONS
from app.ordering.matching import (
    MatchConfidence,
    bundle_variant_for_qty,
    find_dish_matches,
    normalize_name,
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


def _note_suffix(it) -> str:
    """Render an order item's special note (e.g. 'double masala', 'no onion') so two
    lines of the SAME dish with DIFFERENT prep are distinguishable in the cart/summary.
    Without this they look like an accidental duplicate ('2x Chicken Biryani' twice)."""
    note = (getattr(it, "notes", None) or "").strip()
    return f" — {note}" if note else ""


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


async def _canonical_dish_names(
    session: AsyncSession, restaurant_id: int
) -> frozenset[str]:
    """Return the normalised canonical dish names for the tenant.

    In catalogue mode: names of active CatalogProduct rows (what the customer can
    actually order). In text mode: names of active, available Dish rows.

    Used by the anti-hallucination cross-check to distinguish real dishes from
    LLM-fabricated names (R-026, F96, F98).
    """
    from app.identity.models import Restaurant, catalog_mode_enabled
    from app.menu.models import Dish, Menu

    rest = await session.get(Restaurant, restaurant_id)
    if rest is not None and catalog_mode_enabled(rest.settings):
        # Tenant dishes are the orderable surface; shared-catalog mirrors may be polluted.
        menu = await session.scalar(
            select(Menu).where(
                Menu.restaurant_id == restaurant_id,
                Menu.status == "active",
            )
        )
        if menu is None:
            return frozenset()
        rows = await session.scalars(
            select(Dish.name).where(
                Dish.menu_id == menu.id,
                Dish.is_available.is_(True),
                Dish.meta_status == "active",
                Dish.whatsapp_enabled.is_(True),
            )
        )
        return frozenset(n.strip().lower() for n in rows if n)

    # Text mode — active dishes on the active menu
    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if menu is None:
        return frozenset()
    rows = await session.scalars(
        select(Dish.name).where(
            Dish.menu_id == menu.id,
            Dish.is_available.is_(True),
            Dish.meta_status == "active",
        )
    )
    return frozenset(n.strip().lower() for n in rows if n)


# A dish 'name' that is actually an internal/dev slug (e.g. 'chicken_biryani') rather
# than a real customer-facing title (F74/F97). Dish.name has no dedicated slug column
# (see model), so this pattern match is the only signal: all-lowercase, snake_case-ish.
_SLUG_NAME = _re.compile(r"^[a-z][a-z0-9_]*$")

# Regex: a word sequence likely to be a dish name — a run of 2-4 consecutive
# title-case words. Deliberately does NOT span "and"/"&"/"," — a list like "Lamb
# Ouzi and Seafood Platter" must yield TWO candidates ("Lamb Ouzi", "Seafood
# Platter"), not one glued-together non-match, so each fabricated name is counted.
_DISH_NAME_CANDIDATE = _re.compile(
    r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3})\b"
)
# Splits a reply into dish-name-candidate segments at conjunctions/commas so the
# title-case run regex above never crosses "and"/"&" into the next dish name.
_CONJUNCTION_SPLIT = _re.compile(r"\s*(?:,|&|\band\b)\s*", _re.IGNORECASE)


async def _looks_like_hallucinated_menu(
    session: AsyncSession,
    reply: str,
    restaurant_id: int,
) -> bool:
    """True if the LLM reply appears to list dishes NOT in the tenant's catalogue.

    Extends the shape-only `_looks_like_menu` with a dish-name cross-check:
    extract title-case word-runs from the reply, count how many are NOT in the
    canonical dish set.  ≥2 such unknown names → hallucinated menu.

    This catches hallucinations that omit prices (which `_looks_like_menu` misses).
    Safe: single-dish answers or polite "we have X" replies with one matching name
    are never flagged (R-026, F96, F98, TX-27).
    """
    if not reply:
        return False
    # Fast path: price-shape check already catches the common case
    if _looks_like_menu(reply):
        return True

    canonical = await _canonical_dish_names(session, restaurant_id)
    if not canonical:
        # No catalogue data yet — skip cross-check to avoid false positives
        return False

    candidates: list[str] = []
    for segment in _CONJUNCTION_SPLIT.split(reply):
        candidates.extend(_DISH_NAME_CANDIDATE.findall(segment))
    unknown = sum(1 for c in candidates if c.strip().lower() not in canonical)
    return unknown >= 2


def _strip_money_claims(text: str) -> str:
    """Remove lines that contain an AED amount from LLM free text on mutating turns.

    Safety net (R-067): the LLM sometimes authors a price/total in its lead ("Added,
    that's AED 50"). Money facts must come solely from the DB-rendered cart tail, so
    any LLM-authored currency line is dropped before the lead is used.
    """
    if not text:
        return text
    clean = [ln for ln in text.splitlines() if not _PRICE_TOKEN.search(ln)]
    return "\n".join(clean).strip()


# Explicit "show me the menu" keywords — MULTILINGUAL (this is a multi-language SaaS:
# English, Hindi/Urdu roman + Devanagari, Arabic, Telugu). The word "menu" itself is
# widely borrowed across all of these, but we add native words too so a menu request in
# any served language is recognised deterministically.
_MENU_KEYWORDS: tuple[str, ...] = (
    # English — canonical + catalogue variants (F109 / R-028 misspellings)
    "menu", "full menu", "show menu", "see menu", "the list",
    "what do you have", "what do you serve", "what's available", "options",
    "catalog", "catalogue", "show catalog", "show catalogue",
    # catalogue misspellings (F109): catlog / catlogue / catalouge / cataloge
    "catlog", "catlogue", "catalouge", "cataloge",
    # Hindi / Urdu (roman + script) — menu-intent phrases, not generic "what is"
    "menu dikhao", "menu bhejo", "menu dikha", "kya kya hai", "kya milega", "list bhejo",
    "मेनू", "सूची",
    # Arabic (menu / the list / what do you have)
    "قائمة", "المنيو", "منيو", "القائمة", "ماذا لديكم",
    # Telugu (menu / what items are there / list)
    "మెను", "మెనూ", "ఏమి ఉన్నాయి", "జాబితా",
)

# LLM filler that promises a menu without calling menu_show — engine must deliver.
_MENU_PROMISE_PATTERNS: tuple[str, ...] = (
    "here's our menu", "let me show you", "take a look", "view full menu",
)


async def _text_is_exact_catalogue_dish(
    session: AsyncSession,
    restaurant_id: int,
    text: str,
) -> bool:
    """True when ``text`` is an unambiguous exact dish name (not a note fragment)."""
    q = (text or "").strip()
    if not q:
        return False
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=q)
    if result.confidence != MatchConfidence.DIRECT or not result.candidates:
        return False
    return result.candidates[0].name_normalized == normalize_name(q)


def _dish_ref_matches_cart_name(dish_ref: str, cart_name: str) -> bool:
    """True when a partial customer dish reference targets an in-cart line name."""
    skip = frozenset({"with", "and", "the", "a", "an", "in", "for", "on", "please", "need"})
    ref_tokens = [
        t for t in normalize_name(dish_ref).split()
        if t not in skip and len(t) > 2
    ]
    if not ref_tokens:
        return False
    name_norm = normalize_name(cart_name)
    hits = sum(1 for t in ref_tokens if t in name_norm)
    return hits >= max(1, len(ref_tokens) - 1)


def _pick_in_cart_dish_id(
    matches: list,
    dish_ref: str,
) -> int | None:
    if len(matches) == 1:
        return matches[0].dish_id
    if len(matches) > 1:
        best = max(
            matches,
            key=lambda it: sum(
                1 for t in normalize_name(dish_ref).split()
                if t in normalize_name(it.dish_name)
            ),
        )
        return best.dish_id
    return None


async def _resolve_in_cart_dish_id(
    session: AsyncSession,
    order_id: int,
    dish_ref: str | None,
) -> int | None:
    """Map a partial dish reference to a dish_id already in the draft cart."""
    from app.ordering.models import OrderItem

    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order_id))
    ).all()
    if not items:
        return None
    if not (dish_ref or "").strip():
        return items[0].dish_id if len(items) == 1 else None
    matches = [
        it for it in items
        if _dish_ref_matches_cart_name(dish_ref, it.dish_name)
    ]
    hit = _pick_in_cart_dish_id(matches, dish_ref)
    if hit is not None:
        return hit
    # dish_ref may embed kitchen instructions after the dish name
    # ("chicken biriyani chest piece double masala" → in-cart "Chicken Biryani").
    skip = frozenset({"with", "and", "the", "a", "an", "in", "for", "on", "please", "need"})
    words = [
        t for t in normalize_name(dish_ref).split()
        if t not in skip and len(t) > 2
    ]
    for cut in range(len(words) - 1, 0, -1):
        prefix = " ".join(words[:cut])
        pm = [it for it in items if _dish_ref_matches_cart_name(prefix, it.dish_name)]
        hit = _pick_in_cart_dish_id(pm, prefix)
        if hit is not None:
            return hit
    return None


def _is_menu_request(text: str) -> bool:
    """True for short, explicit 'show me the menu' messages, in ANY served language.

    Kept tight (short message + a menu keyword) so normal ordering text like
    'add the chicken from the menu' isn't intercepted. Multilingual so a menu request in
    Hindi/Arabic/Telugu is honoured, not suppressed by the menu gate."""
    t = text.strip().lower()
    if not t or len(t) > 40:
        return False
    # Bare intent words — EXACT match only (as substrings they'd turn
    # "cancel my order" into a menu request). Absorbed from the deleted webhook
    # _CATALOG_KEYWORDS shortcut so these route through the engine (takeover
    # respected, turn recorded, phase-aware) instead of bypassing it.
    if t in {"order", "items", "list", "order food", "place order", "order now"}:
        return True
    if not any(k in t for k in _MENU_KEYWORDS):
        return False
    # Structural negation: substantial non-menu content means ordering, not catalogue.
    remainder = t
    for k in sorted(_MENU_KEYWORDS, key=len, reverse=True):
        remainder = remainder.replace(k, " ")
    remainder = _re.sub(r"[^\w\s]", " ", remainder, flags=_re.UNICODE)
    remainder = _re.sub(r"\s+", " ", remainder).strip()
    r_tokens = [w for w in remainder.split() if w]
    if len(r_tokens) >= 3 or len(remainder.replace(" ", "")) > 12:
        return False
    return True


def _is_cart_query(text: str) -> bool:
    """True for 'what's in my cart / show my order' style LISTING requests (lowercased).

    Answered deterministically with the real cart so the model can't mis-handle it
    (e.g. re-send the catalogue). Kept tight, and never matches an edit/cancel
    ('cancel my order', 'clear cart', 'add to cart') which are real actions.

    Deliberately NOT a bare "cart" substring check: "is my cart good for lunch"
    contains the word "cart" but is asking for a judgment, not a listing — that
    must fall through to the AI (grounded with the real cart) for a real answer,
    not the canned "reply with more items or done" dump (prod regression)."""
    t = text.strip().lower()
    if not t or len(t) > 45:
        return False
    # Strip polite/filler lead-ins so "ok show my cart", "can you show my cart",
    # "pls show cart" resolve the same as the bare phrase. Prod regression: these
    # fell through to the LLM, which ad-libbed "Here's your cart so far 😊" with NO
    # items instead of the deterministic render below.
    for _lead in ("please ", "pls ", "plz ", "kindly ", "can you ", "could you ",
                  "can u ", "could u ", "would you ", "ok ", "okay ", "so ", "hey ",
                  "yo ", "just ", "now "):
        while t.startswith(_lead):
            t = t[len(_lead):].strip()
    t = t.lstrip(",.:;! ").strip()
    if not t:
        return False
    if any(w in t for w in ("cancel", "clear", "empty", "remove", "delete", "add ")):
        return False
    # A QUESTION *about* the cart ("is my cart good for lunch", "should i add more")
    # wants an ANSWER, not a raw dump — let the LLM handle it. Display requests never
    # start with these evaluative interrogatives.
    if t.startswith((
        "is ", "are ", "was ", "were ", "should ", "would ", "could ", "do ",
        "does ", "am ", "will ", "shall ", "how good", "how's my", "hows my",
        "what do you think", "what do u think", "what you think",
    )):
        return False
    exact = {"cart", "my cart", "show cart", "show my cart", "view cart", "check cart",
             "check my cart", "cart?", "my cart?", "basket", "my basket", "my order"}
    if t in exact:
        return True
    # Targeted LISTING phrases only — never a bare "my cart" substring, which would
    # swallow opinion questions like "what do you think of my cart" (must reach the LLM).
    return any(p in t for p in (
        "what's in my cart", "whats in my cart", "what is in my cart", "in my cart",
        "show my cart", "check my cart", "view my cart", "show me my cart", "see my cart",
        "what my cart", "whats my cart", "show me the cart", "see the cart",
        "in my basket", "show my basket",
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
    if any(p in t for p in phrases):
        return True
    # Abbreviated / typo'd forms the phrase list misses — "share ur location", "send u
    # location", "drop ur pin", "whats ur address". The customer is asking the RESTAURANT
    # to share where it is (not offering to share their own).
    if _re.search(r"\b(share|send|sent|drop|give|show)\b[\w ]{0,15}\b(location|address|pin|spot|map)\b", t):
        return True
    if _re.search(r"\b(ur|your)\s+(exact\s+)?(location|address|pin|spot)\b", t):
        return True
    return False


# UAE PDPL (Federal Decree-Law No. 45 of 2021) data-subject-access detection.
# Deterministic and conservative: personal-data phrasings only — plain "data" /
# "privacy" words alone never trigger (they stay LLM-path on-topic keywords).
_DATA_ACCESS_RE = _re.compile(
    r"(?:\bmy\s+personal\s+(?:data|info(?:rmation)?)\b"
    r"|\b(?:tell|show|give|send)\s+me\s+my\s+(?:data|info(?:rmation)?)\b"
    r"|\bmy\s+(?:data|info(?:rmation)?)\s+(?:as\s+per|under|according)\b"
    r"|\b(?:info(?:rmation)?|data)\s+(?:do\s+)?(?:you|u)\s+"
    r"(?:store|have|keep|collect|hold|save)\b"
    r"|\bwhat\s+(?:do\s+)?(?:you|u)\s+know\s+about\s+me\b"
    r"|\b(?:delete|remove|erase|wipe)\s+my\s+"
    r"(?:data|info(?:rmation)?|account|details|number)\b"
    r"|\bmy\s+(?:data|info(?:rmation)?)\s+deleted\b"
    r"|\bprivacy\s+policy\b|\bdata\s+protection\b|\bpersonal\s+data\b"
    r"|\bpdpl\b|\bgdpr\b"
    r"|\bright\s+to\s+(?:access|erasure|be\s+forgotten)\b)",
    _re.IGNORECASE,
)


def _is_data_access_request(text: str | None) -> bool:
    """True for a PDPL/GDPR data-subject request (access or deletion)."""
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > 400:
        return False
    return bool(_DATA_ACCESS_RE.search(t))


def _privacy_data_reply(restaurant_name: str) -> str:
    """Static PDPL access-request answer: stored-data categories + rights."""
    return (
        f"🔒 *Your data with {restaurant_name}*\n\n"
        "To run your delivery service we store:\n"
        "• 📱 Your phone number & WhatsApp profile name\n"
        "• 📍 Delivery addresses and location pins you share\n"
        "• 🧾 Your order history (dishes, totals — cash on delivery only, "
        "we never store card details)\n"
        "• 💬 This chat history (older messages are archived as short summaries)\n"
        "• 🛵 Rider location during your deliveries (kept 30 days, then deleted)\n\n"
        "Under UAE data protection law (PDPL, Federal Decree-Law 45/2021) you can "
        "ask for access, correction, or deletion of your data at any time. "
        "To correct or delete anything, just reply here or call the restaurant "
        "and we'll take care of it 😊"
    )


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


def _is_cancel_intent(text: str | None) -> bool:
    """True when the customer clearly asks to cancel the order (not a coupon/etc.).

    Used to give an ESCAPE from the modify flow — without it a 'Cancel order' tap
    or 'cancel' message inside modify_items was treated as a dish and looped. Kept
    tight (short message, explicit cancel words) so normal ordering text never fires.
    """
    if not text:
        return False
    t = " ".join(text.strip().lower().split()).replace("’", "'")
    if not t or len(t) > 40:
        return False
    if "coupon" in t or "voucher" in t or t.startswith("don't") or t.startswith("dont"):
        return False
    exact = {
        "cancel", "cancel it", "stop", "abort", "forget it", "forget the order",
        "never mind", "nevermind", "discard", "discard order", "scrap it",
    }
    if t in exact:
        return True
    return t.startswith((
        "cancel order", "cancel my order", "cancel the order", "cancel this",
        "cancel everything", "stop order", "stop the order", "forget this order",
    ))


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


# Category availability questions — "do you have any drinks?", "u have any soup".
# Regression: the LLM (or _looks_like_menu anti-hallucination guard) dumped the ENTIRE
# catalogue (500+ lines). These get a SHORT filtered list or catalogue cards for ONE
# category — never the full menu.
_CATEGORY_AVAIL_PATTERNS: tuple[str, ...] = (
    r"^(?:do you|you|u|have you|got)\s+(?:have|got|serve|sell)\s+(?:any\s+)?(.+?)[\?\.!]*$",
    r"^(?:any|some)\s+(.+?)[\?\.!]*$",
    r"^what\s+(.+?)\s+(?:do you have|you have|u have|are there|are available|available)[\?\.!]*$",
)
_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "drink": (
        "drink", "beverage", "juice", "coffee", "tea", "mojito", "shake", "lassi",
        "soda", "cola", "smoothie", "mocktail", "latte", "espresso", "cappuccino",
    ),
    "soup": ("soup", "soups", "broth"),
    "biryani": ("biryani", "biriyani", "mandi"),
    "dessert": ("dessert", "sweet", "falooda", "ice cream", "cake"),
    "pizza": ("pizza",),
    "burger": ("burger",),
    "sandwich": ("sandwich",),
    "shawarma": ("shawarma",),
    "starter": ("starter", "appetizer", "appetiser", "snack"),
    "salad": ("salad",),
}
_CATEGORY_QUERY_BROAD: frozenset[str] = frozenset({
    "menu", "food", "anything", "something", "item", "items", "dish", "dishes",
    "everything", "stuff", "option", "options",
})
_CATEGORY_REPLY_MAX = 15
_FULL_MENU_TEXT_CAP = 40


def _normalize_category_keyword(raw: str) -> str:
    """Strip filler and simple plurals from a parsed category phrase."""
    t = _re.sub(r"\s+", " ", (raw or "").strip().lower()).strip("?.! ")
    for lead in ("the ", "a ", "an ", "any ", "some "):
        if t.startswith(lead):
            t = t[len(lead):].strip()
    if t.endswith("s") and t[:-1] in _CATEGORY_ALIASES:
        t = t[:-1]
    return t


def _category_match_needles(keyword: str) -> tuple[str, ...]:
    """Expand a customer keyword into substrings to match category or product names."""
    base = _normalize_category_keyword(keyword)
    if not base:
        return ()
    if base in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[base]
    return (base,)


def _parse_category_availability_query(text: str | None) -> str | None:
    """If the message asks whether we have a category ('any drinks?'), return the keyword."""
    if not text:
        return None
    if _is_menu_request(text) or _dish_info_question(text):
        return None
    t = _re.sub(r"\s+", " ", text.strip().lower()).replace("'", "'")
    if not t or len(t) > 80:
        return None
    for pat in _CATEGORY_AVAIL_PATTERNS:
        m = _re.match(pat, t)
        if m:
            kw = _normalize_category_keyword(m.group(1))
            if kw and kw not in _CATEGORY_QUERY_BROAD:
                return kw
    return None


# Ingredient / dish browse — "I want boneless chicken", "something with paneer".
# Short filtered list or ONE category's catalogue cards — never the full menu.
# Optional leading conversational filler so "And I want soup" / "ok show me curry
# options" still parse (prod: "And I want soup u have" fell through to the LLM, which
# gave a vague "let me check the menu" and never surfaced the soup). "i want/give me"
# stay the trigger — filler here is only leading connectors/acks, never "i want ... to".
_DISH_SEARCH_LEAD = (
    r"(?:and|also|then|ok|okay|okey|so|ya+|yes|yeah|please|pls|plz|aa+h?|ah|hey|hmm+|"
    r"um+|now|kindly)\s+"
)
_DISH_SEARCH_PATTERNS: tuple[str, ...] = (
    rf"^(?:{_DISH_SEARCH_LEAD})*(?:i want|i'd like|id like|looking for|something with)"
    r"\s+(.+?)[\?\.!]*$",
    rf"^(?:{_DISH_SEARCH_LEAD})*(?:give me|show me)\s+(.+?)\s+options?[\?\.!]*$",
)
_DISH_SEARCH_LEAD_FILLERS: tuple[str, ...] = (
    "to have ", "to get ", "to order ", "the ", "a ", "an ",
)
# Trailing "…do you have?", "…you got", "…available" question tails that pollute the
# keyword ("soup u have" → "soup"). Read the whole phrase, then match on the real noun.
_DISH_SEARCH_TRAIL_RE = _re.compile(
    r"\s+(?:do\s+)?(?:you|u|ya)?\s*(?:have|got|available)(?:\s+any)?\s*\??$"
)


def _normalize_dish_search_keyword(raw: str) -> str:
    """Strip filler from a parsed dish-search phrase (leading articles + trailing
    'do you have?' question tails), so the keyword is the real dish/ingredient noun."""
    t = _re.sub(r"\s+", " ", (raw or "").strip().lower()).strip("?.! ")
    t = _DISH_SEARCH_TRAIL_RE.sub("", t).strip()
    for lead in _DISH_SEARCH_LEAD_FILLERS:
        if t.startswith(lead):
            t = t[len(lead):].strip()
    return t


def _parse_dish_search_query(text: str | None) -> str | None:
    """If the message browses by ingredient ('I want boneless chicken'), return keyword."""
    if not text:
        return None
    if _is_menu_request(text) or _dish_info_question(text):
        return None
    if _parse_category_availability_query(text):
        return None
    t = _re.sub(r"\s+", " ", text.strip().lower()).replace("'", "'")
    if not t or len(t) > 80:
        return None
    for pat in _DISH_SEARCH_PATTERNS:
        m = _re.match(pat, t)
        if m:
            kw = _normalize_dish_search_keyword(m.group(1))
            if kw and kw not in _CATEGORY_QUERY_BROAD:
                return kw
    return None


async def _dish_search_is_browse_only(
    session: AsyncSession,
    restaurant_id: int,
    keyword: str,
) -> bool:
    """True when 'I want X' should show a filtered list; False when X is cart-ready.

    Design rule: exclude dish-search when the keyword is a direct dish order
    (e.g. 'biryani' → Chicken Biryani). Multi-word ingredient phrases like
    'boneless chicken' stay browse even when one dish name matches.
    """
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    needles = _category_match_needles(kw)
    if not needles:
        return False

    from app.menu.models import Dish, Menu

    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if menu is None:
        return True

    dishes = (
        await session.scalars(
            select(Dish).where(
                Dish.menu_id == menu.id,
                Dish.is_available == True,  # noqa: E712
                Dish.meta_status == "active",
            )
        )
    ).all()

    name_hits: list[Dish] = []
    desc_only_hits = 0
    for d in dishes:
        if await _catalog_excludes_dish(session, restaurant_id, d):
            continue
        name_blob = (d.name or "").lower()
        desc_blob = _dish_search_description(d).lower()
        in_name = any(n in name_blob for n in needles)
        in_desc = any(n in desc_blob for n in needles)
        if in_name:
            name_hits.append(d)
        elif in_desc:
            desc_only_hits += 1

    if desc_only_hits and not name_hits:
        return True
    if len(name_hits) > 1:
        return True

    match = await find_dish_matches(session, restaurant_id=restaurant_id, query=kw)
    if match.confidence != MatchConfidence.DIRECT or not match.candidates:
        return True

    kw_norm = normalize_name(kw)
    dish_norm = (match.candidates[0].name_normalized or "").lower()
    if kw_norm and dish_norm == kw_norm:
        return False

    if len(kw.split()) == 1:
        return False

    return True


# Filler openers stripped before a browse phrase is matched, so "can you suggest ..."
# still counts while an off-topic sentence that merely CONTAINS the word does not.
_BROWSE_LEAD_FILLER: tuple[str, ...] = (
    "ok", "okay", "okey", "so", "hey", "hi", "hello", "yo", "please", "pls", "plz",
    "can you", "can u", "could you", "could u", "would you", "will you", "pls can you",
    "i want you to", "i want u to", "kindly", "just",
)
_BROWSE_START_PHRASES: tuple[str, ...] = (
    "show me", "suggest", "recommend", "pick for me", "pick me", "surprise me",
    "surprise", "what should i order", "what should i get", "what do you recommend",
)


def _strip_browse_lead_filler(text: str) -> str:
    """Drop leading filler openers so a browse phrase can be matched at the START."""
    t = _re.sub(r"[^\w ]", " ", (text or "").lower())
    t = _re.sub(r"\s+", " ", t).strip()
    changed = True
    while changed:
        changed = False
        for f in _BROWSE_LEAD_FILLER:
            if t == f:
                return ""
            if t.startswith(f + " "):
                t = t[len(f) + 1:].strip()
                changed = True
    return t


def _is_menu_browse_intent(text: str) -> bool:
    """True for short browse/suggest messages that are not explicit menu keywords.

    The browse phrase must be at the START (after simple filler like "can you") — a
    longer sentence that merely mentions "suggest" ("I have fever can u suggest me a
    tablet") is NOT a menu browse and falls through to the AI to handle in context.
    """
    t = (text or "").strip().lower()
    if not t or len(t) > 45:
        return False
    if _is_menu_request(text):
        return True
    stripped = _strip_browse_lead_filler(text)
    return any(stripped.startswith(p) for p in _BROWSE_START_PHRASES)


def _is_suggestion_browse_intent(text: str) -> bool:
    """True when the customer wants curated picks, not a full menu dump. Start-anchored
    (after filler) so an off-topic sentence containing "suggest" isn't hijacked here."""
    stripped = _strip_browse_lead_filler(text)
    return any(
        stripped.startswith(p)
        for p in ("suggest", "recommend", "surprise", "pick for me", "pick me")
    )


def _maybe_reset_post_order_for_browse(conv: Conversation, text: str) -> bool:
    """Re-open ordering when post_order customer wants to browse again (empty cart)."""
    if _resolve_phase(conv) != "post_order":
        return False
    if conv.state.get("draft_order_id") or conv.state.get("pending_order_id"):
        return False
    if not _is_menu_browse_intent(text):
        return False
    _set_state(
        conv,
        dialogue_phase="ordering",
        dialogue_state="collecting_items",
        draft_order_id=None,
        pending_order_id=None,
    )
    return True


async def _handle_menu_browse(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Deterministic full menu for 'show me' browse intents (not ingredient search)."""
    await _send_menu_or_catalog(
        session, conv, inbound, restaurant_id, prefix="menu-browse",
    )


_SUGGESTION_CANDIDATE_MAX = 30
_SUGGESTION_LIST_MAX = 10  # WhatsApp interactive list row cap


async def _load_suggestion_candidates(
    session: AsyncSession,
    restaurant_id: int,
    *,
    filter_keyword: str | None,
) -> list[dict]:
    """Load menu rows for the suggestion sub-agent (optionally filtered, capped at 30)."""
    needles = _category_match_needles(filter_keyword) if filter_keyword else ()
    candidates: list[dict] = []

    if await _catalog_mode_on(session, restaurant_id):
        from app.catalog.service import _category_of, _load_sendable_products

        _cid, sendable = await _load_sendable_products(session, restaurant_id)
        for p in sendable or []:
            cat = _category_of(p)
            desc = getattr(p, "description", None) or ""
            if needles and not _item_matches_dish_search_query(
                name=p.name, description=desc, needles=needles,
            ):
                continue
            candidates.append({
                "name": p.name,
                "category": cat,
                "description": desc,
                "price_aed": p.price_aed,
            })
    else:
        from app.menu.models import Dish, Menu

        menu = await session.scalar(
            select(Menu).where(
                Menu.restaurant_id == restaurant_id, Menu.status == "active",
            )
        )
        if menu is not None:
            dishes = (
                await session.scalars(
                    select(Dish).where(
                        Dish.menu_id == menu.id,
                        Dish.is_available == True,  # noqa: E712
                        Dish.meta_status == "active",
                    ).order_by(Dish.category, Dish.name)
                )
            ).all()
            for d in dishes:
                if await _catalog_excludes_dish(session, restaurant_id, d):
                    continue
                desc = _dish_search_description(d)
                if needles and not _item_matches_dish_search_query(
                    name=d.name, description=desc, needles=needles,
                ):
                    continue
                candidates.append({
                    "name": d.name,
                    "category": d.category or "Menu",
                    "description": desc,
                    "price_aed": d.price_aed,
                })

    return candidates[:_SUGGESTION_CANDIDATE_MAX]


async def _handle_top_sellers(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Deterministic bestseller list for the Suggestions quick-action button."""
    from app.menu.models import Dish
    from app.ordering.models import Order

    order_id = conv.state.get("draft_order_id") or conv.state.get("pending_order_id")
    order = await session.get(Order, order_id) if order_id else None
    in_cart: set[int] = set()
    if order is not None:
        in_cart = await _cart_dish_ids(session, order.id)

    picks: list[Dish] = []
    rows = await _top_seller_candidates(session, restaurant_id, limit=10)
    for dish_id, _ in rows:
        if dish_id in in_cart:
            continue
        d = await session.get(Dish, dish_id)
        if d is None or not d.is_available:
            continue
        if not getattr(d, "whatsapp_enabled", True):
            continue
        if _SLUG_NAME.match(d.name or ""):
            continue
        if await _catalog_excludes_dish(session, restaurant_id, d):
            continue
        picks.append(d)
        if len(picks) >= _SUGGESTION_LIST_MAX:
            break

    if not picks:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="top-sellers-none",
            body="Tell us what you're in the mood for 😊",
        )
        await _send_menu_or_catalog(
            session, conv, inbound, restaurant_id, prefix="top-sellers-menu",
        )
        return

    rows = [
        {
            "id": f"upsell_add:{d.id}",
            "title": (d.name or "Dish")[:24],
            "description": f"AED {_aed(d.price_aed)}"[:72],
        }
        for d in picks
    ]
    await _send_list(
        session,
        conv=conv,
        inbound=inbound,
        restaurant_id=restaurant_id,
        prefix="top-sellers",
        body=(
            "Here are our bestsellers 😊\n\n"
            "Tap *Add to cart* below, then pick a dish — you can add one at a "
            "time and open the list again for more. When you're happy, tap "
            "*Proceed to delivery* on the next message 👇"
        ),
        button_label="Add to cart",
        sections=[{"title": "Bestsellers", "rows": rows}],
    )
    await _send_suggestion_companion_buttons(
        session, conv, inbound, restaurant_id, prefix="top-sellers-nav",
    )


async def _send_suggestion_companion_buttons(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    prefix: str,
) -> None:
    """Follow the suggestion list — WhatsApp's list overlay has no checkout/skip.

    Sent as a second message so the customer can proceed, decline more adds,
    or clear without picking from the list."""
    cart = await _build_cart_summary(session, conv)
    body = (
        f"🛒 {cart}\n\nAdd more from the list above, or continue 👇"
        if cart
        else "Pick from the list above to add, or continue 👇"
    )
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=prefix,
        body=body,
        buttons=[
            {"id": "proceed_delivery", "title": "Proceed to delivery"},
            {"id": "suggest_done", "title": "I'm good"},
            {"id": "clear_cart", "title": "Clear cart"},
        ],
    )


async def _handle_suggestions(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Grounded dish picks from filtered candidates or the suggestion sub-agent."""
    raw = (inbound.payload.get("text") or "").strip()
    browse_filter = conv.state.get("browse_filter")
    text_kw = _parse_dish_search_query(raw)
    filter_kw = browse_filter or text_kw
    is_vague = not filter_kw

    candidates = await _load_suggestion_candidates(
        session, restaurant_id, filter_keyword=filter_kw or None,
    )

    if not candidates:
        label = (filter_kw or "that").strip().title()
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="suggestion-none",
            body=(
                f"We couldn't find anything matching {label.lower()} right now 🙏 "
                "Here's our full menu — tell me what catches your eye 😊"
            ),
        )
        await _send_menu_or_catalog(
            session, conv, inbound, restaurant_id, prefix="suggestion-menu-fallback",
        )
        return

    _set_state(conv, menu_in_context=True)
    use_sub_agent = len(candidates) > 3 or is_vague

    if not use_sub_agent:
        label = (filter_kw or "your search").strip().title()
        lines = [f"Here are my picks for {label.lower()} 😊"]
        for c in candidates:
            price = c.get("price_aed")
            price_s = f": AED {_aed(price)}" if price is not None else ""
            lines.append(f"• {c['name']}{price_s}")
        lines.append("\nTell me what you'd like and I'll add it 😊")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="suggestion-list",
            body="\n".join(lines),
        )
        return

    from app.llm.factory import get_suggestion_agent

    try:
        result = await get_suggestion_agent().suggest(
            candidates, raw, browse_filter,
        )
    except Exception:
        _logger.exception("Suggestion sub-agent failed; using deterministic fallback")
        result = {
            "intro": "Here are a few ideas!",
            "picks": [
                {"dish_name": c["name"], "reason": ""}
                for c in candidates[:3]
            ],
        }

    candidate_by_name = {c["name"].lower(): c for c in candidates}
    valid_picks: list[dict] = []
    for pick in result.get("picks") or []:
        dish_name = (pick.get("dish_name") or "").strip()
        if not dish_name:
            continue
        match = await find_dish_matches(
            session, restaurant_id=restaurant_id, query=dish_name,
        )
        if match.confidence != MatchConfidence.DIRECT or not match.candidates:
            continue
        resolved = match.candidates[0].name
        if resolved.lower() not in candidate_by_name:
            continue
        valid_picks.append({
            "dish_name": resolved,
            "reason": (pick.get("reason") or "").strip(),
            "price_aed": candidate_by_name[resolved.lower()].get("price_aed"),
        })
        if len(valid_picks) >= 3:
            break

    if not valid_picks:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="suggestion-invalid",
            body="Tell me what you're in the mood for 😊 Here's our menu:",
        )
        await _send_menu_or_catalog(
            session, conv, inbound, restaurant_id, prefix="suggestion-menu-fallback",
        )
        return

    intro = (result.get("intro") or "Here are a few ideas for you!").strip()
    lines = [intro]
    for p in valid_picks:
        reason = p.get("reason") or ""
        price = p.get("price_aed")
        price_s = f" — AED {_aed(price)}" if price is not None else ""
        if reason:
            lines.append(f"• {p['dish_name']} — {reason}{price_s}")
        else:
            lines.append(f"• {p['dish_name']}{price_s}")
    lines.append("\nTell me what you'd like and I'll add it 😊")
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="suggestion-picks",
        body="\n".join(lines),
    )


def _dish_search_description(dish: object) -> str:
    """Customer-facing description for dish-search matching (name + description blob)."""
    return (
        getattr(dish, "description_customer", None)
        or getattr(dish, "description", None)
        or ""
    )


def _item_matches_dish_search_query(
    *, name: str, description: str | None, needles: tuple[str, ...],
) -> bool:
    """True when a menu row matches a dish-search keyword (name + description)."""
    blob = f"{(name or '').lower()} {(description or '').lower()}"
    return any(n in blob for n in needles)


def _item_matches_category_query(
    *, name: str, category: str, needles: tuple[str, ...],
) -> bool:
    """True when a menu row matches a category-availability keyword."""
    blob = f"{(category or '').lower()} {(name or '').lower()}"
    return any(n in blob for n in needles)


async def _handle_category_availability_query(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    keyword: str,
) -> None:
    """Answer 'do you have drinks?' with a capped list or ONE category's catalogue cards."""
    needles = _category_match_needles(keyword)
    if not needles:
        return

    _set_state(conv, menu_in_context=True)

    label = keyword.strip().title() or "that"
    matched: list[tuple[str, str, object]] = []  # (name, category, price)
    matched_cat_names: list[str] = []

    if await _catalog_mode_on(session, restaurant_id):
        from app.catalog.service import _category_of, _load_sendable_products, send_catalog_category

        _cid, sendable = await _load_sendable_products(session, restaurant_id)
        if sendable:
            cat_counts: dict[str, int] = {}
            for p in sendable:
                cat = _category_of(p)
                if _item_matches_category_query(name=p.name, category=cat, needles=needles):
                    matched.append((p.name, cat, p.price_aed))
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            matched_cat_names = [c for c, _ in sorted(
                cat_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )]

            if len(matched_cat_names) == 1 and _cid:
                intro = (
                    f"Yes! We have {label} 😊 Tap below to pick one, "
                    "then send your basket to order."
                )
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="category-query-intro",
                    body=intro,
                )
                sent = await send_catalog_category(
                    session,
                    restaurant_id=restaurant_id,
                    to_phone=inbound.from_phone,
                    category=matched_cat_names[0],
                    idempotency_key=f"catq-{conv.id}-{inbound.wa_message_id}",
                )
                if sent:
                    return
    else:
        from app.menu.models import Dish, Menu

        menu = await session.scalar(
            select(Menu).where(
                Menu.restaurant_id == restaurant_id, Menu.status == "active",
            )
        )
        if menu is not None:
            dishes = (
                await session.scalars(
                    select(Dish).where(
                        Dish.menu_id == menu.id,
                        Dish.is_available == True,  # noqa: E712
                        Dish.meta_status == "active",
                    ).order_by(Dish.category, Dish.name)
                )
            ).all()
            cat_counts: dict[str, int] = {}
            for d in dishes:
                if await _catalog_excludes_dish(session, restaurant_id, d):
                    continue
                cat = d.category or "Menu"
                if _item_matches_category_query(name=d.name, category=cat, needles=needles):
                    matched.append((d.name, cat, d.price_aed))
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            matched_cat_names = [c for c, _ in sorted(
                cat_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )]

    if not matched:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="category-query-none",
            body=(
                f"We don't have {label.lower()} on the menu right now 🙏 "
                "Say 'menu' to see what we do have, or tell me another dish 😊"
            ),
        )
        return

    emoji = _category_emoji(matched_cat_names[0] if matched_cat_names else label)
    lines = [f"Yes! We have {label} {emoji} Here's a selection:"]
    for name, _cat, price in matched[:_CATEGORY_REPLY_MAX]:
        lines.append(f"• {name}: AED {_aed(price)}")
    extra = len(matched) - _CATEGORY_REPLY_MAX
    if extra > 0:
        lines.append(
            f"\n…and {extra} more. Tell me what you'd like, "
            "or say 'menu' to browse everything 🍛"
        )
    else:
        lines.append("\nTell me what you'd like and I'll add it 😊")
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="category-query-list",
        body="\n".join(lines),
    )


async def _handle_dish_search(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    keyword: str,
) -> None:
    """Answer 'I want boneless chicken' with a capped list or ONE category's catalogue cards."""
    needles = _category_match_needles(keyword)
    if not needles:
        return

    _set_state(conv, menu_in_context=True)

    label = keyword.strip().title() or "that"
    matched: list[tuple[str, str, object]] = []  # (name, category, price)
    matched_cat_names: list[str] = []

    if await _catalog_mode_on(session, restaurant_id):
        from app.catalog.service import _category_of, _load_sendable_products, send_catalog_category

        _cid, sendable = await _load_sendable_products(session, restaurant_id)
        if sendable:
            cat_counts: dict[str, int] = {}
            for p in sendable:
                cat = _category_of(p)
                desc = getattr(p, "description", None) or ""
                if _item_matches_dish_search_query(
                    name=p.name, description=desc, needles=needles,
                ):
                    matched.append((p.name, cat, p.price_aed))
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            matched_cat_names = [c for c, _ in sorted(
                cat_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )]

            if len(matched_cat_names) == 1 and _cid:
                intro = (
                    f"Here's what we have with {label.lower()} 😊 Tap below to pick one, "
                    "then send your basket to order."
                )
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="dish-search-intro",
                    body=intro,
                )
                sent = await send_catalog_category(
                    session,
                    restaurant_id=restaurant_id,
                    to_phone=inbound.from_phone,
                    category=matched_cat_names[0],
                    idempotency_key=f"dsq-{conv.id}-{inbound.wa_message_id}",
                )
                if sent:
                    return
    else:
        from app.menu.models import Dish, Menu

        menu = await session.scalar(
            select(Menu).where(
                Menu.restaurant_id == restaurant_id, Menu.status == "active",
            )
        )
        if menu is not None:
            dishes = (
                await session.scalars(
                    select(Dish).where(
                        Dish.menu_id == menu.id,
                        Dish.is_available == True,  # noqa: E712
                        Dish.meta_status == "active",
                    ).order_by(Dish.category, Dish.name)
                )
            ).all()
            cat_counts: dict[str, int] = {}
            for d in dishes:
                if await _catalog_excludes_dish(session, restaurant_id, d):
                    continue
                cat = d.category or "Menu"
                if _item_matches_dish_search_query(
                    name=d.name,
                    description=_dish_search_description(d),
                    needles=needles,
                ):
                    matched.append((d.name, cat, d.price_aed))
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            matched_cat_names = [c for c, _ in sorted(
                cat_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )]

    if not matched:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="dish-search-none",
            body=(
                f"We couldn't find anything with {label.lower()} on the menu right now 🙏 "
                "Say 'menu' to see what we do have, or tell me another dish 😊"
            ),
        )
        return

    emoji = _category_emoji(matched_cat_names[0] if matched_cat_names else label)
    lines = [f"Here's what we have with {label.lower()} {emoji}"]
    for name, _cat, price in matched[:_CATEGORY_REPLY_MAX]:
        lines.append(f"• {name}: AED {_aed(price)}")
    extra = len(matched) - _CATEGORY_REPLY_MAX
    if extra > 0:
        lines.append(
            f"\n…and {extra} more. Tell me what you'd like, "
            "or say 'menu' to browse everything 🍛"
        )
    else:
        lines.append("\nTell me what you'd like and I'll add it 😊")
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="dish-search-list",
        body="\n".join(lines),
    )


async def _render_catalog_menu(session: AsyncSession, restaurant_id: int) -> str:
    """Render the SYNCED Meta catalogue as categorized text.

    In catalogue mode this is the bot's menu knowledge — so it only ever talks about /
    recommends products that are actually in the catalogue (never a text-menu dish the
    customer can't order)."""
    from app.catalog.tenant_scope import load_tenant_catalog_mirror

    _cid, products = await load_tenant_catalog_mirror(session, restaurant_id)
    if not products:
        return "Our catalogue is currently empty. Please try again later."

    from app.catalog.service import _apply_category_map, _category_of, _load_category_map

    _apply_category_map(products, await _load_category_map(session, restaurant_id))
    lines: list[str] = ["👋 *Welcome! Here's our menu*"]
    current_category: str | None = None
    shown = 0
    for p in products:
        if shown >= _FULL_MENU_TEXT_CAP:
            break
        cat = _category_of(p)
        if cat != current_category:
            current_category = cat
            if current_category:
                lines.append(f"\n{_category_emoji(current_category)} *{current_category}*")
        price = _aed(p.price_aed) if p.price_aed is not None else "?"
        lines.append(f"• {p.name}: AED {price}")
        shown += 1
    if len(products) > _FULL_MENU_TEXT_CAP:
        lines.append(
            f"\n…and {len(products) - _FULL_MENU_TEXT_CAP} more items. "
            "Say 'menu' to open the catalogue, or tell me what you'd like 😊"
        )
    else:
        lines.append("\nJust tell me what you'd like and I'll add it to your order 😊")
    return "\n".join(lines)


async def _catalog_mode_on(session: AsyncSession, restaurant_id: int) -> bool:
    """True if this restaurant is in catalogue ordering mode (flag on AND catalog_id set)."""
    from app.identity.models import Restaurant, catalog_mode_enabled

    rest = await session.get(Restaurant, restaurant_id)
    return bool(rest is not None and catalog_mode_enabled(rest.settings))


async def _catalog_excludes_dish(session: AsyncSession, restaurant_id: int, dish) -> bool:
    """True when ``dish`` must never be shown/ordered on WhatsApp.

    Two independent gates:
    - ``whatsapp_enabled=False`` (manager's per-dish WhatsApp switch, TX-45) excludes the
      dish in EVERY mode — text or catalogue.
    - In CATALOGUE mode, True when ``dish`` is additionally NOT part of the synced Meta
      catalogue — so the bot won't describe, recommend, or let a customer type-order a
      text-menu item that isn't actually orderable. Always False (for this gate) in text
      mode (no restriction)."""
    from app.identity.models import Restaurant, catalog_mode_enabled

    if getattr(dish, "meta_status", "active") == "archived":
        return True
    if not getattr(dish, "whatsapp_enabled", True):
        return True
    rest = await session.get(Restaurant, restaurant_id)
    if rest is None or not catalog_mode_enabled(rest.settings):
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


async def _render_menu(
    session: AsyncSession, restaurant_id: int, *, force_text: bool = False
) -> str:
    """Render the active menu as categorized text.

    Catalogue mode: the menu knowledge is the synced Meta catalogue, NOT the text-menu
    dishes — so the bot never offers items the customer can't order from the catalogue.
    ``force_text`` bypasses that bound (used when catalogue cards could not be sent).
    """
    from app.identity.models import Restaurant, catalog_mode_enabled
    from app.menu.models import Dish, Menu

    _rest = await session.get(Restaurant, restaurant_id)
    if not force_text and _rest is not None and catalog_mode_enabled(_rest.settings):
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
        .where(
            Dish.menu_id == menu.id,
            Dish.is_available == True,  # noqa: E712
            Dish.meta_status == "active",
            Dish.whatsapp_enabled == True,  # noqa: E712 — manager's per-dish WA switch (TX-45)
        )
        .order_by(Dish.category, Dish.dish_number)
    )
    # Slug-named dishes (e.g. 'chicken_biryani') are internal identifiers that leaked
    # into the name column — never customer-facing (F74/F97).
    dish_list = [d for d in dishes if not _SLUG_NAME.match(d.name or "")]
    if not dish_list:
        return "Our menu is currently unavailable. Please try again later."

    lines: list[str] = ["👋 *Welcome! Here's our menu*"]
    current_category: str | None = None
    for dish in dish_list[:_FULL_MENU_TEXT_CAP]:
        if dish.category != current_category:
            current_category = dish.category
            if current_category:
                lines.append(f"\n{_category_emoji(current_category)} *{current_category}*")
        price = _aed(dish.price_aed)
        lines.append(f"• {dish.name}: AED {price}")

    if len(dish_list) > _FULL_MENU_TEXT_CAP:
        lines.append(
            f"\n…and {len(dish_list) - _FULL_MENU_TEXT_CAP} more items. "
            "Tell me what you'd like, or say 'menu' to browse 😊"
        )
    else:
        lines.append("\nJust tell me what you'd like and I'll add it to your order 😊")
    return "\n".join(lines)


# Minimum seconds between two full menu dumps to the same conversation. Within
# this window a repeat request gets a one-line pointer instead.
_MENU_RESEND_COOLDOWN_S = 120


async def _send_menu_or_catalog(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    prefix: str,
) -> bool:
    """Unified menu: send WhatsApp catalogue cards when synced; else text menu.

    Customers always get one menu surface. Catalogue is preferred when a
    ``catalog_id`` is configured and products have been synced from Meta.

    Cooldown: a second menu send within ``_MENU_RESEND_COOLDOWN_S`` gets a short
    "menu's just above" pointer instead of the full dump (prod: two identical
    full-menu messages in the same minute — noise for the customer AND for the
    model's context, which then treats menu-dumping as the norm).
    """
    import time as _time

    from app.identity.models import Restaurant

    _now = _time.time()
    _last = float((conv.state or {}).get("last_menu_sent_at") or 0)
    if _now - _last < _MENU_RESEND_COOLDOWN_S:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix=f"{prefix}-again",
            body="The menu's just above 👆 Tell me the dish (or dish number) and I'll add it 😊",
        )
        _set_state(conv, dialogue_state="menu_sent", menu_in_context=True)
        return False
    _set_state(conv, last_menu_sent_at=_now)

    restaurant = await session.get(Restaurant, restaurant_id)
    settings = (restaurant.settings or {}) if restaurant is not None else {}
    catalog_id = (settings.get("catalog_id") or "").strip()
    if catalog_id:
        from app.catalog.service import send_catalog

        sent = await send_catalog(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            idempotency_key=f"{prefix}-catalog-{conv.id}-{inbound.wa_message_id}",
        )
        if sent:
            _set_state(conv, dialogue_state="menu_sent", menu_in_context=True)
            return True
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=prefix, body=await _render_menu(session, restaurant_id, force_text=True),
    )
    _set_state(conv, dialogue_state="menu_sent", menu_in_context=True)
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
    from app.identity.models import Restaurant, catalog_mode_enabled
    from app.menu.models import Menu, MenuFile
    from app.menu.storage import FileBlobStore

    restaurant = await session.get(Restaurant, restaurant_id)
    if restaurant is not None and catalog_mode_enabled(restaurant.settings):
        # Catalogue mode — strict. Send the cards; if they can't be sent, ask the
        # customer to type (the engine still parses typed items) but show NO text menu.
        # Always ACK with a short text line FIRST: catalog cards are enqueued async and
        # Meta can still reject delivery (#131009) after commerce is enabled, which used
        # to leave the customer staring at ✓✓ with zero reply.
        brand = (restaurant.name or "us").strip() or "us"
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="greeting-catalog-ack",
            body=(
                f"Hi! Welcome to {brand} 👋\n\n"
                "Sending our menu now — or just type what you'd like and I'll add it 😊"
            ),
        )
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
        # Catalogue greeting used to return before resale — offer fast-deal food here too.
        await _maybe_offer_resale(session, conv, inbound, restaurant_id)
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
    from app.ordering.resale import _resale_cfg, resale_offer_for_customer

    if conv.state.get("resale_offer_id"):
        return False

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
    cfg = _resale_cfg(settings)
    if cfg.get("discount_type") == "fixed":
        save_line = f"save AED {_aed(offer['discount_aed'])}"
    else:
        save_line = f"{cfg.get('discount_value', 0)}% off (save AED {_aed(offer['discount_aed'])})"
    _set_state(conv, resale_offer_id=order.id)
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=f"resale-offer-{order.id}",
        body=(
            f"⚡ Ready *right now* — skip the wait!\n"
            f"{dish_line}\n"
            f"Just AED {_aed(offer['discounted_subtotal'])} ({save_line}) — "
            "already cooked, delivered fast. 🛵"
        ),
        buttons=[{"id": f"resale_accept:{order.id}", "title": "Grab it ⚡"}],
    )
    return True


async def _companion_order_for_resale(
    session: AsyncSession, conv: Conversation,
):
    """Return the customer's in-progress cart order to batch with a resale accept."""
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Order

    for key in ("draft_order_id", "pending_order_id"):
        oid = conv.state.get(key)
        if not oid:
            continue
        order = await session.get(Order, oid)
        if order and str(order.status) in (
            str(OrderStatus.DRAFT),
            str(OrderStatus.PENDING_CONFIRMATION),
            str(OrderStatus.CONFIRMED),
            str(OrderStatus.PREPARING),
        ):
            return order
    return None


async def _finalize_resale_accept(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    resale_order,
    customer,
    addr,
    distance_km: float | None,
    delivery_fee_aed: Decimal,
    settings: dict,
    distance_source: str | None = None,
) -> None:
    """Mark resale sold, spawn the discounted READY order, dispatch (+ batch companion)."""
    from app.ordering.resale import accept_resale
    from app.ordering.service import is_excluded_for_resale

    # AND-gate delivery guard (now that we know the buyer's real address): refuse only when
    # phone + door/apartment + building + pin ALL match the canceller's — i.e. the same
    # person trying to get their own cancelled food back at the same address.
    if is_excluded_for_resale(
        getattr(resale_order, "exclusion_hash", None),
        phone=inbound.from_phone,
        room_apartment=getattr(addr, "room_apartment", None),
        building=getattr(addr, "building", None),
        lat=getattr(addr, "latitude", None),
        lon=getattr(addr, "longitude", None),
    ):
        _set_state(conv, resale_offer_id=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="resale-same-address",
            body="Sorry, this deal can't be delivered to this address 🙏 "
                 "Reply with a dish to order fresh.",
        )
        return

    companion = await _companion_order_for_resale(session, conv)
    new_order = await accept_resale(
        session,
        resale_order=resale_order,
        customer_id=customer.id,
        address_id=addr.id,
        settings=settings,
        distance_km=distance_km,
        delivery_fee_aed=delivery_fee_aed,
        companion_order=companion,
    )
    # Record how the distance/fee was derived on the spawned order (F112/F31).
    if new_order is not None and distance_source is not None:
        new_order.distance_source = distance_source
        await session.flush()
    _set_state(
        conv,
        resale_offer_id=None,
        dialogue_phase="post_order",
        dialogue_state="order_placed",
        draft_order_id=None if companion is not None else conv.state.get("draft_order_id"),
        pending_order_id=None if companion is not None else conv.state.get("pending_order_id"),
    )
    extra = ""
    if companion is not None:
        extra = " Your other dishes will ride along in the same delivery. 🛵"
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=f"resale-accepted-{new_order.id}",
        body=(
            f"Yours! 🎉 Order #{new_order.order_number} — AED {_aed(new_order.total)} (COD).\n"
            f"It's already cooked and on its way fast.{extra}"
        ),
    )


async def _handle_resale_location_pin(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant,
) -> None:
    """Complete a pending resale accept from a shared GPS pin (no saved address yet)."""
    from app.ordering.fees import UndeliverableError, calculate_fee
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Order
    from app.ordering.service import get_or_create_customer, upsert_address

    order_id = conv.state.get("resale_offer_id")
    if not order_id:
        return
    resale_order = await session.get(Order, order_id)
    if resale_order is None or str(resale_order.status) != str(OrderStatus.ON_RESALE):
        _set_state(conv, resale_offer_id=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="resale-gone",
            body="Sorry, that deal was just taken 😕 Reply with a dish to order fresh.",
        )
        return

    from app.ordering.fees import radius_km

    lat = float(inbound.payload["latitude"])
    lon = float(inbound.payload["longitude"])
    rest_lat = restaurant.lat if restaurant else 25.2048
    rest_lng = restaurant.lng if restaurant else 55.2708
    dist, dist_source = await _road_distance_km(rest_lat, rest_lng, lat, lon)
    fee_settings = await _fee_settings_for(session, restaurant_id)
    try:
        fee = calculate_fee(dist, fee_settings)
    except UndeliverableError:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="resale-undeliverable",
            body="Sorry, that location is outside our delivery area. "
                 f"Share a pin within {radius_km(fee_settings):g} km, or order fresh dishes instead.",
        )
        return

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )
    addr = await upsert_address(
        session,
        customer_id=customer.id,
        latitude=lat,
        longitude=lon,
        room_apartment="",
        building="WhatsApp pin",
        receiver_name=customer.name or "Customer",
        confirmed=True,
    )
    settings = (restaurant.settings or {}) if restaurant else {}
    await _finalize_resale_accept(
        session, conv, inbound, restaurant_id,
        resale_order=resale_order,
        customer=customer,
        addr=addr,
        distance_km=dist,
        distance_source=dist_source,
        delivery_fee_aed=fee,
        settings=settings,
    )


async def _handle_resale_accept(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int,
    order_id: int,
) -> None:
    """Customer accepted a resale offer. If they have a saved address, sell it now
    (mark RESOLD, spawn discounted ready order, dispatch to their address). Else ask
    them to share their location to claim it."""
    from app.identity.models import Restaurant
    from app.ordering.fees import UndeliverableError, calculate_fee, radius_km
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Order
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
        await _send_location_request(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="resale-need-loc",
            body="Great choice! 📍 Tap below to share your delivery location — "
                 "I'll send the ready meal right over.",
        )
        return
    restaurant = await session.get(Restaurant, restaurant_id)
    settings = (restaurant.settings or {}) if restaurant else {}
    dist = None
    dist_source = None
    fee = Decimal("0.00")
    if addr.latitude is not None and addr.longitude is not None:
        rest_lat = restaurant.lat if restaurant else 25.2048
        rest_lng = restaurant.lng if restaurant else 55.2708
        dist, dist_source = await _road_distance_km(rest_lat, rest_lng, addr.latitude, addr.longitude)
        fee_settings = await _fee_settings_for(session, restaurant_id)
        try:
            fee = calculate_fee(dist, fee_settings)
        except UndeliverableError:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="resale-undeliverable",
                body="Sorry, your saved address is outside our delivery area. "
                     f"Share a new pin within {radius_km(fee_settings):g} km to claim the deal.",
            )
            return
    await _finalize_resale_accept(
        session, conv, inbound, restaurant_id,
        resale_order=resale_order,
        customer=customer,
        addr=addr,
        distance_km=dist,
        distance_source=dist_source,
        delivery_fee_aed=fee,
        settings=settings,
    )


def _set_state(conv: Conversation, **updates) -> None:
    """Merge keys into conv.state (JSONB) without losing existing keys."""
    conv.state = {**conv.state, **updates}


def _is_internal_leak(text: str) -> bool:
    """Detect compaction/system_summary JSON that must never reach WhatsApp."""
    t = (text or "").strip()
    if not t:
        return False
    if "[Earlier conversation summary]" in t and ("compacted_count" in t or t.startswith("{")):
        return True
    if t.startswith("{") and "compacted_count" in t:
        return True
    return False


async def _send_text(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
) -> None:
    if _is_internal_leak(body):
        _logger.warning(
            "blocked internal compaction leak to WhatsApp conv=%s prefix=%s",
            conv.id,
            prefix,
        )
        body = "Let me help you with the menu 😊"
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
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
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={"body": body, "buttons": buttons},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )


async def _send_list(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
    button_label: str,
    sections: list[dict],
) -> None:
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.LIST,
        payload={
            "body": body,
            "button_label": button_label,
            "sections": sections,
        },
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
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
    payload = {"body": body, "button_label": button_label, "url": url}
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.CTA_URL,
        payload=payload,
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
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
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=inbound.from_phone,
        msg_type=OutboundMessageType.LOCATION_REQUEST,
        payload={"body": body},
        idempotency_key=f"{prefix}-{conv.id}-{inbound.wa_message_id}",
    )


# Leading words to strip when echoing back what the customer asked for, so a
# negated/filler phrase ("No beef biryani", "a beef biryani") echoes cleanly as
# "Beef Biryani".
_ECHO_LEAD_STRIP = frozenset({
    "no", "not", "a", "an", "the", "some", "any", "want", "need", "give", "me",
    "i", "id", "please", "pls", "get", "add", "have", "we", "do", "you",
})


def _clean_requested_name(dish_query: str) -> str:
    """Title-cased dish name to echo in an off-menu reply, or '' if nothing usable.

    Drops leading filler/negation words so "No beef biryani" → "Beef Biryani".
    Kept short and defensive — never echoes a giant blob back at the customer.
    """
    tokens = _re.findall(r"[^\W\d_]+", (dish_query or ""), _re.UNICODE)
    while tokens and tokens[0].lower() in _ECHO_LEAD_STRIP:
        tokens.pop(0)
    if not tokens or len(tokens) > 6:
        return ""
    return " ".join(t.capitalize() for t in tokens)


def _off_menu_decline(dish_query: str) -> str:
    """Warm, premium-tone 'we don't have that' reply — NO upselling a substitute.

    The customer is treated as a valued guest: we apologise, never push an
    alternative dish, and gently point them back to the menu so they choose.
    """
    name = _clean_requested_name(dish_query)
    item = name if name else "that"
    return (
        f"My apologies — we don't have {item} on our menu 🙏 "
        "I'd be glad to help with anything else; just tell me the dish, "
        "or tap the menu to take a look 😊"
    )


# Explicit "I'm ordering X" verb prefixes (longest first so the most specific wins).
# Used ONLY to recognise a clear order so an OFF-MENU one always gets the warm
# decline, instead of the LLM sometimes mis-routing it to clear_cart / modify.
_ORDER_VERB_PREFIXES = (
    "i want to order ", "i want to add ", "i would like to order ",
    "i'd like to order ", "can i please get ", "could i please get ",
    "i will have ", "i'll have ", "ill have ", "i'll take ", "ill take ",
    "i'll get ", "ill get ", "i would like ", "i'd like ", "id like ",
    "can i get ", "can i have ", "could i get ", "could i have ", "may i have ",
    "please give me ", "please get me ", "let me get ", "lemme get ",
    "give me ", "get me ", "i want ", "i wanna ", "i need ", "order ", "add ",
)
# Leading filler/articles/quantities dropped from the extracted dish phrase.
_BODY_LEAD_STRIP = frozenset({
    "a", "an", "the", "some", "my", "our", "your", "it", "that", "this", "them",
    "me", "of", "for", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "more", "another", "also", "plus", "and",
})
# Trailing politeness/filler dropped from the extracted dish phrase.
_BODY_TRAIL_STRIP = frozenset({
    "also", "too", "please", "pls", "now", "thanks", "thanx", "thankyou",
    "as", "well", "more", "and", "plz",
})
# First words that mean the message is NOT an order (a question / a control word),
# so the off-menu guard never hijacks them.
_NON_ORDER_HEADS = frozenset({
    "to", "know", "see", "check", "cancel", "change", "modify", "remove", "delete",
    "stop", "wait", "hold", "help", "talk", "speak", "call", "where", "when",
    "what", "why", "how", "who", "which", "is", "are", "do", "does", "can", "could",
    "will", "would", "info", "information", "details", "detail", "status", "track",
    "menu", "cart", "order", "bill", "total", "price", "cost", "delivery", "address",
    "location", "time", "minute", "second", "moment", "coupon", "discount", "refund",
})


def _extract_order_dish_query(text: str | None) -> str | None:
    """If the message is clearly 'I want to order <dish>', return the dish phrase.

    Deliberately tight so it NEVER fires on questions, control words, or chit-chat:
    requires an explicit order verb / quantity prefix, a ≥2-word food phrase after
    stripping articles+politeness, and a non-question head word. Returns None
    otherwise. The caller only acts on the result when the phrase is OFF the menu,
    so a valid dish is never intercepted — it still flows to the AI as before.
    """
    if not text:
        return None
    t = " ".join(text.strip().split()).replace("’", "'")
    if not t or len(t) > 70 or "?" in t:
        return None
    low = t.lower()
    # MODIFY / qty-change phrasing is NOT a fresh order — leave it to the AI /
    # deterministic summary path (e.g. "make it two", "change to ...", "instead").
    if any(p in low for p in (
        "make it", "change", "instead", "actually", "swap", "replace",
        "update", "remove", "take off", "rather",
    )):
        return None

    body: str | None = None
    for v in _ORDER_VERB_PREFIXES:
        if low.startswith(v):
            body = t[len(v):].strip()
            break
    if body is None:
        from app.ordering.service import parse_qty_and_text

        _q, rest = parse_qty_and_text(t)
        if rest and rest.strip().lower() != low:  # a real quantity prefix was present
            body = rest.strip()
        else:
            return None

    toks = [w for w in body.split()]
    while toks and (
        toks[0].lower().strip(",.!") in _BODY_LEAD_STRIP
        or toks[0].strip(",.!x").isdigit()  # leading qty digit ("2", "2x")
    ):
        toks.pop(0)
    while toks and toks[-1].lower().strip(",.!") in _BODY_TRAIL_STRIP:
        toks.pop()
    if len(toks) < 2 or len(toks) > 5:
        return None
    if toks[0].lower().strip(",.!") in _NON_ORDER_HEADS:
        return None
    return " ".join(toks)


async def _maybe_decline_off_menu_order(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> bool:
    """Deterministic guard: a clear order for an OFF-MENU dish always gets the warm
    decline — so 'beef biryani' behaves exactly like 'mutton biryani' every time,
    never mis-routed by the LLM to clear_cart / modify.

    Returns True (and replies) only when the message is unambiguously an order, the
    dish isn't on the menu and isn't a known out-of-stock item. A valid or unknown-
    intent message returns False and falls through to the normal AI flow untouched.
    Skipped in catalogue mode (the catalogue flow + AI own that path).
    """
    if inbound.type != MessageType.TEXT:
        return False
    phase = _resolve_phase(conv)
    if phase not in ("ordering", "awaiting_confirmation"):
        return False
    dish_query = _extract_order_dish_query(inbound.payload.get("text"))
    if not dish_query:
        return False
    if await _catalog_mode_on(session, restaurant_id):
        return False

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence != MatchConfidence.NO_MATCH:
        return False  # on the menu (or fuzzy-close) → let the AI handle it normally
    from app.ordering.matching import find_unavailable_match

    if await find_unavailable_match(session, restaurant_id=restaurant_id, query=dish_query):
        return False  # we DO have it, just out of stock → AI offers an alternative

    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="off-menu-order", body=_off_menu_decline(dish_query),
    )
    return True


def _is_checkout_intent(text: str) -> bool:
    """True when the customer wants to finish ordering (not a dish name)."""
    t = (text or "").strip().lower()
    return t in ("done", "checkout", "that's all", "thats all")


# Broader "I'm finished adding items" detector for the AI path, where the LLM was
# unreliable — it looped re-adding the same dish on "that's all" and once bounced to a
# greeting. Tolerates a leading "no" ("no that's all") and trailing filler ("thats all
# thanks", "thats all can't you understand", "motherf*** that's all").
_DONE_PHRASES: frozenset[str] = frozenset({
    "done", "checkout", "check out", "proceed", "proceed to checkout", "finish",
    "finished", "im done", "i am done", "that will be all", "thats all", "that is all",
    "thats it", "that is it", "thats everything", "that is everything", "nothing else",
    "no more", "no more thanks", "complete order", "place order", "im good", "no thats all",
    # Confirm-phrasings (prod: "Confirm the order" fell through to the LLM and looped
    # the menu instead of advancing to checkout).
    "confirm", "confirm order", "confirm the order", "confirm my order",
    "confirm it", "place my order", "place the order",
    # Casual "that's it" without the apostrophe-s ("ya that it", "that it") — common
    # from non-native speakers; normalised text drops the apostrophe so "thats it"
    # already matches, but the elided "that it" did not.
    "that it", "ya that it", "yes that it", "ya thats it", "yes thats it",
    # UAE / Gulf-casual "finish it": khalas (done/enough), yalla (let's go / send it).
    "khalas", "khalas bas", "yalla", "yallah", "yala", "yalla send",
    "yalla go", "send yalla",
    # Common English "wrap it up" phrasings seen in chat orders.
    "thats enough", "that is enough", "im finished", "i am finished",
    "we are done", "were done", "we done", "all done", "all set", "thats all thanks",
    "order it", "order now", "order please", "place it", "place order now",
    "go ahead", "lets go", "let us go", "proceed please", "checkout please",
    "send it now", "send now", "deliver now", "deliver please", "ready to checkout",
})
_DONE_EDGES: tuple[str, ...] = (
    "thats all", "that is all", "thats it", "that is it", "that it", "thats everything",
    "that is everything", "nothing else", "im done", "i am done", "that will be all",
)
# Beyond this many words, a message that only STARTS/ENDS with a done-edge is treated as
# a real request for the LLM, not a bare checkout. Exact-phrase matches ignore this cap.
_CHECKOUT_EDGE_MAX_WORDS = 6

# Negation swap (prod: "No give me chicken soup" straight after "Added 1x Staff
# Chicken Biriyani" means REPLACE, not add-alongside — the LLM crashed on it and the
# customer got the canned error). Explicit desire verb required: a bare "no <dish>"
# stays ambiguous (could mean remove) and falls through to the existing paths.
_NEGATION_SWAP_RE = _re.compile(
    r"^no+[,.!\s]+(?:no+[,.!\s]+)*"
    r"(?:give me|i want|i need|i said|get me|send me|bring me|make it)\s+"
    r"(?P<rest>.+)$"
)


# Delivery-phrased checkout (prod: "Send it to me brothrr" / "Deliver the things I
# asked you to" fell through to the LLM, which re-dumped the menu — customer gave up
# and cancelled). Verb + order-object at the START of the message; the object set is
# closed so "send me the menu", "deliver to <address>" and "do you deliver" never match.
_SEND_ORDER_RE = _re.compile(
    r"^(?:please |pls |now |ok |okay )*"
    r"(?:send|deliver|bring|ship)\s+"
    r"(?:it|them|that|this|everything|"
    r"(?:the )?(?:things?|items?|stuff|food|order|dishes)|"
    r"my (?:order|food|items?|stuff))\b"
)


# Friendly UAE vocatives customers tack onto an instruction ("done habibi", "ok bro",
# "yalla akhi"). Stripped from the EDGES before intent matching so the vocative never
# hides an otherwise-clear checkout/ack. Trailing "my" is also dropped so "that's all my
# friend" resolves. Kept to address-terms only — never a dish word.
_FRIENDLY_VOCATIVES: frozenset[str] = frozenset({
    "habibi", "habib", "habibti", "bro", "bros", "brother", "brotha", "brothr",
    "brothrr", "bruh", "bru", "akhi", "akhy", "khoya", "boss", "chief", "yaar",
    "bhai", "dear", "friend", "man", "buddy", "sir", "madam",
})


def _strip_edge_vocatives(t: str) -> str:
    """Drop leading/trailing friendly vocatives (and a trailing 'my') so a Gulf-casual
    'ok habibi' / 'done my friend' still reads as its bare intent."""
    words = t.split()
    while words and words[0] in _FRIENDLY_VOCATIVES:
        words.pop(0)
    while words and (words[-1] in _FRIENDLY_VOCATIVES or words[-1] == "my"):
        words.pop()
    return " ".join(words)


def _is_done_intent(text: str) -> bool:
    """True for a 'that's all / done / nothing else' checkout phrase (AI path)."""
    # Drop apostrophes FIRST so "that's" → "thats" (else the apostrophe becomes a space
    # and "that s all" never matches "thats all"), then punctuation → space, collapse.
    t = _re.sub(r"[’'`]", "", (text or "").lower())
    t = _re.sub(r"\s+", " ", _re.sub(r"[^\w ]", " ", t)).strip()
    t = _strip_edge_vocatives(t)
    if not t:
        return False
    stripped = t[3:].strip() if t.startswith("no ") else t
    if t in _DONE_PHRASES or stripped in _DONE_PHRASES:
        return True
    if _SEND_ORDER_RE.match(stripped):
        return True
    # A clear done-phrase at the START or END of the message (e.g. angry prefix) counts;
    # matching only at the edges avoids false hits like the question "is that all you have".
    # Word cap: a long, complex sentence that merely ENDS in "that's all" ("can you make
    # it spicy and add fries and remove the soup, that's all") is a real request for the
    # LLM — not a bare checkout. Exact-phrase matches above are unbounded (finite + short).
    if len(stripped.split()) > _CHECKOUT_EDGE_MAX_WORDS:
        return False
    return stripped.startswith(_DONE_EDGES) or stripped.endswith(_DONE_EDGES)


# Bare acknowledgments after a cart edit ("Updated … ✅" → customer "Ok") mean proceed to
# checkout — NOT a new order line. Must be whole-message only so "ok add biryani" still
# routes to the typed-add path (leading "ok" is stripped there as filler).
_ACK_PROCEED_PHRASES: frozenset[str] = frozenset({
    "ok", "okay", "okey", "k", "sure", "yes", "yep", "yeah", "fine", "good", "great",
    # UAE-casual affirmatives: tamam (ok/fine), sahi (right), zain (good), okok.
    "tamam", "tmam", "sahi", "zain", "okok", "ok ok", "aiwa", "aywa", "perfect",
})


def _is_ack_proceed_intent(text: str) -> bool:
    """True when the customer sends only a short ack meaning 'proceed / that's fine'."""
    t = _re.sub(r"[’'`]", "", (text or "").lower())
    t = _re.sub(r"\s+", " ", _re.sub(r"[^\w ]", " ", t)).strip()
    t = _strip_edge_vocatives(t)
    return bool(t) and t in _ACK_PROCEED_PHRASES


def _is_checkout_shortcut(text: str) -> bool:
    """Done-phrases OR bare acks that should advance checkout when the cart has items."""
    return _is_done_intent(text) or _is_ack_proceed_intent(text)


# Leading phrases that mark a QUESTION / COMPLAINT / aside rather than a request to add a
# dish. The item parser strips filler words ("add", "you") and would otherwise mine a
# stray "2 biryani" out of "why did you add 2 biryani" and silently grow the cart. Kept
# deliberately narrow — only leading interrogatives/complaint openers — so a real order
# ("2 biryani", "chicken biryani please") is never blocked.
_ORDER_QUESTION_LEADS: tuple[str, ...] = (
    "why", "how come", "how much", "how many", "who ", "whom", "whose", "when ",
    "where ", "did you", "didn't you", "didnt you", "you add", "you added", "you put",
    "i didn't", "i didnt", "i did not", "i never", "i already", "you do it",
    "do it your", "do it yourself", "you handle", "you cancel", "cancel it your",
)
_ORDER_QUESTION_CONTAINS: tuple[str, ...] = (
    "why did you", "that's wrong", "thats wrong", "that is wrong", "not what i",
    "wrong order", "by mistake", "by your self", "by yourself",
)


def _looks_like_order_question(text: str) -> bool:
    """True when a message is a question/complaint/aside, not a dish request.

    Guards the item-collection parsers so a complaint like "why did you add 2 biryani" or
    an instruction like "you do it yourself" is NOT mined for a stray quantity and added
    to the cart (or matched as a bogus dish). Conservative on purpose."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if t.startswith(_ORDER_QUESTION_LEADS):
        return True
    return any(p in t for p in _ORDER_QUESTION_CONTAINS)


# Off-topic categories — health, homework, etc. NOT food ordering or restaurant service.
# Regression: "I have fever what can I do" dumped the entire menu via the LLM / anti-menu
# guard. These get a warm decline and NEVER a menu.
_OFF_TOPIC_MEDICAL: tuple[str, ...] = (
    "fever", "sick", "illness", " i am ill", " i'm ill", " im ill", "not feeling well",
    "feeling unwell", "doctor", "hospital", "medicine", "medication", "tablet", "tablets",
    "pain", "cough", " flu ", "vomit", "headache", "temperature", "nausea", "diarrhea",
    "diarrhoea", "injured", "injury", "ambulance", "prescription", "symptom", "symptoms",
    "covid", "corona", "infection", "bp ", "blood pressure",
)
_OFF_TOPIC_GENERAL: tuple[str, ...] = (
    "homework", "assignment", "exam ", "tell me a joke", "joke ", "weather forecast",
    "politics", "election", "visa ", "job interview", "fix my phone", "wifi password",
    "relationship advice", "capital of", "who is the president", "write me a",
)
# Keywords that keep a message on-topic even when it also mentions health (ordering soup
# while sick) or is clearly about this restaurant / an order.
_RESTAURANT_ON_TOPIC: tuple[str, ...] = (
    "menu", "order", "cart", "deliver", "delivery", "address", "restaurant", "food",
    "dish", "dishes", "price", "fee", "eta", "track", "coupon", "discount", "biryani",
    "burger", "pizza", "shawarma", "mandi", "soup", "juice", "shake", "save", "data",
    "privacy", "stored", "remember", "hours", "open", "close", "location", "cod", "cash",
    "payment", "total", "subtotal", "confirm", "takeaway", "pickup", "loyalty", "tier",
    "catalogue", "catalog", "complaint", "refund", "rider",
)
_FOOD_ORDER_INTENT: tuple[str, ...] = (
    "order", "get me", "i want", "i'd like", "id like", "give me", "add ", "one ",
    "2 ", "3 ", "something light", "easy to digest", "recommend", "suggest",
)


def _has_food_order_intent(text: str) -> bool:
    """True when the customer is trying to order food, even if they mention being unwell."""
    t = (text or "").strip().lower()
    if not t:
        return False
    if any(p in t for p in _FOOD_ORDER_INTENT):
        return True
    from app.ordering.service import parse_qty_and_text

    qty, rest = parse_qty_and_text(t)
    if qty > 1 or (rest and rest.strip().lower() != t):
        return True
    return False


def _is_restaurant_on_topic(text: str | None) -> bool:
    """True when the message is about ordering, this restaurant, or delivery service."""
    if not text or not text.strip():
        return True
    if (
        _is_menu_request(text)
        or _is_restaurant_location_request(text)
        or _is_tier_query(text)
        or _is_tracking_query(text)
        or _dish_info_question(text)
        or _looks_like_order_question(text)
        or _is_complaint(text)
        or _is_cancel_intent(text)
        or _is_checkout_shortcut(text)
        or _is_clear_cart_command(text)
        or _is_cart_query(text)
    ):
        return True
    t = text.strip().lower()
    if any(p in t for p in _RESTAURANT_ON_TOPIC):
        return True
    if any(p in t for p in (
        "who are you", "what are you", "restaurant name", "your name", "shop name",
        "store name", "what do you save", "what do you store", "anything apart from",
    )):
        return True
    if _has_food_order_intent(t):
        return True
    if _extract_order_dish_query(text):
        return True
    return False


def _classify_off_topic(text: str | None) -> str | None:
    """Return an off-topic category ('medical', 'general') or None when on-topic / ambiguous.

    Conservative: only fires on clear non-restaurant topics so normal chat still reaches
    the AI. Never returns a category for ordering or restaurant-service questions."""
    if not text or _is_restaurant_on_topic(text):
        return None
    t = text.strip().lower()
    if any(w in t for w in _OFF_TOPIC_MEDICAL):
        return "medical"
    if any(p in t for p in _OFF_TOPIC_GENERAL):
        return "general"
    return None


def _off_topic_reply(category: str, restaurant_name: str) -> str:
    """Warm decline for off-topic messages — never offers a menu."""
    if category == "medical":
        return (
            f"I'm sorry you're not feeling well 🙏 {restaurant_name} is a food-ordering "
            "service — we can't give medical advice. Please rest and speak to a doctor "
            "if you need help with your health. When you're ready to order, just tell me "
            "what you'd like 😊"
        )
    return (
        f"Thanks for reaching out 😊 {restaurant_name} can only help with food orders, "
        "our menu, delivery, and your order — not general questions like that. "
        "Tell me what you'd like to eat, or say 'menu' to see what we have 🍛"
    )


# Phrases that genuinely mean "empty my cart / start over". Used to protect the
# destructive clear_cart action: if the LLM tagged a message clear_cart but it says NONE
# of these AND names a dish, it's an order that was misclassified ("one beef curry" read
# as "clear") — so we add the dish instead of silently wiping the cart.
_CLEAR_CART_PHRASES: tuple[str, ...] = (
    "clear", "empty", "start over", "start again", "reset", "wipe", "scrap", "restart",
    "remove all", "remove everything", "delete all", "delete everything",
    "cancel all", "cancel everything", "fresh start", "start fresh", "start new",
    "new order",
)


def _is_explicit_clear(text: str) -> bool:
    """True when the message explicitly asks to empty the cart / start over."""
    t = (text or "").strip().lower()
    return any(p in t for p in _CLEAR_CART_PHRASES)


# PRECISE clear-cart commands for the pre-LLM guard. The clear word is PAIRED with
# cart/order/basket/all/everything (or is a standalone "start over"/"reset"), so this
# never fires on a dish like "clear soup" — where the LLM previously fuzzy-matched
# "clear" → the dish "Clear Soup" and ADDED it instead of clearing.
_CLEAR_CART_COMMANDS: tuple[str, ...] = (
    "clear cart", "clear the cart", "clear my cart", "clear this cart", "clear your cart",
    "clear basket", "clear the basket", "clear my basket", "clear all", "clear everything",
    "clear order", "clear the order", "clear my order", "clear it all",
    "empty cart", "empty the cart", "empty my cart", "empty basket", "empty the basket",
    "empty everything", "start over", "start again", "start fresh", "start a new order",
    "reset cart", "reset the cart", "reset my cart", "remove everything", "remove all",
    "delete everything", "delete all", "cancel all", "cancel everything", "cancel the cart",
    "wipe cart", "wipe the cart", "scrap the order", "clear my basket",
)
_CLEAR_CART_EXACT: frozenset[str] = frozenset({
    "clear", "reset", "empty", "clear cart", "empty cart", "start over", "reset cart",
})


def _is_clear_cart_command(text: str) -> bool:
    """True for an explicit 'empty the whole cart' command. PAIRED phrasing only, so a
    dish order like 'clear soup' is never mistaken for a clear."""
    t = _re.sub(r"[’'`]", "", (text or "").lower())
    t = _re.sub(r"\s+", " ", _re.sub(r"[^\w ]", " ", t)).strip()
    if not t:
        return False
    return t in _CLEAR_CART_EXACT or any(p in t for p in _CLEAR_CART_COMMANDS)


# SET-quantity phrasings — "make it 5", "only 1 biryani", "change to 3", "set it to 2".
# These REPLACE the cart quantity, they don't add to it. The LLM often mis-tags them as
# add_item, so "make it 5" with 1 already in the cart wrongly became 6. Detect them
# deterministically. Kept to unambiguous SET openers (no bare "i want N", which can mean
# "add N").
_SET_QTY_PATTERNS: tuple[str, ...] = (
    r"^make it (\d+)\s*(.*)$",
    r"^change (?:it |them |that )?to (\d+)\s*(.*)$",
    r"^set (?:it |them |that )?(?:to )?(\d+)\s*(.*)$",
    r"^(?:i )?(?:want|need) only (\d+)\s*(.*)$",
    r"^only (\d+)\s+(.*)$",
    r"^just (\d+)\s+(.*)$",
)


# Leading conversational filler stripped before a start-anchored cart-edit parser runs,
# so "Aa pls make it 5" / "and cancel 7up" / "ok remove the soup" still fire (prod: "Aa
# pls make it 5 chicken biryani" was mis-read as ADD 5 → 6). Excludes set-qty verbs like
# "just"/"only" so "just 2 biryani" still SETS. Leading-run only; rest preserved verbatim
# (so internal commas the item-splitter needs survive).
_CART_EDIT_FILLER_RE = _re.compile(
    r"^(?:\s*(?:aa+h?|ah|and|also|then|ok(?:ay|ey)?|so|ya+|ye(?:ah|p)?|yes|please|pls|"
    r"plz|kindly|hmm+|um+|err|hey|now|can\s+(?:you|u)|could\s+(?:you|u)|would\s+you|"
    r"i\s+want\s+(?:you\s+)?(?:u\s+)?to)\b[\s,.!]*)+",
    _re.IGNORECASE,
)


def _strip_cart_edit_lead_filler(text: str) -> str:
    """Drop a run of leading filler words ("Aa pls make it 5" → "make it 5") so a
    start-anchored cart-edit parser still fires. Lowercased; rest kept verbatim."""
    return _CART_EDIT_FILLER_RE.sub("", (text or "").strip()).strip().lower()


def _parse_set_quantity(text: str) -> tuple[int, str] | None:
    """Detect a SET-quantity instruction → (qty, dish_query). dish_query may be '' when
    no dish is named ("make it 5"). Returns None when it isn't a set-quantity message."""
    t = _strip_cart_edit_lead_filler(text)
    if not t:
        return None
    for pat in _SET_QTY_PATTERNS:
        m = _re.match(pat, t)
        if m:
            return int(m.group(1)), (m.group(2) or "").strip()
    return None


# Leading SET-quantity verb, so "make it 5 lemon mint and 2 grill mandi" can be split into
# per-dish targets instead of the whole tail becoming one phantom dish.
_SET_QTY_PREFIX = _re.compile(
    r"^(?:make it|change (?:it |them |that )?to|set (?:it |them |that )?(?:to )?|"
    r"(?:i )?(?:want|need) only|only|just)\s+"
)


def _parse_set_quantity_items(text: str) -> list[tuple[int, str]] | None:
    """Split a SET-quantity instruction into one or more (qty, dish_query) pairs.

    "make it 5 lemon mint and 2 grill mandi" → [(5, "lemon mint"), (2, "grill mandi")].
    "make it 5" → [(5, "")] (dish resolved by the caller). Returns None when it isn't a
    set-quantity, or a multi-segment can't be parsed cleanly (so we never invent a dish
    named "lemon mint and 2 grill mandi")."""
    t = _strip_cart_edit_lead_filler(text)
    m = _SET_QTY_PREFIX.match(t)
    if not m:
        return None
    rest = t[m.end():].strip()
    if not rest:
        return None
    segments = [s.strip() for s in _re.split(r"\s*(?:,|&|\+|\band\b)\s*", rest) if s.strip()]
    if not segments:
        return None
    out: list[tuple[int, str]] = []
    for seg in segments:
        sm = _re.match(r"^(\d+)\s+(.+)$", seg)
        if sm:
            out.append((int(sm.group(1)), sm.group(2).strip()))
        elif len(segments) == 1 and _re.fullmatch(r"\d+", seg):
            out.append((int(seg), ""))  # "make it 5" — dish supplied by the caller
        else:
            return None  # "make it spicy", or a list segment with no quantity
    return out or None


# REMOVE phrasing — "remove 3 chicken soup", "delete biryani", "take off 2 mint".
# Catalogue typed-order used to strip the leading verb and parse_qty_and_text the rest,
# turning "remove 3 soup" into ADD 3. Detect these before the add-only typed-order path.
_REMOVE_ITEM_PATTERNS: tuple[str, ...] = (
    r"^remove (\d+)\s+(.+)$",
    r"^delete (\d+)\s+(.+)$",
    r"^(?:take off|take out) (\d+)\s+(.+)$",
    r"^drop (\d+)\s+(.+)$",
    r"^minus (\d+)\s+(.+)$",
    r"^cancel (\d+)\s+(.+)$",
    r"^remove (.+)$",
    r"^delete (.+)$",
    r"^(?:take off|take out) (.+)$",
    r"^drop (.+)$",
    r"^cancel (.+)$",
)


def _parse_remove_item(text: str) -> tuple[int | None, str] | None:
    """Detect a REMOVE instruction → (qty, dish_query). ``qty=None`` removes all units
    of the dish. Returns None when it isn't a single-item remove (whole-cart clears are
    excluded)."""
    t = _strip_cart_edit_lead_filler(text)
    if not t:
        return None
    if _is_explicit_clear(t) or _is_clear_cart_command(t) or _is_cancel_intent(t):
        return None
    for pat in _REMOVE_ITEM_PATTERNS:
        m = _re.match(pat, t)
        if not m:
            continue
        if m.lastindex == 2:
            qty = int(m.group(1))
            dish = (m.group(2) or "").strip()
        else:
            qty = None
            dish = (m.group(1) or "").strip()
        dish = _re.sub(r"\b(please|pls|thanks|thank you)\b", "", dish).strip()
        if not dish or dish in {"all", "everything", "it", "them", "that"}:
            return None
        if dish.startswith(("all ", "everything ")):
            return None
        return qty, dish
    return None


_REMOVE_VERB_PREFIX = _re.compile(
    r"^(?:remove|delete|take off|take out|drop|minus|cancel)\s+"
)

# Nearest-context references — resolve against the MOST RECENTLY added cart line (what
# the customer just touched) instead of a dish name: "remove it", "cancel that", "one
# more", "another". Read the full sentence (whole-message match, filler stripped).
_REMOVE_REF_RE = _re.compile(
    r"^(?:"
    r"(?:remove|delete|drop|cancel)\s+(?:it|that|this|the last(?: one| item| dish)?|that one|the last)"
    r"|take\s+(?:it|that|this)\s+(?:off|out)"
    r"|take\s+(?:off|out)\s+the\s+last(?: one)?"
    r")\s*$"
)
_ADD_MORE_RE = _re.compile(
    r"^(?:"
    r"(?:add |get |give me )?(?:one|1|another)\s+more(?: please| pls)?"
    r"|another(?: one| please)?"
    r"|one more(?: one)?(?: please| pls)?"
    r"|same again|same one more|more of (?:it|that|this)"
    r")\s*$"
)


def _is_remove_reference(text: str) -> bool:
    """True for a bare 'remove it / cancel that / take it off / remove the last one' —
    a delete aimed at the most-recent cart line, no dish named."""
    return bool(_REMOVE_REF_RE.match(_strip_cart_edit_lead_filler(text)))


def _is_add_more_reference(text: str) -> bool:
    """True for 'one more / another / same again' — add one of the most-recent dish."""
    return bool(_ADD_MORE_RE.match(_strip_cart_edit_lead_filler(text)))


async def _most_recent_cart_item(session: AsyncSession, order_id: int):
    """The most recently added cart line (OrderItem with the highest id, qty>0) — the
    nearest referent for a bare 'make it N' / 'remove it' / 'one more'. None if empty."""
    from app.ordering.models import OrderItem

    rows = [
        r for r in (
            await session.scalars(select(OrderItem).where(OrderItem.order_id == order_id))
        ).all()
        if r.qty > 0
    ]
    return max(rows, key=lambda r: r.id) if rows else None


def _recent_proposed_name(proposed: list) -> str | None:
    """Most-recent dish name in a modify 'proposed' list — the nearest referent for a
    bare 'remove it' / 'make it N' during the modify/post-order flow."""
    for item in reversed(proposed or []):
        if isinstance(item, dict):
            name = item.get("dish_name") or item.get("name")
            if name:
                return name
    return None


def _parse_remove_items(text: str) -> list[tuple[int | None, str]] | None:
    """Split a REMOVE instruction into one or more (qty, dish) pairs, so "remove 1 lemon
    mint and 1 7 up" takes off BOTH (prod: only the first came off). ``qty=None`` removes
    all units of that dish. Mirrors _parse_set_quantity_items so remove handles multi-item
    exactly like set-qty. Returns None for whole-cart clears / cancel-order / non-removes."""
    t = _strip_cart_edit_lead_filler(text)
    if not t:
        return None
    if _is_explicit_clear(t) or _is_clear_cart_command(t) or _is_cancel_intent(t):
        return None
    m = _REMOVE_VERB_PREFIX.match(t)
    if not m:
        return None
    rest = t[m.end():].strip()
    if not rest:
        return None
    segments = [s.strip() for s in _re.split(r"\s*(?:,|&|\+|\band\b)\s*", rest) if s.strip()]
    if not segments:
        return None
    out: list[tuple[int | None, str]] = []
    for seg in segments:
        sm = _re.match(r"^(\d+)\s+(.+)$", seg)
        if sm:
            qty: int | None = int(sm.group(1))
            dish = sm.group(2).strip()
        else:
            qty = None
            dish = seg
        dish = _re.sub(r"\b(please|pls|thanks|thank you)\b", "", dish).strip()
        if not dish or dish in {"all", "everything", "it", "them", "that"}:
            return None
        if dish.startswith(("all ", "everything ")):
            return None
        out.append((qty, dish))
    return out or None


def _is_cart_edit_intent(text: str) -> bool:
    """True when the message is a cart edit (set quantity or remove), not a new add."""
    return (
        _parse_set_quantity_items(text) is not None
        or _parse_remove_item(text) is not None
    )


# KEEP-ONLY phrasing — "only mandi", "just the biryani", "keep only mandi", "i only want
# mandi" means: the cart should hold ONLY that dish (prune the rest). A digit after the
# keyword ("only 2 mandi") is a SET-quantity, not keep-only, so those are excluded.
_KEEP_ONLY_PATTERNS: tuple[str, ...] = (
    r"^keep only (.+)$",
    r"^(?:i )?(?:just |only )?want only (.+)$",
    r"^(?:i )?only want (.+)$",
    r"^(?:i )?just want (.+)$",
    r"^only (.+)$",
    r"^just (.+)$",
)


def _parse_keep_only(text: str) -> str | None:
    """Detect a KEEP-ONLY instruction → the dish query to keep (others get pruned).
    Returns None when it isn't keep-only or names a quantity ("only 2 mandi")."""
    t = (text or "").strip().lower()
    if not t:
        return None
    for pat in _KEEP_ONLY_PATTERNS:
        m = _re.match(pat, t)
        if m:
            dish = (m.group(1) or "").strip()
            # strip a trailing "please/thanks" and drop set-quantity ("only 2 mandi").
            dish = _re.sub(r"\b(please|pls|thanks|thank you)\b", "", dish).strip()
            if dish and not dish[0].isdigit():
                return dish
    return None


async def _handle_confirmation_done(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    restaurant=None,
) -> None:
    """'Done' at the confirm step — re-show the summary or capture address, never both.

    Regression: at awaiting_confirmation with an address already on the order, 'done'
    fell through to the LLM which asked for the address AGAIN and then re-showed the
    summary (ordering-phase checkout logic misfiring at the wrong time)."""
    from app.ordering.models import Order

    oid = conv.state.get("pending_order_id") or conv.state.get("draft_order_id")
    order = await session.get(Order, oid) if oid else None
    if order is None or not await _order_has_items(session, order.id):
        _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="confirm-done-empty",
            body="Your cart is empty. Please add a dish before checking out 😊",
        )
        return
    if order.address_id is not None:
        _set_state(conv, dialogue_phase="awaiting_confirmation",
                   dialogue_state="order_confirmation")
        await _send_order_summary(session, conv, inbound, restaurant_id, order)
        return
    await _begin_address_capture(
        session, conv, inbound, restaurant_id, restaurant=restaurant,
    )


async def _handle_done_checkout(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    restaurant=None,
    empty_prefix: str = "empty-cart",
) -> None:
    """Proceed to address only when the draft cart has items; otherwise block checkout."""
    from app.ordering.models import Order

    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None or str(order.status) != "draft" or not await _order_has_items(
        session, order.id
    ):
        _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix=empty_prefix,
            body="Your cart is empty. Please add at least one dish before proceeding.",
        )
        return
    await _begin_address_capture(session, conv, inbound, restaurant_id, restaurant=restaurant)


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
    if _is_checkout_intent(dish_query):
        await _handle_done_checkout(session, conv, inbound, restaurant_id)
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

    # A question/complaint/aside ("why did you add 2 biryani", "you do it yourself") must
    # NOT be mined for a stray quantity and silently added to the cart. Acknowledge and
    # ask the customer to state the dish + quantity instead of adding anything.
    if _looks_like_order_question(text):
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-question",
            body=("Sorry if that got mixed up 🙂 Tell me the dish and how many you'd like "
                  "(e.g. '1 Chicken Biryani') and I'll add exactly that."),
        )
        return

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)

    if result.confidence == MatchConfidence.NO_MATCH:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-match",
            body=_off_menu_decline(dish_query),
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
    upsell, buttons = await _post_add_extras(session, conv, restaurant_id, order)
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="item-added",
        body=(
            f"Added {qty}x {dish.name} (AED {price}).\n"
            f"Reply with more items, or send 'done' to proceed to delivery details."
            f"{upsell}"
        ),
        buttons=buttons,
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
) -> tuple[float, str]:
    """Distance (km) restaurant → customer + the SOURCE it was derived from.

    Returns ``(distance_km, source)`` where ``source`` is ``"road"`` (the configured
    geo provider answered) or ``"haversine_fallback"`` (the provider raised and we
    degraded to a straight-line estimate). Persisting the source makes the fee basis
    auditable and a degraded quote visible to ops (F112/F31).

    Uses the GeoPort (``google_maps`` → traffic-aware road distance) so the fee and
    radius the customer is quoted match real driving distance. The provider's HTTP
    client is sync, so it's run in a thread to avoid blocking the event loop. This
    wrapper's haversine fallback ensures a provider/config error can never break
    ordering.
    """
    import asyncio

    from app.geo.factory import get_geo_provider
    from app.geo.haversine import distance_km as _haversine

    try:
        dist = await asyncio.to_thread(
            get_geo_provider().distance_km, lat1, lng1, lat2, lng2
        )
        return dist, "road"
    except Exception:  # noqa: BLE001 - never let geo break ordering
        return _haversine(lat1, lng1, lat2, lng2), "haversine_fallback"


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
    dist_source = None
    fee = Decimal("0.00")
    if stored.latitude is not None and stored.longitude is not None:
        dist, dist_source = await _road_distance_km(rest_lat, rest_lng, stored.latitude, stored.longitude)
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
    order.distance_source = dist_source
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
        dist, dist_source = await _road_distance_km(rest_lat, rest_lng, lat, lon)
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
            distance_km=dist, distance_source=dist_source, delivery_fee=str(fee),
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
    order.distance_source = conv.state.get("distance_source")
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
        f"{f' ({it.variant_name})' if it.variant_name else ''}"
        f"{_note_suffix(it)}: "
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
    # Auto-apply an unambiguous single assigned coupon. _redeem_context already
    # scopes these to Coupon.customer_id == this customer, so there's no choice
    # to make — requiring them to type a code they never picked was pure friction
    # (prod feedback: "why isn't there an auto-apply option"). Two+ coupons stay
    # a manual prompt (genuinely ambiguous which one to use); a coupon that fails
    # validation (e.g. below min_order) silently falls back to the prompt too.
    if len(active_coupons) == 1 and Decimal(order.coupon_discount_aed or 0) <= 0:
        from app.coupons.service import CouponError
        from app.ordering.payments import apply_coupon

        try:
            await apply_coupon(
                session, order=order, coupon_code=active_coupons[0].code,
                created_by="system",
            )
        except CouponError:
            pass
        else:
            active_coupons = []
        await session.flush()
    # Payment composition (W5 / R-049 / RA-3): coupon discount, wallet credit applied,
    # and COD due. Summary math == confirm math == door cash. Wallet credit shown is the
    # projected application = min(available balance [+ any existing hold], order total).
    _cent = Decimal("0.01")
    coupon_line = ""
    if Decimal(order.coupon_discount_aed or 0) > 0:
        coupon_line = f"Coupon discount: -AED {_aed(order.coupon_discount_aed)}\n"
    applied = min(
        wallet_available + Decimal(order.wallet_applied_aed or 0), Decimal(order.total)
    ).quantize(_cent)
    if applied > 0:
        cod_due = (Decimal(order.total) - applied).quantize(_cent)
        payment_block = (
            f"💳 Wallet credit: -AED {_aed(applied)}\n"
            f"COD due (cash on delivery): AED {_aed(cod_due)}\n"
        )
    else:
        payment_block = "Payment: COD (cash on delivery)\n"

    # Only prompt for a coupon when the customer still has an unapplied one.
    if active_coupons and Decimal(order.coupon_discount_aed or 0) <= 0:
        redeem_block = "\n🏷️ Have a coupon? Send the code to apply it.\n"

    summary = (
        f"Order summary:\n{item_lines}\n\n"
        f"Subtotal: AED {_aed(order.subtotal)}\n"
        f"Delivery fee: AED {_aed(order.delivery_fee_aed)}\n"
        f"{coupon_line}"
        f"Total: AED {_aed(order.total)}\n"
        f"{payment_block}"
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
    from app.coupons.service import CouponError
    from app.ordering.models import Order
    from app.ordering.payments import apply_coupon

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
        # Single money path (F41): apply_coupon validates/redeems, persists
        # coupon_id + coupon_discount_aed, and recomputes the total — never mutate
        # order.total here by hand.
        result = await apply_coupon(session, order=order, coupon_code=code)
    except CouponError as e:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="coupon-rejected",
            body=f"Sorry, I couldn't apply that coupon ({e}). You can still confirm your order.",
        )
        return
    discount = result["coupon_discount_aed"]
    await session.flush()
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=f"coupon-applied-{order.coupon_id}",
        body=f"Coupon applied — AED {_aed(discount)} off! 🎉 Here's your updated order:",
    )
    await _send_order_summary(session, conv, inbound, restaurant_id, order)


async def _resolve_order_for_modify(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
):
    """Find the placed order the customer is editing.

    Prefer an in-flight modify target, then the order just confirmed
    (``last_placed_order_id``), then the latest non-draft placed order for this
    phone. Draft carts and stale ``pending_order_id`` pointers must never win over
    a freshly confirmed order (regression: modify #R1-0100 after confirm #R1-0118).
    """
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    mod_id = conv.state.get("modify_order_id")
    if mod_id:
        order = await session.get(Order, mod_id)
        if order is not None:
            return order

    last_id = conv.state.get("last_placed_order_id")
    if last_id:
        order = await session.get(Order, last_id)
        if order is not None:
            _terminal = {
                str(OrderStatus.DELIVERED), str(OrderStatus.CANCELLED),
                str(OrderStatus.UNDELIVERABLE), str(OrderStatus.RESOLD),
                str(OrderStatus.WRITTEN_OFF), str(OrderStatus.ON_RESALE),
            }
            if str(order.status) not in _terminal and str(order.status) != str(OrderStatus.DRAFT):
                return order

    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == inbound.from_phone,
        )
    )
    if customer is None:
        return None

    _terminal = {
        str(OrderStatus.DELIVERED), str(OrderStatus.CANCELLED),
        str(OrderStatus.UNDELIVERABLE), str(OrderStatus.RESOLD),
        str(OrderStatus.WRITTEN_OFF), str(OrderStatus.ON_RESALE),
    }
    return await session.scalar(
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.customer_id == customer.id,
            Order.status != str(OrderStatus.DRAFT),
            Order.status.notin_(_terminal),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )


def _clear_modify_state(conv: Conversation) -> None:
    """Drop all modify FSM keys when leaving the edit sub-flow."""
    _set_state(
        conv,
        modify_order_id=None,
        modify_proposed=None,
        modify_proposed_initialized=None,
    )


async def _proposed_from_order(session: AsyncSession, order_id: int) -> list[dict]:
    """Serialize current order lines into modify_proposed entries."""
    from app.ordering.models import OrderItem

    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order_id))
    ).all()
    return [
        {
            "dish_id": it.dish_id,
            "dish_number": it.dish_number,
            "name": it.dish_name,
            "price_aed": str(it.price_aed),
            "qty": it.qty,
        }
        for it in items
    ]


async def _modify_remove_from_proposed(
    session: AsyncSession,
    restaurant_id: int,
    proposed: list[dict],
    dish_query: str,
) -> tuple[list[dict], str | None]:
    """Drop matching lines from modify_proposed. Returns (new_list, removed_name)."""
    if not proposed or not dish_query:
        return proposed, None

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence != MatchConfidence.NO_MATCH and result.candidates:
        cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
        if cands:
            drop_ids = {c.id for c in cands}
            removed_names = [p["name"] for p in proposed if p.get("dish_id") in drop_ids]
            new_list = [p for p in proposed if p.get("dish_id") not in drop_ids]
            if removed_names:
                return new_list, removed_names[0]

    q = dish_query.lower()
    removed_names = [
        p.get("name", "") for p in proposed
        if q in (p.get("name") or "").lower()
    ]
    if removed_names:
        new_list = [p for p in proposed if q not in (p.get("name") or "").lower()]
        return new_list, removed_names[0]
    return proposed, None


async def _modify_keep_only_proposed(
    session: AsyncSession,
    restaurant_id: int,
    proposed: list[dict],
    dish_query: str,
) -> tuple[list[dict], str | None]:
    """Keep/replace modify_proposed with only the named dish (menu substitution allowed)."""
    if not dish_query:
        return proposed, None

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH or not result.candidates:
        return proposed, None
    cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
    if not cands:
        return proposed, None

    # Prefer the candidate already on the order; else take the best menu match (e.g.
    # combo on the order → customer says "only lemon mint" → standalone Lemon Mint).
    dish = None
    proposed_ids = {p.get("dish_id") for p in proposed}
    for c in cands:
        if c.id in proposed_ids:
            dish = c
            break
    if dish is None:
        dish = cands[0]

    kept = next((p for p in proposed if p.get("dish_id") == dish.id), None)
    qty = kept.get("qty", 1) if kept else 1
    return ([{
        "dish_id": dish.id,
        "dish_number": dish.dish_number,
        "name": dish.name,
        "price_aed": str(dish.price_aed),
        "qty": qty,
    }], dish.name)


_MODIFY_BLOCKED_STATUSES = frozenset({
    "ready", "assigned", "picked_up", "arriving", "delivered", "cancelled",
    "undeliverable", "on_resale", "resold", "written_off",
})


def _order_is_modifiable(order) -> bool:
    return str(order.status) not in _MODIFY_BLOCKED_STATUSES


async def _modify_update_qty_in_proposed(
    session: AsyncSession,
    restaurant_id: int,
    proposed: list[dict],
    dish_query: str,
    qty: int,
) -> tuple[list[dict], str | None]:
    """Set absolute qty on a proposed line (qty <= 0 removes the line)."""
    if not dish_query:
        return proposed, None
    if qty <= 0:
        return await _modify_remove_from_proposed(session, restaurant_id, proposed, dish_query)

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH or not result.candidates:
        return proposed, None
    cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
    if not cands:
        return proposed, None
    dish = cands[0]
    entry = {
        "dish_id": dish.id,
        "dish_number": dish.dish_number,
        "name": dish.name,
        "price_aed": str(dish.price_aed),
        "qty": qty,
    }
    new_list = list(proposed)
    idx = next((i for i, p in enumerate(new_list) if p.get("dish_id") == dish.id), None)
    if idx is not None:
        new_list[idx] = entry
    else:
        new_list.append(entry)
    return new_list, dish.name


async def _proposed_differs_from_order(
    session: AsyncSession, order_id: int, proposed: list[dict],
) -> bool:
    """True when proposed lines differ from persisted order_items."""
    from app.ordering.models import OrderItem

    current = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order_id))
    ).all()
    cur_map = {(it.dish_id, it.dish_name): it.qty for it in current}
    prop_map = {(p.get("dish_id"), p.get("name")): p.get("qty", 0) for p in proposed}
    return cur_map != prop_map


async def _offer_full_cancel_from_empty_modify(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    order_id: int,
) -> None:
    """Option A T6: empty proposed → offer whole-order cancel, not a zero-item modify."""
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    num = order.order_number if order else "?"
    _set_state(conv, dialogue_state="modify_confirm", modify_order_id=order_id, modify_proposed=[])
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="modify-empty-offer",
        body=(
            f"That would remove everything from order #{num}. "
            "Would you like to cancel the whole order instead?"
        ),
        buttons=[
            {"id": "cancel_order", "title": "Cancel order"},
            {"id": "cancel_modify", "title": "Keep original"},
        ],
    )


async def _notify_manager_modify_review(
    session: AsyncSession,
    restaurant_id: int,
    order_id: int,
    summary: dict,
) -> None:
    """E-10: staff handoff when a modify proposal reaches review (best-effort)."""
    from app.identity.models import Restaurant
    from app.ordering.models import Order

    restaurant = await session.get(Restaurant, restaurant_id)
    order = await session.get(Order, order_id)
    if restaurant is None or not getattr(restaurant, "phone", None) or order is None:
        return
    summary_line = (summary.get("summary") or "Customer proposed order changes.").strip()
    action_hint = (summary.get("suggested_action") or "").strip()
    change_count = summary.get("change_count", 0)
    mgr_tail = f" Suggested: {action_hint}." if action_hint else ""
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="order",
        entity_id=str(order.id),
        action="modify_review",
        after={
            "order_number": order.order_number,
            "summary": summary_line,
            "change_count": change_count,
            "suggested_action": action_hint or None,
        },
    )
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=restaurant.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={
            "body": (
                f"📝 Order #{order.order_number} — modify review pending "
                f"({change_count} line change(s)): {summary_line}.{mgr_tail} "
                "Customer must confirm in WhatsApp."
            ),
        },
        idempotency_key=f"modify-review:{order.id}:{change_count}:{abs(hash(summary_line)) % 65536}",
    )


async def _advance_modify_to_confirm(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    mod_id: int,
    proposed: list[dict],
) -> None:
    """Move to modify_confirm with summary, or offer full cancel when proposed is empty."""
    if not proposed:
        await _offer_full_cancel_from_empty_modify(
            session, conv, inbound, restaurant_id, mod_id,
        )
        return
    _set_state(conv, dialogue_state="modify_confirm", modify_proposed=proposed)
    try:
        from app.llm.complaint_agent import build_order_context_for_summarizer
        from app.llm.factory import get_modify_summarizer
        from app.llm.modify_agent import format_proposed_lines
        from app.ordering.models import Order

        _mod_order = await session.get(Order, mod_id)
        _order_ctx = await build_order_context_for_summarizer(session, _mod_order)
        _prop_text = format_proposed_lines(proposed)
        _chat = (inbound.payload.get("text") or "").strip()
        _mod_summary = await get_modify_summarizer().summarize(
            _order_ctx, _prop_text, _chat,
        )
        if _mod_summary:
            _set_state(conv, modify_summary=_mod_summary)
            await _notify_manager_modify_review(
                session, restaurant_id, mod_id, _mod_summary,
            )
    except Exception:  # noqa: BLE001
        _logger.exception(
            "modify summarizer failed for restaurant %s conv %s",
            restaurant_id, conv.id,
        )
    await _send_modify_summary(session, conv, inbound, restaurant_id, mod_id, proposed)


async def _apply_post_confirm_line_edit(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    action: str,
    data: dict,
) -> None:
    """Option B: post-confirm remove/set_qty via AI schema → pending confirm summary."""
    order = await _resolve_order_for_modify(session, conv, inbound, restaurant_id)
    if order is None or not _order_is_modifiable(order):
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="post-edit-blocked",
            body="That order can't be changed right now. Send 'hi' if you need help.",
        )
        return

    proposed = list(conv.state.get("modify_proposed", []) or [])
    if not proposed:
        proposed = await _proposed_from_order(session, order.id)

    label: str | None = None
    if action == "remove_item":
        dish_query = (data.get("dish_query") or "").strip()
        if not dish_query and data.get("items"):
            dish_query = str(data["items"][0].get("dish_query") or "").strip()
        proposed, label = await _modify_remove_from_proposed(
            session, restaurant_id, proposed, dish_query,
        )
    elif action == "update_qty":
        dish_query = (data.get("dish_query") or "").strip()
        qty = data.get("qty")
        if not dish_query and data.get("items"):
            it = data["items"][0]
            dish_query = str(it.get("dish_query") or "").strip()
            qty = it.get("qty") if qty is None else qty
        if dish_query and qty is not None:
            proposed, label = await _modify_update_qty_in_proposed(
                session, restaurant_id, proposed, dish_query, int(qty),
            )

    if label is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="post-edit-nomatch",
            body="I couldn't match that dish on your order. Try the exact name from your summary.",
        )
        return

    _set_state(
        conv,
        modify_order_id=order.id,
        modify_proposed=proposed,
        modify_proposed_initialized=True,
    )
    await _advance_modify_to_confirm(
        session, conv, inbound, restaurant_id, order.id, proposed,
    )


async def _handle_modify_intent(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Start modify flow: lookup recent modifiable order (conv.state pending/ modify_order_id or by phone like status query).
    If before ready, set modify_items + empty proposed; prompt for new items (SLA restart noted).
    """
    from app.ordering.models import OrderItem

    order = await _resolve_order_for_modify(session, conv, inbound, restaurant_id)

    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-no-order",
            body="You don't have any active orders to modify. Send 'hi' to place a new order.",
        )
        return

    if not _order_is_modifiable(order):
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-blocked",
            body=f"Order #{order.order_number} cannot be modified (status: {order.status}). Modifications allowed only before ready per spec.",
        )
        return

    seeded = await _proposed_from_order(session, order.id)
    _update_agent_notes(
        conv,
        modify_intent="active",
        pending_modify_order=str(order.order_number or order.id),
    )
    _set_state(
        conv,
        dialogue_state="modify_items",
        modify_order_id=order.id,
        modify_proposed=seeded,
        modify_proposed_initialized=True,
    )
    # Use a real dish from this order as the example so the hint is never a
    # dish the restaurant doesn't serve (multi-tenant: no hardcoded dish names).
    example_dish = await session.scalar(
        select(OrderItem.dish_name).where(OrderItem.order_id == order.id).limit(1)
    )
    example = f"'remove {example_dish}'" if example_dish else "the dish to change"
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="modify-start",
        body=(
            f"Sure, let's modify order #{order.order_number}. "
            f"Tell me what to change (e.g. {example}, 'only <dish>'), or 'done' when ready to review. "
            f"After you confirm, the 40-min SLA clock restarts."
        ),
    )


async def _try_post_order_item_edit(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> bool:
    """Deterministic post-confirm edits: 'cancel/remove <dish>' or 'only <dish>'.

    Starts (or continues) the modify FSM with the current order seeded as proposed,
    applies the edit immediately, and never misroutes to whole-order cancel or an
    empty modify loop."""
    if conv.state.get("dialogue_phase") != "post_order":
        return False
    if conv.state.get("dialogue_state") not in ("order_placed", "", "modify_confirm"):
        return False
    if inbound.type != MessageType.TEXT:
        return False

    text = (inbound.payload.get("text") or "").strip()
    keep_q = _parse_keep_only(text)
    remove_items = _parse_remove_items(text)
    _remove_ref = remove_items is None and _is_remove_reference(text)
    if not keep_q and remove_items is None and not _remove_ref:
        return False

    order = await _resolve_order_for_modify(session, conv, inbound, restaurant_id)
    if order is None:
        return False

    if not _order_is_modifiable(order):
        return False

    proposed = list(conv.state.get("modify_proposed", []) or [])
    if not proposed:
        proposed = await _proposed_from_order(session, order.id)
    # Nearest-context: bare "remove it" targets the most-recent line of the order.
    if _remove_ref and remove_items is None:
        _last_name = _recent_proposed_name(proposed)
        if not _last_name:
            return False
        remove_items = [(None, _last_name)]
    if keep_q:
        proposed, label = await _modify_keep_only_proposed(
            session, restaurant_id, proposed, keep_q,
        )
        if label is None:
            return False
    else:
        # Multi-item remove ("cancel biryani and 7up") — loop so every named dish comes
        # off, not just the first (matches the ordering-phase cart-edit path).
        removed_any = False
        for _rm_qty, rm_query in remove_items:
            proposed, label = await _modify_remove_from_proposed(
                session, restaurant_id, proposed, rm_query,
            )
            if label is not None:
                removed_any = True
        if not removed_any:
            return False

    _set_state(
        conv,
        modify_order_id=order.id,
        modify_proposed=proposed,
        modify_proposed_initialized=True,
    )
    await _advance_modify_to_confirm(
        session, conv, inbound, restaurant_id, order.id, proposed,
    )
    return True


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
    mod_id = conv.state.get("modify_order_id")
    proposed = list(conv.state.get("modify_proposed", []) or [])
    if not proposed and mod_id and not conv.state.get("modify_proposed_initialized"):
        proposed = await _proposed_from_order(session, mod_id)
        _set_state(conv, modify_proposed=proposed, modify_proposed_initialized=True)

    keep_q = _parse_keep_only(text)
    if keep_q:
        new_prop, kept = await _modify_keep_only_proposed(
            session, restaurant_id, proposed, keep_q,
        )
        if kept is not None:
            _set_state(conv, dialogue_state="modify_items", modify_proposed=new_prop)
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-keep-only",
                body=(
                    f"Got it — your order will have only {kept}.\n"
                    "Reply with more changes, or send 'done' to review (SLA restarts on confirm)."
                ),
            )
            return

    remove_items = _parse_remove_items(text)
    # Nearest-context: bare "remove it" targets the most-recent proposed line.
    if remove_items is None and _is_remove_reference(text):
        _last_name = _recent_proposed_name(proposed)
        if _last_name:
            remove_items = [(None, _last_name)]
    if remove_items is not None:
        # Multi-item remove ("remove biryani and 7up") — take off every named dish.
        new_prop = proposed
        removed_labels: list[str] = []
        for _rm_qty, rm_query in remove_items:
            new_prop, removed = await _modify_remove_from_proposed(
                session, restaurant_id, new_prop, rm_query,
            )
            if removed is not None:
                removed_labels.append(removed)
        if removed_labels:
            _set_state(conv, dialogue_state="modify_items", modify_proposed=new_prop)
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-removed",
                body=(
                    f"Removed {', '.join(removed_labels)} from your order.\n"
                    "Reply with more changes, or send 'done' to review (SLA restarts on confirm)."
                ),
            )
            return

    setq_items = _parse_set_quantity_items(text)
    if setq_items is not None:
        new_prop = proposed
        changed: list[str] = []
        for sqty, sdish in setq_items:
            if not sdish:
                # Nearest-context: bare "make it N" targets the most-recent proposed line.
                sdish = _recent_proposed_name(proposed) or ""
                if not sdish:
                    continue
            new_prop, name = await _modify_update_qty_in_proposed(
                session, restaurant_id, new_prop, sdish, sqty,
            )
            if name:
                changed.append(name)
        if changed:
            _set_state(conv, dialogue_state="modify_items", modify_proposed=new_prop)
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-qty",
                body=(
                    f"Updated {', '.join(changed)} ✅\n"
                    "Reply with more changes, or send 'done' to review (SLA restarts on confirm)."
                ),
            )
            return

    qty, dish_query = parse_qty_and_text(text)
    lower_q = dish_query.lower()

    from app.conversation.intent_rubric import is_completion_intent

    _mod_done = (
        not keep_q
        and remove_items is None
        and setq_items is None
        and (is_completion_intent(text) or _is_ack_proceed_intent(text))
    )
    if _mod_done:
        if not mod_id:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-no-proposed",
                body="No modification in progress. Send 'hi' to start a new order.",
            )
            return
        await _advance_modify_to_confirm(
            session, conv, inbound, restaurant_id, mod_id, proposed,
        )
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

    # Same guard as the ordering collector: a question/complaint/aside ("you do it
    # yourself") must not be parsed as a replacement dish or mined for a quantity.
    if _looks_like_order_question(text):
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-question-mod",
            body=("No problem — tell me the change as a dish and quantity (e.g. "
                  "'1 Chicken Biryani'), or 'remove <dish>', and I'll update it."),
        )
        return

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)

    if result.confidence == MatchConfidence.NO_MATCH:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="no-match-mod",
            body=_off_menu_decline(dish_query),
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
    entry = {
        "dish_id": dish.id,
        "dish_number": dish.dish_number,
        "name": dish.name,
        "price_aed": str(dish.price_aed),
        "qty": qty,
    }
    existing_idx = next(
        (i for i, p in enumerate(proposed) if p.get("dish_id") == dish.id),
        None,
    )
    if existing_idx is not None:
        proposed[existing_idx] = entry
        action = f"Updated to {qty}x {dish.name}"
    else:
        proposed.append(entry)
        action = f"Added {qty}x {dish.name}"
    _set_state(conv, dialogue_state="modify_items", modify_proposed=proposed)

    price = _aed(dish.price_aed)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="item-proposed",
        body=(
            f"{action} (AED {price}).\n"
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
        f"  {it.qty}x {it.dish_name}{_note_suffix(it)}: "
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

    differs = await _proposed_differs_from_order(session, order.id, proposed)
    if differs:
        body = (
            f"Order #{order.order_number} — your updated items:\n{prop_lines}\n\n"
            f"Was:\n{curr_lines}\n\n"
            f"Subtotal: AED {_aed(new_sub)}\n"
            f"Delivery: AED {_aed(order.delivery_fee_aed or 0)}\n"
            f"Total: AED {_aed(new_total)} (COD)\n\n"
            f"Confirm these changes? The 40-minute delivery window restarts after you confirm."
        )
    else:
        body = (
            f"Order #{order.order_number}:\n{prop_lines}\n\n"
            f"Subtotal: AED {_aed(new_sub)}\n"
            f"Delivery: AED {_aed(order.delivery_fee_aed or 0)}\n"
            f"Total: AED {_aed(new_total)} (COD)\n\n"
            f"No changes yet — tell me what to update, or tap Keep original."
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
    if (
        not btn_id
        and inbound.type == MessageType.TEXT
        and _is_ack_proceed_intent(inbound.payload.get("text") or "")
    ):
        btn_id = "confirm_modify"

    if btn_id == "cancel_order":
        proposed = conv.state.get("modify_proposed", []) or []
        if not proposed:
            _clear_modify_state(conv)
            _set_state(conv, dialogue_state="order_placed")
            await _execute_cancel_order(session, conv, inbound, restaurant_id)
            return

    if btn_id == "confirm_modify":
        proposed = conv.state.get("modify_proposed", []) or []
        if not proposed:
            await _offer_full_cancel_from_empty_modify(
                session, conv, inbound, restaurant_id, mod_id,
            )
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
            _clear_modify_state(conv)
            _set_state(conv, dialogue_state="order_placed")
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="modify-unavailable",
                body=("Those items are no longer available, so your order was not changed. "
                      f"Your original Order #{order.order_number} still stands."),
            )
            return

        await modify_order(session, order=order, new_items=new_items, actor="customer")
        # commit by caller (webhook/router)

        _clear_modify_state(conv)
        _set_state(conv, dialogue_state="order_placed")
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
        _clear_modify_state(conv)
        _set_state(conv, dialogue_state="order_placed")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-cancelled",
            body="Modification cancelled. Original order unchanged. Send 'hi' if needed.",
        )
        return

    # re-prompt
    proposed = conv.state.get("modify_proposed", []) or []
    await _send_modify_summary(session, conv, inbound, restaurant_id, mod_id, proposed)


async def _handle_cancel_during_modify(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Cancel the order from inside the modify flow, so a 'Cancel order' tap (or a
    'cancel' message) is honoured instead of being read as a dish — the customer is
    never trapped in modify_items with no way out.

    Always exits the modify flow first. Then cancels the underlying order when the
    FSM still allows it (draft / pre-ready); if it's already too far along, it keeps
    the order but still drops the customer out of the modify loop.
    """
    from app.ordering.fsm import IllegalTransitionError
    from app.ordering.models import Order
    from app.ordering.service import cancel_order

    oid = conv.state.get("modify_order_id") or conv.state.get("pending_order_id")
    order = await session.get(Order, oid) if oid else None
    # Drop out of the modify flow no matter what (the trap is the bug we're fixing).
    _clear_modify_state(conv)

    if order is None:
        _set_state(conv, dialogue_state="cancelled",
                   draft_order_id=None, pending_order_id=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-cancel-noorder",
            body="No problem — there's nothing to cancel. Send 'hi' to start a new order.",
        )
        return

    try:
        await cancel_order(session, order=order, actor="customer", reason="customer_cancel")
    except IllegalTransitionError:
        _set_state(conv, dialogue_state="order_placed")
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="modify-cancel-blocked",
            body=(f"Order #{order.order_number} can't be cancelled now, but I've stopped "
                  "the changes. Please call the restaurant if you need help."),
        )
        return

    _set_state(conv, dialogue_state="cancelled",
               draft_order_id=None, pending_order_id=None)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="modify-cancelled-order",
        body=_cancel_confirmation_body(order.order_number),
    )


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
    # E-10: focused sub-agent distills issue + suggested_action for staff handoff.
    summary: dict = {}
    evidence: list[dict] = []
    category: str | None = None
    try:
        from app.llm.complaint_agent import (
            build_chat_snippet_for_summarizer,
            build_order_context_for_summarizer,
            category_from_summary,
        )
        from app.llm.factory import get_complaint_summarizer

        order_context = await build_order_context_for_summarizer(session, latest_order)
        chat_snippet = text or await build_chat_snippet_for_summarizer(session, conv)
        summary = await get_complaint_summarizer().summarize(order_context, chat_snippet)
        if summary:
            evidence.append({"kind": "ai_summary", **summary})
            category = category_from_summary(summary)
    except Exception:  # noqa: BLE001
        _logger.exception(
            "complaint summarizer failed for restaurant %s conv %s",
            restaurant_id, conv.id,
        )

    ticket = await create_ticket(
        session,
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        order_id=latest_order.id if latest_order else None,
        source_message=text or None,
        evidence=evidence or None,
        category=category,
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
        issue_line = (summary.get("issue") or text[:160]) if summary else text[:160]
        action_hint = summary.get("suggested_action", "")
        mgr_tail = f" Suggested: {action_hint}." if action_hint else ""
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=restaurant.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={
                "body": f"⚠️ New complaint ticket #{ticket.id} (order {order_ref}) "
                        f"from {customer.phone}: \"{issue_line}\".{mgr_tail} "
                        "Open the dashboard to resolve."
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
        f"{f' ({it.variant_name})' if it.variant_name else ''}"
        f"{_note_suffix(it)} "
        f"(AED {_aed(it.price_aed * it.qty)})"
        for it in items
    ]
    return ", ".join(lines) + f" | Subtotal: AED {_aed(order.subtotal)}"


async def _contextual_error_body(session: AsyncSession, conv) -> str:
    """Fallback text for a crashed AI/dispatch turn.

    Context-aware on purpose: a bare "Type the dish name or send 'hi'" throws away
    everything the customer already did and reads as the bot looping the same reply.
    When there's a live cart we echo it and offer the next step (confirm / add more)
    so a transient LLM hiccup doesn't strand a full basket.
    """
    cart = await _build_cart_summary(session, conv)
    if cart:
        return (
            "Sorry, I had a brief hiccup 😅\n\n"
            f"🛒 {cart}\n\n"
            "Reply *confirm* to place your order, or tell me another dish to add."
        )
    return "Sorry, having a moment 😅 Type the dish name to order, or send 'hi' to start."


def _cart_tail(cart: str) -> str:
    """Trailing cart line for edit confirmations so the customer always sees the
    current cart right after a remove / quantity change."""
    return f"\n\n🛒 {cart}" if cart else "\n\n🛒 Your cart is now empty."


_MENU_SPECIAL_PHRASES: tuple[str, ...] = (
    "chef special", "chef's special", "restaurant special", "house special",
    "today's special", "todays special",
)
_UPSELL_VOLUME_DAYS = 30


def _text_signals_menu_special(*, category: str | None, name: str, description: str | None) -> bool:
    cat = (category or "").lower()
    if "special" in cat or "specials" in cat:
        return True
    blob = f"{name} {description or ''}".lower()
    return any(p in blob for p in _MENU_SPECIAL_PHRASES)


async def _cart_dish_ids(session: AsyncSession, order_id: int) -> set[int]:
    from app.ordering.models import OrderItem

    return {
        did
        for (did,) in (
            await session.execute(
                select(OrderItem.dish_id).where(OrderItem.order_id == order_id)
            )
        ).all()
    }


async def _top_seller_candidates(
    session: AsyncSession,
    restaurant_id: int,
    *,
    limit: int = 10,
):
    from datetime import datetime, timedelta, timezone

    from app.ordering.models import Order, OrderItem

    since = (datetime.now(timezone.utc) - timedelta(days=_UPSELL_VOLUME_DAYS)).replace(
        tzinfo=None
    )
    return (
        await session.execute(
            select(OrderItem.dish_id, func.sum(OrderItem.qty).label("units"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.status.notin_(("draft", "cancelled")),
                Order.created_at >= since,
                OrderItem.dish_id.isnot(None),
            )
            .group_by(OrderItem.dish_id)
            .order_by(func.sum(OrderItem.qty).desc())
            .limit(limit)
        )
    ).all()


async def _menu_special_dish(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order,
):
    """First available dish flagged as a menu special, not already in cart."""
    from app.menu.models import Dish, Menu

    in_cart = await _cart_dish_ids(session, order.id)
    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
    if menu is None:
        return None
    dishes = (
        await session.scalars(
            select(Dish).where(
                Dish.menu_id == menu.id,
                Dish.is_available == True,  # noqa: E712
                Dish.meta_status == "active",
            ).order_by(Dish.category, Dish.name)
        )
    ).all()
    for dish in dishes:
        if dish.id in in_cart:
            continue
        if not getattr(dish, "whatsapp_enabled", True):
            continue
        if _SLUG_NAME.match(dish.name or ""):
            continue
        if not _text_signals_menu_special(
            category=dish.category, name=dish.name, description=dish.description
        ):
            continue
        if await _catalog_excludes_dish(session, restaurant_id, dish):
            continue
        return dish
    return None


async def _top_seller_dish(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order, *, limit: int = 10,
):
    from app.menu.models import Dish

    in_cart = await _cart_dish_ids(session, order.id)
    rows = await _top_seller_candidates(session, restaurant_id, limit=limit)
    for dish_id, _units in rows:
        if dish_id in in_cart:
            continue
        dish = await session.get(Dish, dish_id)
        if dish is None or not dish.is_available:
            continue
        if not getattr(dish, "whatsapp_enabled", True):
            continue
        if _SLUG_NAME.match(dish.name or ""):
            continue
        if await _catalog_excludes_dish(session, restaurant_id, dish):
            continue
        return dish
    return None


async def _history_upsell_dish(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order,
):
    """The customer's most-ordered PAST dish that isn't in the current cart.

    Grounded strictly in the DB (real dish, real price — spec R-003/R-005: never
    invent): available today, orderable on WhatsApp, catalogue-allowed. Tier-1 of
    ``_upsell_dish_for_cart``; ``upsell_shown_for`` is set by the resolver."""
    try:
        from app.menu.models import Dish
        from app.ordering.models import Customer, Order, OrderItem

        customer = await session.scalar(
            select(Customer).where(
                Customer.restaurant_id == restaurant_id,
                Customer.phone == conv.phone,
            )
        )
        if customer is None:
            return None

        past_rows = (
            await session.execute(
                select(OrderItem.dish_id, func.sum(OrderItem.qty).label("units"))
                .join(Order, Order.id == OrderItem.order_id)
                .where(
                    Order.restaurant_id == restaurant_id,
                    Order.customer_id == customer.id,
                    Order.id != order.id,
                    Order.status.notin_(("draft", "cancelled")),
                    OrderItem.dish_id.isnot(None),
                )
                .group_by(OrderItem.dish_id)
                .order_by(func.sum(OrderItem.qty).desc())
                .limit(5)
            )
        ).all()
        if not past_rows:
            return None

        in_cart = await _cart_dish_ids(session, order.id)

        for dish_id, _units in past_rows:
            if dish_id in in_cart:
                continue
            dish = await session.get(Dish, dish_id)
            if (
                dish is None
                or not dish.is_available
                or not getattr(dish, "whatsapp_enabled", True)
                or _SLUG_NAME.match(dish.name or "")
            ):
                continue
            if await _catalog_excludes_dish(session, restaurant_id, dish):
                continue
            return dish
        return None
    except Exception:  # noqa: BLE001 — an upsell must never break an add
        _logger.debug("history upsell skipped", exc_info=True)
        return None


async def _upsell_dish_for_cart(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order,
) -> tuple[object | None, str]:
    if conv.state.get("upsell_shown_for") == order.id:
        return None, "none"
    try:
        dish = await _history_upsell_dish(session, conv, restaurant_id, order)
        if dish is not None:
            _set_state(conv, upsell_shown_for=order.id)
            return dish, "history"
        dish = await _menu_special_dish(session, conv, restaurant_id, order)
        if dish is not None:
            _set_state(conv, upsell_shown_for=order.id)
            return dish, "menu_special"
        dish = await _top_seller_dish(session, conv, restaurant_id, order)
        if dish is not None:
            _set_state(conv, upsell_shown_for=order.id)
            return dish, "top_seller"
    except Exception:  # noqa: BLE001
        _logger.debug("upsell resolver failed", exc_info=True)
    return None, "none"


async def _history_upsell_line(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order,
) -> str:
    """One-line history upsell for plain-text add confirmations ("" when none)."""
    dish, source = await _upsell_dish_for_cart(session, conv, restaurant_id, order)
    if dish is None or source != "history":
        return ""
    return (
        f"\n\nYou had {dish.name} (AED {_aed(dish.price_aed)}) last time. "
        "Add one? 😊"
    )


async def _execute_upsell_add(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    dish_id: int,
) -> bool:
    """Add one unit of *dish_id* to the live cart and re-show quick-action buttons."""
    from app.menu.models import Dish as _UpsellDish
    from app.ordering.service import add_item

    _udish = await session.get(_UpsellDish, dish_id)
    if (
        _udish is None
        or _udish.restaurant_id != restaurant_id
        or not _udish.is_available
    ):
        return False
    _uorder = await _ensure_draft_order(session, conv, inbound, restaurant_id)
    await add_item(session, order=_uorder, dish=_udish, qty=1)
    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
    await _record_cart_observation(session, conv)
    cart = await _build_cart_summary(session, conv)
    upsell, buttons = await _post_add_extras(session, conv, restaurant_id, _uorder)
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="upsell-added",
        body=f"Added 1x {_udish.name} ✅{_cart_tail(cart)}{upsell}",
        buttons=buttons,
    )
    return True


async def _post_add_extras(
    session: AsyncSession, conv: Conversation, restaurant_id: int, order,
) -> tuple[str, list[dict]]:
    """(upsell_body_line, buttons) for every added-to-cart confirmation.

    Buttons (WhatsApp max 3, titles ≤ 20 chars):
      1. Proceed to delivery  — same as typing 'done'
      2. Add <upsell dish>    — or 'Suggestions' when no grounded pick
      3. Clear cart
    """
    upsell_line = ""
    dish, source = await _upsell_dish_for_cart(session, conv, restaurant_id, order)
    if dish is not None:
        if source == "history":
            upsell_line = (
                f"\n\nYou had {dish.name} (AED {_aed(dish.price_aed)}) last time. "
                "Add one? 😊"
            )
        else:
            upsell_line = (
                f"\n\nTry {dish.name} (AED {_aed(dish.price_aed)})? Add one? 😊"
            )
        title = f"Add {dish.name}"
        if len(title) > 20:
            title = title[:20]
        upsell_btn = {"id": f"upsell_add:{dish.id}", "title": title}
    else:
        upsell_btn = {"id": "suggest_dishes", "title": "Suggestions"}
    buttons = [
        {"id": "proceed_delivery", "title": "Proceed to delivery"},
        upsell_btn,
        {"id": "clear_cart", "title": "Clear cart"},
    ]
    return upsell_line, buttons


async def _send_cart_confirmation(
    session: AsyncSession,
    *,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    prefix: str,
    body: str,
    cart: str,
) -> None:
    """Every cart-mutation confirmation (add/remove/swap/qty-change/note) must
    carry the same quick-action buttons — proceed/upsell/clear — whenever the
    cart still has items, not just the original add sites. Falls back to plain
    text when the mutation left the cart empty (nothing to act on).

    Root-cause fix: several mutation replies (remove, swap, qty update,
    catalogue set-qty/note) used to call ``_send_text`` directly, leaving the
    customer with no tap target — they'd fall back to typing free text like
    'Cancel', which can collide with the marketing opt-out keyword (prod
    regression). Route every cart-mutation reply through here instead."""
    order = None
    if cart and (_ccid := conv.state.get("draft_order_id")):
        from app.ordering.models import Order as _CartConfirmOrder

        order = await session.get(_CartConfirmOrder, _ccid)
    if order is not None:
        upsell, buttons = await _post_add_extras(session, conv, restaurant_id, order)
        await _send_buttons(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix=prefix, body=f"{body}{upsell}", buttons=buttons,
        )
    else:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix=prefix, body=body,
        )


async def _record_cart_observation(
    session: AsyncSession, conv: Conversation
) -> None:
    """Record a compact DB-derived cart observation into message history after any
    mutation, so the next turn's _build_history carries ground truth (F66/W3).

    This is history-only bookkeeping (never sent to the customer): it anchors the
    LLM's next turn to the REAL cart, so the model can't drift onto a stale cart it
    imagined earlier in the conversation.
    """
    cart = await _build_cart_summary(session, conv)
    if not cart:
        return
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="cart_observation",
        payload={"text": f"[Cart updated] {cart}"},
    )


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
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int,
    draft_order_id: int | None = None,
) -> None:
    """Returning customer still has an in-progress cart → show it and ask whether to
    continue it or start a new order, instead of silently wiping or appending.

    TX-02/R-DB-15: ``draft_order_id`` is re-pinned into ``conv.state`` here (not
    merely left as-is) so a reordered/replayed webhook or a fresh session load
    can never process the NEXT turn ("Continue order" → "that's all") against a
    stale/missing pointer and read the cart as empty.
    """
    cart = await _build_cart_summary(session, conv)
    _set_state(
        conv, dialogue_phase="ordering", dialogue_state="resume_offer",
        **({"draft_order_id": draft_order_id} if draft_order_id is not None else {}),
    )
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


def _history_limit_for_phase(phase: str) -> int:
    """E-01: per-phase history window — smaller post-order / address slices."""
    from app.config import get_settings

    s = get_settings()
    if phase == "post_order":
        return s.conversation_history_limit_post_order
    if phase == "address_capture":
        return s.conversation_history_limit_address
    if phase == "ordering":
        return s.conversation_history_limit_ordering
    return s.conversation_history_limit


def _update_agent_notes(conv: Conversation, **kwargs) -> None:
    """E-05: persist compact session notes outside the history window."""
    notes = dict(conv.state.get("agent_notes") or {})
    for key, value in kwargs.items():
        if value is None:
            notes.pop(key, None)
        else:
            notes[key] = value
    _set_state(conv, agent_notes=notes or None)


def _render_session_notes(agent_notes: dict | None) -> str:
    """E-05: render a 2–3 line session_notes block for the system prompt."""
    if not agent_notes:
        return ""
    preferred = (
        ("last_confirmed_order", "Last confirmed order"),
        ("modify_intent", "Modify intent"),
        ("pending_modify_order", "Pending modify order"),
    )
    lines: list[str] = []
    for key, label in preferred:
        val = agent_notes.get(key)
        if val:
            lines.append(f"- {label}: {val}")
    if not lines:
        for key, val in list(agent_notes.items())[:3]:
            if val:
                lines.append(f"- {key}: {val}")
    if not lines:
        return ""
    return "## Session notes\n" + "\n".join(lines[:3])


def _apply_history_source_prefix(msg, content: str) -> str:
    """E-06: prefix history rows with source/direction metadata."""
    if not content:
        return content
    if msg.type in ("order", "product_list"):
        tag = "[catalog]"
    elif msg.direction == "inbound":
        tag = "[customer]"
    else:
        tag = "[assistant]"
    if content.startswith(tag):
        return content
    return f"{tag} {content}"


_CART_DUP_MARKERS = ("🛒", "[Cart updated]")


async def _menu_dish_count(session: AsyncSession, restaurant_id: int) -> int:
    """Count active WhatsApp-sendable dishes for JIT menu context (E-03)."""
    from app.identity.models import Restaurant, catalog_mode_enabled
    from app.menu.models import Dish, Menu

    _rest = await session.get(Restaurant, restaurant_id)
    if _rest is not None and catalog_mode_enabled(_rest.settings):
        from app.catalog.service import _load_sendable_products

        _cid, sendable = await _load_sendable_products(session, restaurant_id)
        return len(sendable) if sendable else 0

    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if menu is None:
        return 0
    dishes = (
        await session.scalars(
            select(Dish).where(
                Dish.menu_id == menu.id,
                Dish.is_available == True,  # noqa: E712
                Dish.meta_status == "active",
                Dish.whatsapp_enabled == True,  # noqa: E712
            )
        )
    ).all()
    return sum(1 for d in dishes if not _SLUG_NAME.match(d.name or ""))


async def _apply_tot_lite_branch(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant,
    *,
    text: str,
    phase: str,
) -> bool:
    """E-17: execute winning ToT-lite interpretation (checkout / add / question)."""
    from app.ordering.models import Order as _Ord_amb

    _did = conv.state.get("draft_order_id")
    _order = await session.get(_Ord_amb, _did) if _did else None
    _cart_ok = (
        _order is not None
        and str(_order.status) == "draft"
        and await _order_has_items(session, _order.id)
    )
    from app.llm.factory import get_thought_evaluator

    winner = await get_thought_evaluator().evaluate(
        text, phase, cart_nonempty=_cart_ok,
    )
    if winner == "checkout" and _cart_ok:
        await _handle_done_checkout(
            session, conv, inbound, restaurant_id, restaurant=restaurant,
        )
        return True

    if winner == "add" and phase == "ordering":
        if await _try_catalog_typed_order(
            session, conv, inbound, restaurant_id, restaurant,
        ):
            return True
        _set_state(conv, menu_in_context=True)
        await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
        return True

    if winner == "question":
        if phase == "ordering" and not _is_menu_request(text):
            _info_name = _dish_info_question(text)
            if _info_name:
                _info_reply = await _answer_dish_info(session, restaurant_id, _info_name)
                if _info_reply:
                    await _send_text(
                        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                        prefix="dish-info-tot", body=_info_reply,
                    )
                    return True
        await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
        return True

    return False


async def _maybe_clarify_vague_inbound(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    router_intent=None,
) -> bool:
    """E-21: short vague messages with no dish match → one clarifying question."""
    from app.llm.port import IntentLabel

    if inbound.type != MessageType.TEXT:
        return False
    if _resolve_phase(conv) != "ordering":
        return False
    # Per E-21 spec: only when the router could not classify the turn.
    if router_intent is not None and router_intent != IntentLabel.UNKNOWN:
        return False
    text = (inbound.payload.get("text") or "").strip()
    if _is_done_intent(text) or _is_checkout_shortcut(text) or _is_checkout_intent(text):
        return False
    if any(ch.isdigit() for ch in text):
        return False
    if len(text.split()) >= 4:
        return False
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=text)
    if result.confidence != MatchConfidence.NO_MATCH:
        return False
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="vague-clarify",
        body="Could you tell me the dish name and quantity?",
    )
    return True


def _render_history_content(msg) -> str:
    """Render one stored Message into LLM-readable content. Covers every
    Message.type so nothing falls through to an opaque '[type]' (R-078/82/84,
    DB-H8/12/13). Body is normalised to the delivered WhatsApp form (DB-H2)."""
    from app.outbox.service import to_whatsapp_text

    payload = msg.payload or {}
    mtype = msg.type

    if mtype == "cart_observation":
        text = payload.get("text") or payload.get("body") or ""
        return to_whatsapp_text(text) if text else ""

    if mtype == "order":
        # Catalogue basket → readable basket from the snapshot persisted at record
        # time (R-077/F63). Fall back to product_items count if older row.
        dt = (payload.get("display_text") or "").strip()
        if dt:
            return f"[sent catalogue basket: {dt}]"
        snap = payload.get("cart_snapshot") or []
        if snap:
            parts = [f"{line.get('qty', 1)}x {line.get('dish', 'item')}" for line in snap]
            return f"[sent catalogue basket: {'; '.join(parts)}]"
        n = len(payload.get("product_items") or [])
        return f"[sent catalogue basket: {n} item(s)]"

    if mtype in ("text", "audio"):
        # Voice notes (type "audio") carry their transcript under "text".
        text = payload.get("text") or payload.get("body") or ""
        return to_whatsapp_text(text) if text else ""

    if mtype == "location":
        lat = payload.get("latitude", "")
        lng = payload.get("longitude", "")
        return f"[customer shared location pin: {lat},{lng}]"

    if mtype == "button_reply":
        title = payload.get("title") or payload.get("id") or "button"
        bid = payload.get("id")
        return f"[tapped: {title}" + (f" ({bid})]" if bid else "]")

    if mtype == "list_reply":
        title = payload.get("title") or payload.get("id") or "item"
        return f"[selected: {title}]"

    if mtype == "buttons":
        # E-22: body alone — drop verbose option lists when the body was already sent.
        body = to_whatsapp_text(payload.get("body") or "")
        return body.strip() or "[buttons sent]"

    if mtype in ("cta_url", "location_request"):
        body = to_whatsapp_text(payload.get("body") or "")
        label = payload.get("button_label")
        return (body + (f" [button: {label}]" if label else "")).strip() or f"[{mtype}]"

    if mtype == "product_list":
        return "[sent menu / product cards]"

    if mtype == "system_summary":
        summary = (payload.get("summary") or "").strip()
        return summary or "[system_summary]"

    # Any other type still gets its best human text, never a bare placeholder.
    text = payload.get("text") or payload.get("body") or payload.get("caption")
    return to_whatsapp_text(text) if text else f"[{mtype}]"


async def _build_history(
    session: AsyncSession,
    conv: Conversation,
    limit: int | None = None,
    dialogue_phase: str | None = None,
) -> list[dict]:
    """Single source of truth for LLM conversation history.

    Fetches the last `limit` rows ordered by (created_at, id) — this ordering is
    deliberately UNCHANGED from before W7a (verified against the full voice/
    conversation regression suite before landing; do not switch to `Message.ts`
    without re-verifying every test) — renders every Message.type via
    `_render_history_content`, merges consecutive same-role turns (R-079), and
    uses a configurable window (R-080/F55). Returns OpenAI-style
    [{role, content}].
    """
    from app.conversation.compaction import maybe_compact_history
    from app.conversation.models import Message

    await maybe_compact_history(session, conv)

    if limit is None:
        phase = dialogue_phase or _resolve_phase(conv)
        limit = _history_limit_for_phase(phase)

    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    ).all()
    rows = list(reversed(rows))  # oldest first

    # Session freshness: if the customer returns after a long silence, drop everything
    # before that gap so yesterday's chat can't colour a fresh order (the draft cart has
    # its own separate expiry). Keep only the trailing run whose consecutive gaps are all
    # under the threshold — the current session. 0 disables.
    from app.config import get_settings as _get_settings_gap

    _gap_min = _get_settings_gap().conversation_session_gap_minutes
    if _gap_min and len(rows) > 1:
        from datetime import timedelta, timezone

        _gap = timedelta(minutes=_gap_min)
        _cut = 0
        for _i in range(len(rows) - 1, 0, -1):
            _older, _newer = rows[_i - 1].created_at, rows[_i].created_at
            if _older is not None and _newer is not None:
                _a = _older if _older.tzinfo else _older.replace(tzinfo=timezone.utc)
                _b = _newer if _newer.tzinfo else _newer.replace(tzinfo=timezone.utc)
                if (_b - _a) > _gap:
                    _cut = _i  # most recent session starts here
                    break
        if _cut:
            rows = rows[_cut:]

    latest_cart_obs_idx = max(
        (i for i, msg in enumerate(rows) if msg.type == "cart_observation"),
        default=None,
    )

    raw: list[dict] = []
    for i, msg in enumerate(rows):
        content = _render_history_content(msg)
        if not content:
            continue
        if msg.type == "system_summary":
            raw.append({"role": "system", "content": content})
            continue
        role = "user" if msg.direction == "inbound" else "assistant"
        # E-22: drop stale assistant cart echoes when a newer cart_observation exists.
        if (
            role == "assistant"
            and msg.type != "cart_observation"
            and latest_cart_obs_idx is not None
            and i < latest_cart_obs_idx
            and any(marker in content for marker in _CART_DUP_MARKERS)
        ):
            continue
        content = _apply_history_source_prefix(msg, content)
        raw.append({"role": role, "content": content})

    # Merge consecutive same-role turns so the model never sees user,user,user
    # (R-079) — rapid mixed inbound types (order + text + audio) collapse to one.
    history: list[dict] = []
    for item in raw:
        if history and history[-1]["role"] == item["role"]:
            history[-1]["content"] += "\n" + item["content"]
        else:
            history.append({"role": item["role"], "content": item["content"]})

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
# Menu/catalog keyword sends must not hijack mid-checkout (address or confirm summary).
_MENU_REQUEST_BLOCKED_PHASES = frozenset({"address_capture", "awaiting_confirmation"})

# Single source of truth: derived from action_schema.LEGACY_PHASE_ACTIONS (W1) so
# engine phase-guard and provider tool schemas can never drift.
# Delta from old hand-written literal:
#   ordering: +add_item/update_qty/remove_item (superset; schema-correct).
#             status_query preserved explicitly — ACTION_SPECS scopes it to
#             post_order only, but allowing it here prevents a wrong-phase guard
#             no-op when a customer asks about a past order mid-ordering session.
#   awaiting_confirmation: +add_item/update_qty/remove_item (superset; these are
#             intercepted before the guard by the confirmation-edit special case).
_PHASE_ACTIONS: dict[str, frozenset] = {
    phase: actions | ({"status_query"} if phase == "ordering" else frozenset())
    for phase, actions in LEGACY_PHASE_ACTIONS.items()
}


def _resolve_phase(conv: Conversation) -> str:
    """Return the current dialogue_phase, mapping legacy dialogue_state if needed."""
    state = conv.state or {}
    if "dialogue_phase" in state and state["dialogue_phase"] in _VALID_PHASES:
        return state["dialogue_phase"]
    old_state = state.get("dialogue_state", "greeting")
    return _PHASE_MAP.get(old_state, "ordering")


def _menu_catalog_intercept_allowed(conv: Conversation) -> bool:
    """True when a menu/catalog keyword may replace the current checkout step."""
    return _resolve_phase(conv) not in _MENU_REQUEST_BLOCKED_PHASES


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
    ctx: dict = {
        "restaurant_name": (restaurant.name if restaurant else None) or "Restaurant",
    }

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

    session_notes = _render_session_notes(conv.state.get("agent_notes"))
    if session_notes:
        ctx["session_notes"] = session_notes

    if phase == "ordering":
        dish_count = await _menu_dish_count(session, restaurant_id)
        ctx["menu_dish_count"] = dish_count
        if conv.state.get("menu_in_context"):
            ctx["menu_text"] = await _render_menu(session, restaurant_id)
            _set_state(conv, menu_in_context=False)
        else:
            ctx["menu_text"] = (
                "Menu available on request — use menu_show action or dish_query for adds. "
                f"{dish_count} active dishes."
            )
        ctx["cart_summary"] = await _build_cart_summary(session, conv)

        from app.ordering.cart_service import CartService
        from app.ordering.models import Order as _Order

        _draft_oid = conv.state.get("draft_order_id")
        _draft_order = await session.get(_Order, _draft_oid) if _draft_oid else None
        if _draft_order is not None and str(_draft_order.status) == "draft":
            _svc = CartService(session)
            _lines = await _svc.build_structured_context(_draft_order)
            ctx["cart_lines"] = [
                {
                    "cart_item_id": ln.cart_item_id,
                    "dish_id": ln.dish_id,
                    "dish_name": ln.dish_name,
                    "variant_name": ln.variant_name,
                    "notes": ln.notes,
                    "qty": ln.qty,
                    "price_aed": str(ln.price_aed),
                }
                for ln in _lines
            ]
        else:
            ctx["cart_lines"] = []

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
                f"  {it.qty}x {it.dish_number}. {it.dish_name}{_note_suffix(it)}: "
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
            pin_lat=None, pin_lon=None, distance_km=None, distance_source=None, delivery_fee=None,
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
    upsell, buttons = await _post_add_extras(session, conv, restaurant_id, order)
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="bundle-applied", body=f"Added {label} ✅{_cart_tail(cart)}{upsell}",
        buttons=buttons,
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
    upsell, buttons = await _post_add_extras(session, conv, restaurant_id, order)
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="size-applied",
        body=f"Added {qty}x {dish.name} ({variant['name']}) ✅{_cart_tail(cart)}{upsell}",
        buttons=buttons,
    )
    return True


async def _offer_unavailable_alternative(
    session: AsyncSession, conv, inbound: InboundMessage, restaurant_id: int, dish_query: str
) -> bool:
    """If ``dish_query`` is a real dish that's just turned OFF today, tell the customer
    it's unavailable and suggest an available alternative (same category if possible).
    Returns True if it sent such a message, False if the dish genuinely isn't on the menu
    (so the caller falls back to the off-menu decline). Catalogue mode: only suggest an
    alternative that's actually orderable from the catalogue."""
    from app.ordering.matching import find_unavailable_match, suggest_available_alternative

    off = await find_unavailable_match(session, restaurant_id, dish_query)
    if off is None:
        return False
    alt = await suggest_available_alternative(
        session, restaurant_id, category=off.category, exclude_id=off.id
    )
    if alt is not None and await _catalog_excludes_dish(session, restaurant_id, alt):
        alt = None  # don't suggest a dish the customer can't actually order
    if alt is not None:
        body = (
            f"Sorry, {off.name} is sold out today 🙏 "
            f"Can I get you {alt.name} (AED {_aed(alt.price_aed)}) instead, "
            "or say 'menu' to see what's available? 😊"
        )
    else:
        body = (
            f"Sorry, {off.name} is sold out today 🙏 "
            "Say 'menu' to see what we have available right now 😊"
        )
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="dish-unavailable", body=body,
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
        if special_note and await _apply_note_to_existing_cart_item(
            session,
            conv,
            dish_id=-1,
            notes=special_note,
            dish_query=dish_query,
        ):
            return "updated_note"
        # Distinguish "we have it but it's off today" from "we don't have it at all".
        # The matcher only searches AVAILABLE dishes, so a real dish the manager turned
        # off (e.g. Chicken Biryani sold out today) lands here. Tell the customer it's
        # unavailable today and offer an available alternative, instead of the misleading
        # "we don't have that".
        handled = await _offer_unavailable_alternative(
            session, conv, inbound, restaurant_id, dish_query
        )
        return "unavailable" if handled else "no_match"
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

    if special_note and variant is None and await _apply_note_to_existing_cart_item(
        session, conv, dish_id=dish.id, notes=special_note, dish_query=dish_query,
    ):
        return "updated_note"

    await _add_dish_to_cart(
        session, conv, inbound, restaurant_id,
        dish=dish, qty=qty, notes=special_note or None, variant=variant,
    )
    return "added"


async def _apply_note_to_existing_cart_item(
    session: AsyncSession,
    conv: Conversation,
    *,
    dish_id: int,
    notes: str,
    qty: int | None = None,
    dish_query: str | None = None,
) -> bool:
    """Apply a kitchen note to an existing cart dish instead of charging for a
    duplicate line. Returns True when an existing cart line was updated."""
    from app.ordering.models import Order
    from app.ordering.service import set_item_note

    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None or str(order.status) != "draft":
        return False
    if dish_id >= 0:
        updated = await set_item_note(session, order=order, dish_id=dish_id, notes=notes, qty=qty)
        if updated is not None:
            return True
    if dish_query:
        alt_id = await _resolve_in_cart_dish_id(session, order.id, dish_query)
        if alt_id is not None:
            updated = await set_item_note(
                session, order=order, dish_id=alt_id, notes=notes, qty=qty,
            )
            return updated is not None
    return False


async def _try_apply_kitchen_note_to_cart(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> bool:
    """Deterministic path: dish-in-cart + prep modifiers → set kitchen note, no menu dump."""
    from app.ordering.cart_service import CartService, normalize_note
    from app.ordering.models import Order
    from app.ordering.service import parse_qty_and_text

    if inbound.type != MessageType.TEXT:
        return False
    text = (inbound.payload.get("text") or "").strip()
    if not text or "?" in text or _is_menu_request(text.lower()):
        return False
    # Quantity corrections ("only 1 biryani with …") must reach update_qty, not note-only.
    if _re.search(r"\b(?:only|just)\s+\d+\b", text, _re.IGNORECASE) or _re.search(
        r"\b(?:only|just)\s+(?:one|two|three|four|five|six|seven|eight|nine|ten)\b",
        text,
        _re.IGNORECASE,
    ) or _re.match(r"^(\d+)\s*[xX]\s*\S", text) or _re.search(
        r"\b([1-9]|1[0-9]|20)\s+\D", text
    ):
        return False

    draft_order_id = conv.state.get("draft_order_id")
    order = await session.get(Order, draft_order_id) if draft_order_id else None
    if order is None or str(order.status) != "draft":
        return False
    if not await _order_has_items(session, order.id):
        return False

    dish_ref: str | None = None
    note: str | None = None
    with_match = _re.match(r"^(.+?)\s+with\s+(.+)$", text, _re.IGNORECASE)
    if with_match:
        dish_ref = with_match.group(1).strip()
        note = with_match.group(2).strip()
    else:
        qty, dish_query = parse_qty_and_text(text)
        words = dish_query.split()
        for cut in range(len(words), 0, -1):
            cand = " ".join(words[:cut])
            pref = await find_dish_matches(session, restaurant_id=restaurant_id, query=cand)
            if (pref.confidence == MatchConfidence.DIRECT and pref.candidates
                    and pref.candidates[0].name_normalized == normalize_name(cand)):
                dish_ref = cand
                note = (" ".join(words[cut:]).strip() or None)
                break
        if note is None and qty is None:
            note = text
            dish_ref = None

    if not note or not normalize_note(note):
        return False

    if await _text_is_exact_catalogue_dish(session, restaurant_id, note):
        return False

    dish_id = await _resolve_in_cart_dish_id(session, order.id, dish_ref)
    if dish_id is None:
        from app.ordering.models import OrderItem as _OI_fb

        _cart_lines = (
            await session.scalars(select(_OI_fb).where(_OI_fb.order_id == order.id))
        ).all()
        if len(_cart_lines) == 1:
            dish_id = _cart_lines[0].dish_id
        elif dish_ref:
            _best = max(
                _cart_lines,
                key=lambda it: sum(
                    1 for t in normalize_name(dish_ref).split()
                    if t in normalize_name(it.dish_name)
                ),
                default=None,
            )
            if _best is not None and _dish_ref_matches_cart_name(dish_ref, _best.dish_name):
                dish_id = _best.dish_id
    if dish_id is None:
        return False

    updated = await CartService(session).set_note(
        order=order, dish_id=dish_id, raw_note=note,
    )
    if updated is None:
        return False

    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
    cart = await _build_cart_summary(session, conv)
    await _record_cart_observation(session, conv)
    clean = normalize_note(note)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="kitchen-note",
        body=(
            f"Sorry about that! I've added 1 {updated.dish_name} with a note for "
            f"{clean}. I'll pass that to the kitchen and they'll do their best to "
            f"accommodate it 😊{_cart_tail(cart)}"
        ),
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
    from app.ordering.cart_service import CartService
    from app.ordering.models import Order, OrderItem

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
    _cs_rm = CartService(session)
    removed = await _cs_rm.remove(order=order, dish=dish, qty=to_remove)
    if removed <= 0:
        return ("not_in_cart", dish.name)
    return ("removed" if removed >= in_cart_units else "reduced", dish.name)


async def _try_negation_swap(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int,
) -> bool:
    """Handle "No give me <dish>" as a swap of the LAST cart line.

    Returns True when the swap was executed and a reply sent. The new dish is
    resolved BEFORE the cart is touched — an off-menu dish falls through (False)
    with the cart intact, and a failed add restores the removed line."""
    raw = (inbound.payload.get("text") or "").strip()
    t = _re.sub(r"[’'`]", "", raw.lower())
    t = _re.sub(r"\s+", " ", t).strip()
    m = _NEGATION_SWAP_RE.match(t)
    if not m:
        return False
    dish_q = m.group("rest").strip(" .!,?")
    if not dish_q or "?" in raw or _is_menu_request(dish_q) or _is_done_intent(dish_q):
        return False
    from app.ordering.service import parse_qty_and_text

    qty, rest = parse_qty_and_text(dish_q)
    dish_q = (rest or dish_q).strip()
    if not dish_q:
        return False

    from app.ordering.models import Order, OrderItem

    draft_id = conv.state.get("draft_order_id")
    if not draft_id:
        return False
    order = await session.get(Order, draft_id)
    if order is None or str(order.status) != "draft":
        return False
    last_item = await session.scalar(
        select(OrderItem)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id.desc())
        .limit(1)
    )
    if last_item is None:
        return False

    # Resolve the NEW dish first — never destroy the cart for an off-menu request.
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_q)
    if result.confidence == MatchConfidence.NO_MATCH or not result.candidates:
        return False
    cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
    if not cands:
        return False

    from app.menu.models import Dish

    old_dish = await session.get(Dish, last_item.dish_id)
    old_name = old_dish.name if old_dish else "the last item"
    old_qty = last_item.qty or 1
    swap_qty = qty if qty and qty > 1 else old_qty

    if old_dish is not None:
        await _execute_ai_remove_item(session, conv, restaurant_id, old_dish.name)
    status = await _execute_ai_add_item(
        session, conv, inbound, restaurant_id, dish_q, swap_qty, "",
        suppress_offers=True,
    )
    if status not in ("added", "updated_note"):
        # Add failed after the remove — restore the old line, never silently empty.
        if old_dish is not None:
            from app.ordering.cart_service import CartService

            await CartService(session).add(order=order, dish=old_dish, qty=old_qty)
        return False

    cart = await _build_cart_summary(session, conv)
    await _send_cart_confirmation(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="negation-swap",
        body=f"Sure! Swapped {old_name} for {cands[0].name} ✅{_cart_tail(cart)}",
        cart=cart,
    )
    return True


async def _execute_ai_update_qty(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage,
    restaurant_id: int, dish_query: str, qty: int, *, suppress_offers: bool = False,
    special_note: str = "",
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
    from app.ordering.cart_service import CartService
    from app.ordering.models import Order

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
    _cs_upd = CartService(session)
    if qty <= 0:
        await _cs_upd.set_qty(order=order, dish_id=dish.id, qty=0)
        return ("removed", dish.name)
    # W2/T7: route note through CartService.set_note so normalize_note strips politeness
    # prefixes ("pls", "please", etc.) before storing, and note survives qty changes.
    if special_note:
        result = await _cs_upd.set_note(
            order=order, dish_id=dish.id, raw_note=special_note, qty=qty
        )
        if result is not None:
            return ("updated", dish.name)

    # If the new quantity matches a bundle, ask before pricing it differently.
    bundle = bundle_variant_for_qty(dish, qty)
    if bundle is not None and not suppress_offers:
        await _offer_bundle_choice(
            session, conv, inbound, restaurant_id,
            dish=dish, qty=qty, notes=None, bundle=bundle,
        )
        return ("awaiting_bundle", dish.name)

    await _cs_upd.set_qty(order=order, dish_id=dish.id, qty=qty)
    return ("updated", dish.name)


async def _keep_only_dish(
    session: AsyncSession, conv: Conversation, restaurant_id: int, dish_query: str
) -> tuple[int | None, str | None]:
    """Prune the draft cart down to ONLY the dish matching ``dish_query`` ("only mandi").

    Removes every OTHER line (via set_item_qty(0) so totals recompute), keeping the named
    dish. Returns ``(removed_count, kept_name)``; ``(None, None)`` when there's no draft,
    the dish doesn't match, or it isn't in the cart (caller then treats it as an order)."""
    from app.ordering.models import Order, OrderItem
    from app.ordering.service import set_item_qty

    draft_order_id = conv.state.get("draft_order_id")
    if not draft_order_id or not dish_query:
        return (None, None)
    order = await session.get(Order, draft_order_id)
    if order is None or str(order.status) != "draft":
        return (None, None)
    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    if result.confidence == MatchConfidence.NO_MATCH or not result.candidates:
        return (None, None)
    cands = await _catalog_filter_candidates(session, restaurant_id, result.candidates)
    if not cands:
        return (None, None)
    target = await _resolve_cart_dish(session, order_id=order.id, candidates=cands[:5])
    if target is None:
        return (None, None)  # the "only" dish isn't in the cart → not a keep-only
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    other_dish_ids = {it.dish_id for it in items if it.dish_id != target.id}
    for other_id in other_dish_ids:
        await set_item_qty(session, order=order, dish_id=other_id, qty=0)
    return (len(other_dish_ids), target.name)


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
        # SET-quantity at confirm ("make it 5 soup") must REPLACE qty, not add — the
        # ordering-phase guard in _dispatch_action never runs here because confirm edits
        # short-circuit earlier.
        _raw = inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""
        _setq_items = _parse_set_quantity_items(_raw)
        if _setq_items is not None:
            _changed: list[str] = []
            for _sqty, _sdish in _setq_items:
                if not _sdish:
                    continue
                _outcome, _dname = await _execute_ai_update_qty(
                    session, conv, inbound, restaurant_id, _sdish, _sqty,
                    suppress_offers=len(_setq_items) > 1,
                )
                if _outcome == "awaiting_bundle":
                    return
                if _outcome in ("updated", "removed"):
                    _changed.append(_dname or _sdish)
                elif _outcome == "not_in_cart":
                    if await _execute_ai_add_item(
                        session, conv, inbound, restaurant_id, _sdish, _sqty, "",
                        suppress_offers=True,
                    ) == "added":
                        _changed.append(_sdish)
            if _changed:
                _set_state(conv, dialogue_phase="awaiting_confirmation",
                           dialogue_state="order_confirmation")
                await _send_order_summary(session, conv, inbound, restaurant_id, order)
                return
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
            special_note=data.get("special_note", ""),
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


async def _begin_address_capture(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    *,
    restaurant=None,
    location_prefix: str = "ask-location",
    location_body: str = (
        "Great! Please share your delivery location 📍. "
        "Tap the button below to send your pin."
    ),
) -> None:
    """Shared checkout path: resale pitch → saved address → location pin."""
    from app.identity.models import Restaurant

    if restaurant is None:
        restaurant = await session.get(Restaurant, restaurant_id)

    await _maybe_offer_resale(session, conv, inbound, restaurant_id)
    _set_state(conv, dialogue_phase="address_capture", dialogue_state="address_capture")

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

    await _send_location_request(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=location_prefix,
        body=location_body,
    )


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
    dist_km, dist_source = await _road_distance_km(
        restaurant.lat, restaurant.lng, addr.latitude, addr.longitude
    )
    from app.ordering.fees import fee_settings_from_restaurant
    fee = calculate_fee(dist_km, fee_settings_from_restaurant(restaurant.settings))
    order.address_id = addr.id
    order.distance_km = dist_km
    order.distance_source = dist_source
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
    # SAFETY GATE: never confirm without a delivery address — a placed order with no
    # drop-off can't be dispatched. Route back to address capture instead.
    if order.address_id is None:
        _set_state(conv, dialogue_phase="ordering", dialogue_state="address_capture")
        await _begin_address_capture(
            session, conv, inbound, restaurant_id, restaurant=None,
            location_prefix="confirm-need-loc",
            location_body="Almost there! 📍 Share your delivery location so we can send your order.",
        )
        return
    await finalize_confirmation(session, order=order, actor="customer")
    _update_agent_notes(
        conv,
        last_confirmed_order=str(order.order_number or order.id),
        modify_intent=None,
        pending_modify_order=None,
    )
    # Drop the cart pointers now the order is placed — a later order must start a
    # fresh draft, not reuse this (now confirmed) order's id.
    _set_state(conv, dialogue_phase="post_order", dialogue_state="order_placed",
               draft_order_id=None, pending_order_id=None, last_placed_order_id=order.id)
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
    # Same rule as cart updates: every actionable state carries buttons. A plain
    # confirmation left customers typing free text ("Cancel order", "where is my
    # order") — the dead-end that caused the cancel/marketing-opt-out collision.
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-confirmed",
        body=(
            f"Order confirmed! 🎉 Order #{order.order_number}\n"
            f"{payment_line}"
            f"Your food will arrive within ~40 minutes. We'll keep you posted! 🛵"
        ),
        buttons=[
            {"id": "track_order", "title": "Track order"},
            {"id": "modify_order", "title": "Modify order"},
            {"id": "cancel_order", "title": "Cancel order"},
        ],
    )


async def _resolve_order_for_cancel(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
):
    """Find the order a customer is trying to cancel.

    Pre-confirm flows keep ``draft_order_id`` / ``pending_order_id`` in conv.state.
    After confirm those pointers are cleared, so we fall back to the customer's
    latest non-terminal placed order (same resolution as status queries).
    """
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    for key in ("pending_order_id", "draft_order_id"):
        order_id = conv.state.get(key)
        if order_id:
            order = await session.get(Order, order_id)
            if order is not None:
                return order

    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == inbound.from_phone,
        )
    )
    if customer is None:
        return None

    _terminal = {
        str(OrderStatus.CANCELLED),
        str(OrderStatus.DELIVERED),
        str(OrderStatus.UNDELIVERABLE),
        str(OrderStatus.RESOLD),
        str(OrderStatus.WRITTEN_OFF),
        str(OrderStatus.ON_RESALE),
    }
    return await session.scalar(
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.customer_id == customer.id,
            Order.status != str(OrderStatus.DRAFT),
            Order.status.notin_(_terminal),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )


def _cancel_confirmation_body(order_number: str) -> str:
    """Customer-facing cancel ack — never mention internal resale/discount ops."""
    return (
        f"No problem, order #{order_number} is cancelled. "
        "Send 'hi' whenever you're ready to order again 😊"
    )


async def _execute_cancel_order(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> None:
    """Cancel the customer's current order (draft through confirmed/preparing).

    Uses ``cancel_order`` so wallet release, resale path, and dispatch/rider
    detachment all run — a bare FSM transition left assigned riders delivering
    food the customer had already cancelled.
    """
    from app.ordering.fsm import IllegalTransitionError, OrderStatus
    from app.ordering.service import cancel_order

    order = await _resolve_order_for_cancel(session, conv, inbound, restaurant_id)
    if order is None:
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-cancel-none",
            body="You don't have an active order to cancel. Send 'hi' to place a new order.",
        )
        return

    try:
        await cancel_order(session, order=order, actor="customer", reason="customer_cancel")
    except IllegalTransitionError:
        _with_rider = {
            str(OrderStatus.ASSIGNED),
            str(OrderStatus.PICKED_UP),
            str(OrderStatus.ARRIVING),
        }
        if str(order.status) in _with_rider:
            body = (
                f"Sorry, order #{order.order_number} is already with the rider — "
                "we can't cancel it now. Please call the restaurant if you need help."
            )
        elif str(order.status) == str(OrderStatus.READY):
            body = (
                f"Your order #{order.order_number} is ready and a rider is being assigned — "
                "please call the restaurant if you need to change anything."
            )
        else:
            body = (
                f"Sorry, order #{order.order_number} can't be cancelled in its current state. "
                "Please call the restaurant for help."
            )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="order-cancel-blocked", body=body,
        )
        return

    _set_state(conv, dialogue_phase="ordering", dialogue_state="greeting",
               draft_order_id=None, pending_order_id=None)
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="order-cancelled",
        body=_cancel_confirmation_body(order.order_number),
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


def _dish_name_in_text(dish_name: str, raw_text: str) -> bool:
    """True if the dish's own name appears in the customer's message (case/space
    -insensitive substring). Menu-data-driven, language-agnostic — no phrase table."""
    if not dish_name or not raw_text:
        return False

    def norm(s: str) -> str:
        return _re.sub(r"\s+", " ", s.casefold()).strip()

    return norm(dish_name) in norm(raw_text)


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

    # Required-field validation gate (W1, R-069): the interpreter chose an action
    # whose mandatory fields were missing. to_engine_result sets needs_clarification
    # on the action_data and returns action="no_action". Do NOT mutate; send one
    # deterministic clarification reply authored by the engine (not an LLM phrase).
    if data.get("needs_clarification"):
        await _send_text(
            session,
            conv=conv,
            inbound=inbound,
            restaurant_id=restaurant_id,
            prefix="ai-clarify",
            body=reply or (
                "Sorry, I didn't quite catch that — could you tell me the dish "
                "and the exact quantity you'd like? 😊"
            ),
        )
        return

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

    _raw_inbound_text = (
        inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""
    )

    # Menu-promise fulfillment: model said "here's our menu" but chose no_action.
    if action == "no_action" and reply:
        _lower = reply.lower()
        if any(p in _lower for p in _MENU_PROMISE_PATTERNS):
            _cart = await _build_cart_summary(session, conv)
            if (
                _menu_catalog_intercept_allowed(conv)
                and (phase != "post_order" or not _cart)
            ):
                if phase == "post_order" and not _cart:
                    _maybe_reset_post_order_for_browse(conv, _raw_inbound_text)
                await _send_menu_or_catalog(
                    session, conv, inbound, restaurant_id, prefix="menu-promise",
                )
                return

    # Anti-hallucination safety net: if the AI dumped a (fabricated) menu into its
    # reply, swap in the REAL menu before it goes out. Runs in EVERY phase — the model
    # can be asked "show me the menu" mid-confirmation, where it would otherwise echo a
    # menu from history (in catalogue mode that history may hold the old text menu).
    # _render_menu is catalogue-bounded when catalogue mode is on, so this can never
    # leak a text-menu item.
    if _looks_like_menu(reply):
        _draft_for_menu = conv.state.get("draft_order_id")
        if (
            _draft_for_menu
            and await _order_has_items(session, _draft_for_menu)
            and not _is_menu_request(_raw_inbound_text.lower())
        ):
            reply = (
                "Sorry about the mix-up! I've noted your request for the kitchen. 😊"
            )
        else:
            reply = await _render_menu(session, restaurant_id)

    # ── ordering actions ──────────────────────────────────────────────────
    if action == "show_menu":
        if not _menu_catalog_intercept_allowed(conv):
            if reply:
                await _send_text(
                    session, conv=conv, inbound=inbound,
                    restaurant_id=restaurant_id, prefix="ai-reply", body=reply,
                )
            return
        if phase == "post_order":
            if await _build_cart_summary(session, conv):
                if reply:
                    await _send_text(
                        session, conv=conv, inbound=inbound,
                        restaurant_id=restaurant_id, prefix="ai-reply", body=reply,
                    )
                return
            _maybe_reset_post_order_for_browse(conv, _raw_inbound_text)
        if await _try_apply_kitchen_note_to_cart(
            session, conv, inbound, restaurant_id,
        ):
            return
        # Catalogue first (when enabled), else the REAL text menu from the DB — never
        # let the LLM reproduce it (it hallucinated entire fake menus). Ignore message.
        await _send_menu_or_catalog(
            session, conv, inbound, restaurant_id, prefix="show-menu",
        )
        return

    if action == "add_item":
        items = data.get("items") or []
        # SET-quantity guard: "make it 5 lemon mint" / "only 1 biryani" REPLACE the cart
        # quantity, they don't add. The LLM mis-tags these as add_item, so "make it 5"
        # with 1 in the cart wrongly became 6. When the phrasing is a set AND the dish is
        # already in the cart, route to the set path; otherwise ("make it 5" for a dish
        # not in the cart) fall through and add.
        _raw = inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""
        _setq_items = _parse_set_quantity_items(_raw)
        if _setq_items is not None:
            # Lone "make it 5" (no dish) → take the dish the LLM parsed.
            if len(_setq_items) == 1 and not _setq_items[0][1]:
                _fill = (
                    data.get("dish_query")
                    or (items[0].get("dish_query", "") if items else "")
                    or ""
                ).strip()
                _setq_items = [(_setq_items[0][0], _fill)] if _fill else []
            _multi = len(_setq_items) > 1
            _changed: list[str] = []
            for _sqty, _sdish in _setq_items:
                if not _sdish:
                    continue
                _outcome, _dname = await _execute_ai_update_qty(
                    session, conv, inbound, restaurant_id, _sdish, _sqty,
                    suppress_offers=_multi,
                )
                if _outcome == "awaiting_bundle":
                    return  # single-dish bundle question already sent
                if _outcome in ("updated", "removed"):
                    _changed.append(_dname or _sdish)
                elif _outcome == "not_in_cart":
                    # set-to-N for a dish not in the cart yet == add N of it.
                    if await _execute_ai_add_item(
                        session, conv, inbound, restaurant_id, _sdish, _sqty, "",
                        suppress_offers=True,
                    ) == "added":
                        _changed.append(_sdish)
                # no_match → leave it for the normal add path below
            if _changed:
                cart = await _build_cart_summary(session, conv)
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="ai-set-qty", body=f"Updated! ✅{_cart_tail(cart)}",
                )
                return
            # nothing changed → fall through: treat as a normal add.
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
                if status in ("added", "updated_note"):
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
            _multi_order = None
            if added and (_mdid := conv.state.get("draft_order_id")):
                from app.ordering.models import Order as _MultiOrder

                _multi_order = await session.get(_MultiOrder, _mdid)
            if _multi_order is not None:
                upsell, buttons = await _post_add_extras(
                    session, conv, restaurant_id, _multi_order
                )
                await _send_buttons(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="ai-add-multi", body=f"{body}{upsell}", buttons=buttons,
                )
            else:
                await _send_text(session, conv=conv, inbound=inbound,
                                 restaurant_id=restaurant_id, prefix="ai-add-multi", body=body)
            return

        # Single dish — named via the items list (length 1) or the flat dish_query.
        # Capture the raw (pre-default) qty from whichever source supplied the dish, so
        # the backstop's "did the customer give a quantity?" check reads the same source.
        if len(items) == 1 and not data.get("dish_query"):
            dish_query = items[0].get("dish_query", "")
            _raw_qty = items[0].get("qty")
            special_note = items[0].get("special_note", "")
        else:
            dish_query = data.get("dish_query", "")
            _raw_qty = data.get("qty")
            special_note = data.get("special_note", "")
        qty = int(_raw_qty or 1)
        if dish_query and qty > _max_item_qty(restaurant):
            await _escalate_large_qty(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                qty=qty, dish_query=dish_query,
            )
            return
        if dish_query:
            raw_text = inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""
            # Re-add backstop: the agent named a dish already in the cart, but the
            # customer never named it (and gave no quantity) -> this is a mis-fired
            # add (e.g. a closing parsed as add_item). Do NOT inflate the cart.
            # Only run this backstop when a draft order exists; short-circuit for perf.
            _draft_id = conv.state.get("draft_order_id")
            if _draft_id:
                already = await _resolve_cart_dish(
                    session,
                    order_id=_draft_id,
                    candidates=(await find_dish_matches(
                        session, restaurant_id=restaurant_id, query=dish_query)).candidates,
                )
                gave_qty = _raw_qty is not None
                # Known limit: if the menu/DB dish name and the customer's script differ
                # (e.g. English DB name vs Arabic message), the name won't be found in
                # raw_text and a genuine name-less repeat is suppressed. Accepted tradeoff
                # vs silent overcharge.
                if (already is not None
                        and not gave_qty
                        and not _dish_name_in_text(already.name, raw_text)):
                    cart = await _build_cart_summary(session, conv)
                    await _send_text(
                        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                        prefix="ai-readd-noop",
                        body=f"You're all set 😊{_cart_tail(cart)}\nReady to checkout? Just say 'done'.",
                    )
                    return
            status = await _execute_ai_add_item(
                session, conv, inbound, restaurant_id, dish_query, qty, special_note
            )
            if status in ("added", "updated_note"):
                # W3: DB-backed cart tail — the LLM reply is a tone lead only; money
                # facts come solely from the DB cart (RA-1/R-013/R-040). Strip any 🛒
                # line the model added (else the cart renders twice) and drop a reply
                # that is empty or a fabricated menu.
                cart = await _build_cart_summary(session, conv)
                lead = "\n".join(
                    ln for ln in reply.splitlines() if not ln.strip().startswith("🛒")
                ).strip() if reply else ""
                lead = _strip_money_claims(lead)  # R-067: never let the LLM state money
                if not lead or _looks_like_menu(lead):
                    lead = "Got it! 😊"
                _ups_order = None
                _ups_did = conv.state.get("draft_order_id")
                if _ups_did:
                    from app.ordering.models import Order as _UpsOrder

                    _ups_order = await session.get(_UpsOrder, _ups_did)
                await _record_cart_observation(session, conv)  # F66/W3
                if _ups_order is not None:
                    upsell, buttons = await _post_add_extras(
                        session, conv, restaurant_id, _ups_order
                    )
                    await _send_buttons(
                        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                        prefix="ai-add", body=f"{lead}{_cart_tail(cart)}{upsell}",
                        buttons=buttons,
                    )
                else:
                    await _send_text(session, conv=conv, inbound=inbound,
                                     restaurant_id=restaurant_id, prefix="ai-add",
                                     body=f"{lead}{_cart_tail(cart)}")
            elif status == "no_match":
                if await _try_apply_kitchen_note_to_cart(
                    session, conv, inbound, restaurant_id,
                ):
                    return
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
        if outcome in ("removed", "reduced"):
            await _record_cart_observation(session, conv)  # F66/W3
        await _send_cart_confirmation(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-remove", body=body, cart=cart,
        )
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
                    session, conv, inbound, restaurant_id, iq, iqty, suppress_offers=True,
                    special_note=it.get("special_note", ""),
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
            await _send_cart_confirmation(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="ai-qty-multi", body=body, cart=cart,
            )
            return

        dish_query = data.get("dish_query", "") or (items[0].get("dish_query", "") if items else "")
        raw_qty = data.get("qty") if data.get("qty") is not None else (items[0].get("qty") if items else None)
        special_note = (
            data.get("special_note", "")
            or (items[0].get("special_note", "") if items else "")
        )
        # cart_set_note → update_qty with note only (qty omitted).
        if raw_qty is None and special_note and dish_query:
            if await _apply_note_to_existing_cart_item(
                session,
                conv,
                dish_id=-1,
                notes=special_note,
                dish_query=dish_query,
            ):
                cart = await _build_cart_summary(session, conv)
                await _record_cart_observation(session, conv)
                clean = special_note.strip()
                body = (
                    f"Got it! I've noted {clean} for your order 😊{_cart_tail(cart)}"
                )
                await _send_cart_confirmation(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="ai-set-note", body=body, cart=cart,
                )
                return
        qty = int(raw_qty or 1)
        if dish_query and qty > _max_item_qty(restaurant):
            await _escalate_large_qty(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                qty=qty, dish_query=dish_query,
            )
            return
        outcome, dish_name = await _execute_ai_update_qty(
            session, conv, inbound, restaurant_id, dish_query, qty,
            special_note=special_note,
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
        if outcome in ("updated", "removed"):
            await _record_cart_observation(session, conv)  # F66/W3
        await _send_cart_confirmation(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-qty", body=body, cart=cart,
        )
        return

    if action == "clear_cart":
        # Guard: a destructive cart-wipe must LOSE to an actual order. The LLM sometimes
        # tags an order ("one beef curry") as clear_cart; if the message isn't an explicit
        # "empty/start over" AND parses to a dish query, route it to the add path so the
        # item is added (or honestly declined) instead of the cart being silently emptied.
        raw_text = inbound.payload.get("text", "") if inbound.type == MessageType.TEXT else ""
        if raw_text.strip() and not _is_explicit_clear(raw_text):
            from app.ordering.service import parse_qty_and_text

            _q, _dq = parse_qty_and_text(raw_text)
            if _dq and not _is_checkout_intent(_dq):
                await _handle_collecting_items(session, conv, inbound, restaurant_id)
                return

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
        await _begin_address_capture(
            session, conv, inbound, restaurant_id, restaurant=restaurant,
            location_prefix="ai-proceed-addr-loc",
            location_body=(
                "Great! Please share your delivery location 📍. Tap the button below "
                "to send your pin so the rider reaches you exactly."
            ),
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
        # W3: do NOT forward the LLM reply here — the address-capture paths already
        # send _send_order_summary with DB-backed totals as the confirm message. A
        # bare LLM reply would carry stale/hallucinated money facts with no DB
        # summary behind it (F104/TX-17). Confirmation stays engine-authored.
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
    if phase == "post_order" and action in ("remove_item", "update_qty"):
        await _apply_post_confirm_line_edit(
            session, conv, inbound, restaurant_id, action, data,
        )
        return

    if phase == "post_order" and action == "confirm_line_edit":
        await _handle_modify_confirm(session, conv, inbound, restaurant_id)
        return

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
        return

    # Empty no_action reply → NEVER silence. Clarify with real context: reference
    # the cart when one exists (not another menu dump — the menu-as-universal-
    # fallback loop drove a prod customer to give up and cancel).
    cart = await _build_cart_summary(session, conv)
    if cart:
        body = (
            f"Sorry, I didn't quite get that 😅 You have:{_cart_tail(cart)}\n\n"
            "Add more items, tell me what to change, or say 'done' to check out."
        )
    else:
        body = (
            "Sorry, I didn't quite get that 😅 Tell me the dish you'd like, "
            "or say 'menu' to see everything."
        )
    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="ai-clarify-empty", body=body,
    )


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

    dist_km, dist_source = await _road_distance_km(restaurant.lat, restaurant.lng, lat, lng)

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
        # R-008: an undeliverable pin must NEVER wipe the cart — only clear the
        # pin/fee/address-capture state so the customer can retry with a new pin
        # or call the restaurant, without re-building the whole order from scratch.
        _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items",
                   pin_lat=None, pin_lon=None, distance_km=None, distance_source=None,
                   delivery_fee=None)

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
        distance_source=dist_source,
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



async def _okf_grounding(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage, restaurant_id: int
) -> str:
    """Retrieve authoritative OKF facts for this message + customer and render a
    grounding block for the prompt. Lazily ensures the menu/policy bundle exists
    (first use per restaurant) and refreshes this customer's profile doc."""
    from app.okf import producer, retrieval
    from app.okf.models import OkfDoc
    from app.ordering.service import get_or_create_customer

    text = (inbound.payload.get("text") or "").strip() if inbound.type == MessageType.TEXT else ""
    if not text:
        return ""
    # Lazily build the menu/policy bundle once (cheap upsert; skip if present).
    has_any = await session.scalar(
        select(OkfDoc.id).where(OkfDoc.restaurant_id == restaurant_id).limit(1)
    )
    if has_any is None:
        await producer.refresh_menu_and_policy(session, restaurant_id=restaurant_id)
    customer = await get_or_create_customer(session, restaurant_id=restaurant_id, phone=inbound.from_phone)
    await producer.refresh_customer(session, restaurant_id=restaurant_id, customer_id=customer.id)

    # Language-agnostic entity pins: dishes in the customer's current cart + their
    # pending/draft order. These ground non-English questions (Telugu/Arabic/Urdu)
    # that pg_trgm can't lexically match against English docs.
    from app.ordering.models import OrderItem

    dish_ids: list[int] = []
    order_ref = conv.state.get("pending_order_id") or conv.state.get("draft_order_id")
    if order_ref:
        rows = await session.scalars(
            select(OrderItem.dish_id).where(OrderItem.order_id == int(order_ref))
        )
        dish_ids = list(rows)

    docs = await retrieval.retrieve(
        session, restaurant_id=restaurant_id, query=text, customer_id=customer.id,
        dish_ids=dish_ids or None, order_id=int(order_ref) if order_ref else None,
    )
    return retrieval.grounding_block(docs)


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

    if restaurant is None:
        restaurant = await session.get(RestaurantModel, restaurant_id)

    restaurant_name = restaurant.name if restaurant else "Restaurant"
    phase = _resolve_phase(conv)
    _inbound_text = (
        (inbound.payload.get("text") or "").strip()
        if inbound.type == MessageType.TEXT
        else ""
    )
    try:
        history = await _build_history(session, conv, dialogue_phase=phase)
    except Exception:
        _logger.warning(
            "build_history failed for restaurant %s conv %s",
            restaurant_id, conv.id, exc_info=True,
        )
        history = [{"role": "user", "content": _inbound_text or "hi"}]
    try:
        context = await _build_context(session, conv, restaurant_id, phase, restaurant)
    except Exception:
        _logger.warning(
            "build_context failed for restaurant %s conv %s",
            restaurant_id, conv.id, exc_info=True,
        )
        context = {
            "order_number": "",
            "order_status": "unknown",
            "rider_eta": "",
            "menu_text": "",
            "cart_summary": "",
            "cart_lines": [],
            "delivery_info": "",
            "restaurant_location": "unknown",
            "hours_info": "",
            "restaurant_phone": "",
        }

    # Off-topic (health, homework, etc.) → warm decline, NEVER the menu. The LLM used to
    # reply with a fabricated menu or trigger show_menu on "I have fever what can I do".
    if inbound.type == MessageType.TEXT:
        _off_cat = _classify_off_topic(inbound.payload.get("text"))
        if _off_cat:
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix=f"off-topic-{_off_cat}",
                body=_off_topic_reply(_off_cat, restaurant_name),
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

    # Deterministic checkout: a clear "that's all / no that's all / done / nothing else"
    # with items in the cart goes STRAIGHT to the summary/address — never loop on
    # "anything else?" or bounce to a greeting. The LLM was unreliable here (it re-added
    # the same dish repeatedly and once sent a welcome mid-order), so short-circuit before
    # it runs. Empty cart → fall through to the AI (a bare "done" may mean something else).
    if (
        phase == "ordering"
        and inbound.type == MessageType.TEXT
        and _is_checkout_shortcut(inbound.payload.get("text") or "")
    ):
        from app.ordering.models import Order

        _did = conv.state.get("draft_order_id")
        _order = await session.get(Order, _did) if _did else None
        if (
            _order is not None
            and str(_order.status) == "draft"
            and await _order_has_items(session, _order.id)
        ):
            await _handle_done_checkout(
                session, conv, inbound, restaurant_id, restaurant=restaurant
            )
            return

    # Negation swap: "No give me chicken soup" right after an add means REPLACE the
    # last cart line with the named dish (prod: this crashed the LLM path and sent the
    # canned error). Deterministic, and only for an explicit desire verb — a bare
    # "no <dish>" stays with the existing remove/AI paths.
    if (
        phase == "ordering"
        and inbound.type == MessageType.TEXT
        and await _try_negation_swap(session, conv, inbound, restaurant_id)
    ):
        return

    # Keep-only: "only mandi" / "just the biryani" means prune the cart to that dish, NOT
    # wipe it (the LLM tagged "only mandi" as clear_cart and emptied everything). Handle
    # deterministically when the named dish is actually in the cart; else fall through.
    if (
        phase == "ordering"
        and inbound.type == MessageType.TEXT
    ):
        _keep_q = _parse_keep_only(inbound.payload.get("text") or "")
        if _keep_q:
            _removed, _kept = await _keep_only_dish(session, conv, restaurant_id, _keep_q)
            if _kept is not None:
                cart = await _build_cart_summary(session, conv)
                body = (
                    f"Done! Kept only {_kept}, removed the rest ✅{_cart_tail(cart)}"
                    if _removed
                    else f"You've got just {_kept} 😊{_cart_tail(cart)}\n\n"
                    "Add more, or say 'done' to check out."
                )
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="keep-only", body=body,
                )
                return

    # Deterministic clear: "clear cart" / "empty the cart" / "start over" must empty the
    # cart — never reach the LLM, which fuzzy-matched "clear" to the dish "Clear Soup" and
    # ADDED it. Precise paired phrasing only, so ordering "clear soup" still works.
    if (
        phase == "ordering"
        and inbound.type == MessageType.TEXT
        and _is_clear_cart_command(inbound.payload.get("text") or "")
    ):
        from sqlalchemy import delete as sa_delete

        from app.ordering.models import Order, OrderItem

        _did = conv.state.get("draft_order_id")
        _order = await session.get(Order, _did) if _did else None
        if _order is not None and str(_order.status) == "draft":
            await session.execute(
                sa_delete(OrderItem).where(OrderItem.order_id == _order.id)
            )
            _order.subtotal = Decimal("0.00")
            _order.total = _order.delivery_fee_aed
            await session.flush()
            _set_state(conv, dialogue_state="collecting_items", abandoned_nudged=None)
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="clear-cart-cmd",
            body="Cleared your cart 🧹 What would you like to order?",
        )
        return

    # Store saved_address_id in conv.state for use_saved_address action
    if "saved_address_id" in context:
        _set_state(conv, saved_address_id=context["saved_address_id"])

    # Prompt KB (vector RAG over context.txt): retrieve master-template + phase specs.
    try:
        from app.config import get_settings
        from app.llm.prompt_kb import prompt_kb_grounding

        _kb_settings = get_settings()
        if _kb_settings.prompt_kb_enabled and _inbound_text:
            context["prompt_kb"] = prompt_kb_grounding(
                _inbound_text,
                phase=phase,
                top_k=_kb_settings.prompt_kb_top_k,
                max_chars=_kb_settings.prompt_kb_max_chars,
            )
        else:
            context["prompt_kb"] = ""
    except Exception:  # noqa: BLE001
        context["prompt_kb"] = ""

    # OKF grounding (RAG): retrieve authoritative facts for this message + customer
    # so the bot answers from real data (menu/policy/customer/order), not invention.
    # Best-effort — grounding must never break a reply.
    try:
        context["grounding"] = await _okf_grounding(session, conv, inbound, restaurant_id)
    except Exception:  # noqa: BLE001
        context["grounding"] = ""

    try:
        from app.conversation.context_metrics import log_context_snapshot
        from app.llm.conversation_prompts import build_identity, build_phase_block

        log_context_snapshot(
            restaurant_id=restaurant_id,
            conv_id=conv.id,
            phase=phase,
            system=build_identity(restaurant_name, context) + build_phase_block(phase, context),
            history=history,
            grounding=context.get("grounding"),
        )
    except Exception:  # noqa: BLE001
        _logger.debug("context_metrics snapshot failed", exc_info=True)

    agent = get_conversation_agent()
    try:
        result = await agent.respond(
            restaurant_name=restaurant_name,
            dialogue_phase=phase,
            history=history,
            context=context,
        )
    except Exception:
        _logger.error(
            "agent.respond failed for restaurant %s conv %s (phase=%s)",
            restaurant_id, conv.id, phase, exc_info=True,
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-fallback",
            body=await _contextual_error_body(session, conv),
        )
        return

    try:
        await _dispatch_action(
            session, conv, inbound, restaurant_id, result, phase, restaurant
        )
    except Exception:
        _logger.error(
            "dispatch_action failed for restaurant %s conv %s",
            restaurant_id, conv.id, exc_info=True,
        )
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="action-fallback",
            body=await _contextual_error_body(session, conv),
        )


async def _resolve_counterpart(
    session: AsyncSession, restaurant_id: int, phone: str
):
    """Return ("rider", rider) if the phone is a rider for this tenant, else ("customer", None)."""
    from app.identity.models import Rider
    from app.identity.phones import phone_lookup_values

    rider = await session.scalar(
        select(Rider).where(
            Rider.restaurant_id == restaurant_id,
            Rider.phone.in_(phone_lookup_values(phone)),
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

    # Free-form rider messages (text, voice transcript, etc.) — no bot reply, but
    # flag the thread for the manager, notify them on WhatsApp, and ack the rider.
    if inbound.type in {MessageType.TEXT, MessageType.AUDIO, MessageType.IMAGE}:
        text = (inbound.payload.get("text") or inbound.payload.get("caption") or "").strip()
        if inbound.type == MessageType.TEXT and not text:
            return
        conv.manual_takeover = True
        conv.taken_over_by = restaurant_id
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=inbound.from_phone,
            msg_type=OutboundMessageType.TEXT,
            payload={
                "body": "Got it — the manager has been notified and will reply shortly.",
            },
            idempotency_key=f"rider-free-ack-{inbound.wa_message_id}",
            mirror_rider_conversation=False,
        )
        from app.identity.models import Restaurant as RestaurantModel

        restaurant = await session.get(RestaurantModel, restaurant_id)
        if restaurant is not None and restaurant.phone:
            preview = text if text else "📎 attachment"
            if len(preview) > 160:
                preview = preview[:160].rstrip() + "…"
            rider_label = getattr(rider, "name", None) or inbound.from_phone
            await enqueue_message(
                session,
                restaurant_id=restaurant_id,
                to_phone=restaurant.phone,
                msg_type=OutboundMessageType.TEXT,
                payload={
                    "body": (
                        f"🛵 Driver {rider_label} ({inbound.from_phone}) sent a message:\n"
                        f"\"{preview}\"\n"
                        "Open Chats → Drivers to reply."
                    ),
                },
                idempotency_key=f"rider-msg-mgr-{inbound.wa_message_id}",
                mirror_rider_conversation=False,
            )
        return


async def _download_and_transcribe_voice(
    inbound: InboundMessage,
) -> tuple[str | None, bytes | None, str | None]:
    """Download a WhatsApp voice note, transcribe it, and return raw bytes for
    dashboard replay. Returns (transcript, audio_bytes, mime). STT is best-effort
    — never raises into the dialogue flow."""
    media_id = inbound.payload.get("audio_id")
    if not media_id:
        return None, None, None
    try:
        from app.speech.factory import get_transcriber
        from app.whatsapp.factory import get_whatsapp_provider

        provider = get_whatsapp_provider()
        audio, mime = await provider.download_media(media_id)
        mime = mime or inbound.payload.get("mime") or "audio/ogg"
        transcript = await get_transcriber().transcribe(audio, mime=mime)
        text = (transcript or "").strip() or None
        return text, audio or None, mime
    except Exception:
        _logger.exception("voice transcription failed (%s)", inbound.wa_message_id)
        return None, None, None


async def _try_catalog_cart_edit(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
    restaurant,
) -> bool:
    """In catalogue mode, handle remove / set-quantity edits BEFORE the add-only
    typed-order path. Regression: "Remove 3 chicken soup" and "Make it 5 chicken soup"
    were parsed as adds via parse_qty_and_text inside _try_catalog_typed_order."""
    if inbound.type != MessageType.TEXT:
        return False
    if not await _catalog_mode_on(session, restaurant_id):
        return False
    text = (inbound.payload.get("text") or "").strip()
    if not text:
        return False

    remove_items = _parse_remove_items(text)
    setq_items = None if remove_items is not None else _parse_set_quantity_items(text)
    # Nearest-context references ("remove it", "one more") resolve to the most-recent line.
    _remove_ref = (
        remove_items is None and setq_items is None and _is_remove_reference(text)
    )
    _add_more = (
        remove_items is None and setq_items is None and not _remove_ref
        and _is_add_more_reference(text)
    )
    if remove_items is None and setq_items is None and not _remove_ref and not _add_more:
        return False

    draft_order_id = conv.state.get("draft_order_id") or conv.state.get("pending_order_id")
    if not draft_order_id:
        return False

    from app.ordering.models import Order

    order = await session.get(Order, draft_order_id)
    if order is None or str(order.status) != "draft":
        return False

    if conv.state.get("draft_order_id") != order.id:
        _set_state(conv, draft_order_id=order.id)

    phase = _resolve_phase(conv)
    prefix = "catalog-cart-edit"
    body: str

    # Resolve nearest-context references now that we have the order.
    if _remove_ref or _add_more:
        _recent = await _most_recent_cart_item(session, order.id)
        if _recent is None:
            return False  # nothing to reference → let the normal flow reply
        if _remove_ref:
            remove_items = [(None, _recent.dish_name)]  # remove the whole recent line
        else:  # _add_more → add one of the most-recent dish
            outcome = await _execute_ai_add_item(
                session, conv, inbound, restaurant_id, _recent.dish_name, 1, "",
                suppress_offers=True,
            )
            cart = await _build_cart_summary(session, conv)
            body = (
                f"Added 1x {_recent.dish_name} ✅{_cart_tail(cart)}"
                if outcome == "added"
                else f"🛒 {cart}" if cart else "Your cart is empty."
            )
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="catalog-cart-add-more", body=body,
            )
            return True

    if remove_items is not None:
        # Multi-item remove: "remove 1 lemon mint and 1 7 up" takes off BOTH (prod bug:
        # only the first came off). Each item resolved independently; report what came
        # off and what couldn't be found.
        removed_labels: list[str] = []
        not_found: list[str] = []
        for rm_qty, dish_query in remove_items:
            outcome, dish_name = await _execute_ai_remove_item(
                session, conv, restaurant_id, dish_query, rm_qty,
            )
            if outcome == "removed":
                removed_labels.append(dish_name or dish_query)
            elif outcome == "reduced":
                removed_labels.append(f"{rm_qty}x {dish_name}")
            else:
                not_found.append(dish_name or dish_query)
        if phase == "awaiting_confirmation":
            _set_state(conv, dialogue_phase="awaiting_confirmation",
                       dialogue_state="order_confirmation")
            await _send_order_summary(session, conv, inbound, restaurant_id, order)
            return True
        cart = await _build_cart_summary(session, conv)
        if removed_labels and not not_found:
            body = f"Done! Removed {', '.join(removed_labels)} ✅{_cart_tail(cart)}"
        elif removed_labels:
            body = (
                f"Done! Removed {', '.join(removed_labels)} ✅ "
                f"(couldn't find {', '.join(not_found)}){_cart_tail(cart)}"
            )
        else:
            body = (
                f"I couldn't find {', '.join(not_found)} to remove. Tell me the dish "
                "name and I'll take it off 😊"
            )
        prefix = "catalog-cart-remove"
    else:
        assert setq_items is not None
        # Bare "make it 5" (no dish named) — resolve deterministically instead of
        # punting to the flaky LLM (prod: "Make it 5" on a single-line cart crashed to
        # the canned error, while "Make it 5 arayes" worked):
        #   • exactly ONE distinct dish in the cart → set that line (unambiguous)
        #   • TWO+ distinct dishes → target the MOST RECENTLY added dish (nearest
        #     context = what the customer just touched), not a "which one?" detour
        #   • empty cart → nothing to set → defer to the normal flow
        if len(setq_items) == 1 and not setq_items[0][1]:
            from app.ordering.models import OrderItem as _OI_setq

            _rows = [
                r for r in (await session.scalars(
                    select(_OI_setq).where(_OI_setq.order_id == order.id)
                )).all()
                if r.qty > 0
            ]
            _bare_qty = setq_items[0][0]
            if not _rows:
                return False  # empty cart → let the normal flow reply
            _distinct = {r.dish_id for r in _rows}
            if len(_distinct) == 1:
                setq_items = [(_bare_qty, _rows[0].dish_name)]
            else:
                # Nearest-context resolution: read the recent turn — "make it N" means
                # the dish the customer MOST RECENTLY added/touched (last cart line by
                # insertion), so we act instead of re-asking "which one?".
                _recent = max(_rows, key=lambda r: r.id)
                setq_items = [(_bare_qty, _recent.dish_name)]
        changed: list[str] = []
        for sqty, sdish in setq_items:
            if not sdish:
                return False  # lone "make it 5" — dish name needed; let the AI resolve
            outcome, dname = await _execute_ai_update_qty(
                session, conv, inbound, restaurant_id, sdish, sqty,
                suppress_offers=len(setq_items) > 1,
            )
            if outcome == "awaiting_bundle":
                return True
            if outcome in ("updated", "removed"):
                changed.append(dname or sdish)
            elif outcome == "not_in_cart":
                if await _execute_ai_add_item(
                    session, conv, inbound, restaurant_id, sdish, sqty, "",
                    suppress_offers=True,
                ) == "added":
                    changed.append(sdish)
        if not changed:
            return False
        if phase == "awaiting_confirmation":
            _set_state(conv, dialogue_phase="awaiting_confirmation",
                       dialogue_state="order_confirmation")
            await _send_order_summary(session, conv, inbound, restaurant_id, order)
            return True
        cart = await _build_cart_summary(session, conv)
        body = f"Updated! ✅{_cart_tail(cart)}"
        prefix = "catalog-cart-set-qty"

    await _send_text(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix=prefix, body=body,
    )
    return True


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

    # No phase gate: by the time we reach here in handle_inbound, every greeting /
    # menu-request / cart / tracking / checkout guard has already run, so a clearly
    # typed dish is an order REGARDLESS of phase. (The old `phase=="ordering"` gate
    # meant the FIRST dish right after "hi" — before any "ordering" phase was set —
    # fell through to the model, which then re-sent the catalogue instead of adding.)
    if inbound.type != MessageType.TEXT:
        return False
    if not await _catalog_mode_on(session, restaurant_id):
        return False
    text = (inbound.payload.get("text") or "").strip()
    if not text or "?" in text or _is_menu_request(text.lower()):
        return False  # questions / menu requests → AI
    if _is_cart_edit_intent(text):
        return False  # remove / set-qty — handled by _try_catalog_cart_edit

    _set_state(conv, menu_in_context=True)

    # "only/just N <dish>" signals an absolute-set intent — detect BEFORE stripping so
    # the signal survives filler removal (we strip them below but the flag is preserved).
    is_only_intent = bool(_re.match(
        r"^(?:only|just|i\s+only\s+want|i\s+just\s+want)\s+",
        text,
        _re.IGNORECASE,
    ))

    # Strip leading politeness/filler so "ok add one mutton biryani", "please give me 2
    # biryani", "i want chicken" parse down to the real dish + quantity.
    fillers = (
        "i would like", "i'd like", "id like", "i'll have", "ill have", "can i get",
        "could i get", "let me get", "i want", "i need", "give me", "get me", "gimme",
        "please", "kindly", "okay", "okey", "ok", "pls", "add", "want",
        "only", "just", "need",  # "only/just" stripped after flag set; "need" strips prefix
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

    # ── Multi-item typed order ──────────────────────────────────────────────────
    # Read the WHOLE sentence: "1 mojito and 1 chicken biryani", "coke, fries",
    # "biryani & mojito" are TWO dishes, not one dish with a note. Split on
    # conjunctions and add each line deterministically — but ONLY when EVERY segment
    # is itself a real catalogue dish. A dish + modifier ("biryani and make it spicy")
    # or a dish whose NAME contains "and" ("fish and chips") is NOT all-dishes, so it
    # falls through to the single-item note logic below. Prod regression: the message
    # became one line "Mojito — and 1 chicken biryani" (2nd dish buried as a note).
    _whole = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
    _whole_exact = bool(
        _whole.confidence == MatchConfidence.DIRECT and _whole.candidates
        and _whole.candidates[0].name_normalized == normalize_name(dish_query)
    )
    _segments = [s.strip() for s in _CONJUNCTION_SPLIT.split(body) if s.strip()]
    if not _whole_exact and len(_segments) >= 2:
        _resolved: list[tuple] = []  # (dish, qty)
        _all_dishes = True
        for _seg in _segments:
            _sq, _sname = parse_qty_and_text(_seg)
            _sname = _sname.strip()
            _sm = (
                await find_dish_matches(session, restaurant_id=restaurant_id, query=_sname)
                if _sname else None
            )
            if (_sm is not None and _sm.confidence == MatchConfidence.DIRECT
                    and _sm.candidates
                    and not await _catalog_excludes_dish(
                        session, restaurant_id, _sm.candidates[0])):
                _resolved.append((_sm.candidates[0], _sq or 1))
            else:
                _all_dishes = False
                break
        _maxq = _max_item_qty(restaurant)
        if (_all_dishes and len(_resolved) >= 2
                and all(q <= _maxq for _, q in _resolved)):
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
                    pin_lat=None, pin_lon=None, distance_km=None,
                    distance_source=None, delivery_fee=None,
                )
            for _d, _q in _resolved:
                await add_item(session, order=order, dish=_d, qty=_q, notes=None)
            _set_state(
                conv, dialogue_phase="ordering", dialogue_state="collecting_items"
            )
            cart = await _build_cart_summary(session, conv)
            await _record_cart_observation(session, conv)  # F66/W3
            upsell, buttons = await _post_add_extras(
                session, conv, restaurant_id, order
            )
            _added = ", ".join(f"{_q}x {_d.name}" for _d, _q in _resolved)
            await _send_buttons(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="catalog-typed-add-multi",
                body=f"Added {_added} ✅{_cart_tail(cart)}{upsell}",
                buttons=buttons,
            )
            return True

    # Split a modifier off the dish: prefer the LONGEST prefix that EXACTLY matches a
    # dish name, with the trailing words as the special note — "chicken biryani double
    # masala" → dish "Chicken Biryani" + note "double masala". (Fuzzy matching can't be
    # used for the split: it accepts "chicken biryani double" as the dish, so the note
    # would lose words.) Without this a typed order WITH a modifier fell through to the
    # LLM, which misfired (returned clear_cart and wiped the cart).
    words = dish_query.split()
    dish = None
    note: str | None = None

    # W2/T6: "[note_words] in/for/on [dish_ref]" pattern — e.g. "double masala in
    # biriyani", "extra sauce for biryani".  Only fired when a draft order already
    # exists so there is a cart to update; avoids false-note on a first-order message.
    _nid = _re.match(
        r"^(.+?)\s+(?:in|for|on)\s+(\S.{0,60})$",
        dish_query,
        _re.IGNORECASE,
    ) if conv.state.get("draft_order_id") else None
    if _nid:
        _nid_note_part = _nid.group(1).strip()
        _nid_dish_part = _nid.group(2).strip()
        _nid_res = await find_dish_matches(
            session, restaurant_id=restaurant_id, query=_nid_dish_part
        )
        if _nid_res.confidence == MatchConfidence.DIRECT and _nid_res.candidates:
            dish = _nid_res.candidates[0]
            note = _nid_note_part
        elif _nid_res.confidence == MatchConfidence.AMBIGUOUS and _nid_res.candidates:
            # Ambiguous dish reference (e.g. "biriyani" matching both Chicken Biryani
            # and Mutton Biryani): prefer the candidate already in the cart (RA-7).
            # This turns "double masala in biriyani" into a note-set on the biryani
            # the customer actually ordered, without adding a duplicate line.
            _nid_draft_oid = conv.state.get("draft_order_id")
            if _nid_draft_oid:
                from app.ordering.models import OrderItem as _OI_nid
                for _nid_cand in _nid_res.candidates:
                    _nid_hit = await session.scalar(
                        select(_OI_nid.id).where(
                            _OI_nid.order_id == _nid_draft_oid,
                            _OI_nid.dish_id == _nid_cand.id,
                        ).limit(1)
                    )
                    if _nid_hit is not None:
                        dish = _nid_cand
                        note = _nid_note_part
                        break

    if dish is None:
        for cut in range(len(words), 0, -1):
            cand = " ".join(words[:cut])
            pref = await find_dish_matches(session, restaurant_id=restaurant_id, query=cand)
            if (pref.confidence == MatchConfidence.DIRECT and pref.candidates
                    and pref.candidates[0].name_normalized == normalize_name(cand)):
                dish = pref.candidates[0]
                note = (" ".join(words[cut:]).strip() or None)
                break

    if dish is None:
        # No exact dish-name prefix → fall back to a fuzzy match on the WHOLE query (no
        # note). Catches typos like "chicken biriyani" — still adds the dish.
        pref = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)
        if pref.confidence == MatchConfidence.DIRECT and pref.candidates:
            dish = pref.candidates[0]
        else:
            # W2/T6 Note-indicator heuristic: "extra masala", "without onion", "spicy"
            # etc.  Body starts with a kitchen-modifier word and remainder is NOT a
            # known dish → treat as a kitchen note for the single in-cart dish (F101).
            _NOTE_STARTERS = {
                "extra", "without", "less", "light", "spicy", "mild",
                "hot", "cold", "crispy", "soft", "double", "triple", "half",
            }
            _bwords = body.split()
            if _bwords and _bwords[0].lower() in _NOTE_STARTERS:
                _rest_q = " ".join(_bwords[1:]).strip()
                if _rest_q:
                    _rm = await find_dish_matches(
                        session, restaurant_id=restaurant_id, query=_rest_q
                    )
                    if _rm.confidence == MatchConfidence.DIRECT and _rm.candidates:
                        # e.g. "extra lemon mint" → add that dish (not a note)
                        dish = _rm.candidates[0]
                if dish is None:
                    # Non-dish modifier phrase → apply as note to the single in-cart dish
                    _doid = conv.state.get("draft_order_id")
                    if _doid:
                        from app.ordering.models import OrderItem as _OI_h
                        _ord_h = await session.get(Order, _doid)
                        if _ord_h and str(_ord_h.status) == "draft":
                            _its_h = (
                                await session.scalars(
                                    select(_OI_h).where(_OI_h.order_id == _ord_h.id)
                                )
                            ).all()
                            if len({i.dish_id for i in _its_h}) == 1:
                                from app.ordering.cart_service import (
                                    CartService, normalize_note,
                                )
                                _cs_h = CartService(session)
                                await _cs_h.set_note(
                                    order=_ord_h,
                                    dish_id=_its_h[0].dish_id,
                                    raw_note=body,
                                )
                                _set_state(
                                    conv,
                                    dialogue_phase="ordering",
                                    dialogue_state="collecting_items",
                                )
                                _cart_h = await _build_cart_summary(session, conv)
                                await _record_cart_observation(session, conv)  # F66/W3
                                await _send_cart_confirmation(
                                    session, conv=conv, inbound=inbound,
                                    restaurant_id=restaurant_id,
                                    prefix="catalog-typed-note",
                                    body=(
                                        f"Got it! {normalize_note(body)} for "
                                        f"{_its_h[0].dish_name} ✅{_cart_tail(_cart_h)}"
                                    ),
                                    cart=_cart_h,
                                )
                                return True
            if dish is None:
                return False  # no match → AI (warm reply or disambiguates)
    # If the trailing "note" is itself another dish, this is a MULTI-item order — let the
    # AI handle it (the multi-item parser) rather than burying a second dish in a note.
    if note:
        tail = await find_dish_matches(session, restaurant_id=restaurant_id, query=note)
        if tail.confidence == MatchConfidence.DIRECT and tail.candidates:
            return False
    if await _catalog_excludes_dish(session, restaurant_id, dish):
        # Typed an item that isn't in the catalogue → answer honestly and
        # deterministically here (never let it fall to the AI, which sometimes
        # re-sends the whole catalogue instead of saying we don't have it).
        # Honest demotion (TX-06, R-023): the dish exists in our records but isn't on
        # the active WhatsApp catalogue — say so plainly and point to the phone, never
        # inject a fake mini-menu or silently drop the request.
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="catalog-typed-unavailable",
            body=(f"Sorry, we don't have {dish.name} on our WhatsApp catalogue right now 🙏 "
                  "It's available by phone — please call us to order it, or tell me "
                  "another dish from our catalogue 😊"),
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
            pin_lat=None, pin_lon=None, distance_km=None, distance_source=None, delivery_fee=None,
        )
    # W2/T6: check whether this dish is already in the cart so we can branch correctly.
    from app.ordering.models import OrderItem as _OI_ck
    from app.ordering.cart_service import CartService, normalize_note
    _any_line = await session.scalar(
        select(_OI_ck.id).where(
            _OI_ck.order_id == order.id,
            _OI_ck.dish_id == dish.id,
        ).limit(1)
    )
    _in_cart = _any_line is not None
    _cs = CartService(session)

    # Branch A: "only/just N dish" + dish already in cart → absolute qty-set (F82/W2).
    # Never clears other cart items; only adjusts this dish to the stated total.
    if is_only_intent and _in_cart:
        await _cs.set_qty(order=order, dish_id=dish.id, qty=add_qty)
        _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
        cart = await _build_cart_summary(session, conv)
        await _record_cart_observation(session, conv)  # F66/W3
        upsell, buttons = await _post_add_extras(session, conv, restaurant_id, order)
        await _send_buttons(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="catalog-typed-set-qty",
            body=f"Got it! {dish.name} updated to {add_qty} ✅{_cart_tail(cart)}{upsell}",
            buttons=buttons,
        )
        return True

    # Branch B: note text present + dish already in cart → update note, no dup (RA-4/W2).
    if note and _in_cart:
        await _cs.set_note(order=order, dish_id=dish.id, raw_note=note)
        _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
        cart = await _build_cart_summary(session, conv)
        await _record_cart_observation(session, conv)  # F66/W3
        upsell, buttons = await _post_add_extras(session, conv, restaurant_id, order)
        await _send_buttons(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="catalog-typed-note",
            body=f"Updated {dish.name}: {normalize_note(note)} ✅{_cart_tail(cart)}{upsell}",
            buttons=buttons,
        )
        return True

    # Branch B2: note + partial in-cart match (e.g. combo line "Chicken Biriyani + Lemon Mint"
    # when customer says "chicken biriyani with double masala").
    if note:
        _alt_dish_id = await _resolve_in_cart_dish_id(session, order.id, dish.name)
        if _alt_dish_id is not None:
            await _cs.set_note(order=order, dish_id=_alt_dish_id, raw_note=note)
            _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
            cart = await _build_cart_summary(session, conv)
            await _record_cart_observation(session, conv)  # F66/W3
            _alt_line = await session.scalar(
                select(_OI_ck.dish_name).where(
                    _OI_ck.order_id == order.id,
                    _OI_ck.dish_id == _alt_dish_id,
                ).limit(1)
            )
            _line_name = _alt_line or dish.name
            upsell, buttons = await _post_add_extras(session, conv, restaurant_id, order)
            await _send_buttons(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="catalog-typed-note-partial",
                body=f"Updated {_line_name}: {normalize_note(note)} ✅{_cart_tail(cart)}{upsell}",
                buttons=buttons,
            )
            return True

    # Default: plain delta-add (existing behaviour).
    await add_item(session, order=order, dish=dish, qty=add_qty, notes=note)
    _set_state(conv, dialogue_phase="ordering", dialogue_state="collecting_items")
    cart = await _build_cart_summary(session, conv)
    await _record_cart_observation(session, conv)  # F66/W3
    note_label = f" — {note}" if note else ""
    upsell, buttons = await _post_add_extras(session, conv, restaurant_id, order)
    await _send_buttons(
        session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
        prefix="catalog-typed-add",
        body=f"Added {add_qty}x {dish.name}{note_label} ✅{_cart_tail(cart)}{upsell}",
        buttons=buttons,
    )
    return True


async def _router_classify_intent(
    session: AsyncSession, conv: Conversation, inbound: InboundMessage
):
    """W4 top-level multilingual router: classify the customer's latest text turn.

    LLM-driven and language-agnostic (no English phrase tables on the live path).
    Returns an ``IntentLabel``.  On any failure — or for non-text inbounds — it
    returns ``UNKNOWN``, which is a MUTATING_INTENT, so the existing engine flow
    is preserved exactly (the router only ever *diverts* clearly non-mutating
    turns away from a silent cart change).
    """
    from app.llm.port import IntentLabel

    if inbound.type != MessageType.TEXT:
        return IntentLabel.UNKNOWN
    text = (inbound.payload.get("text") or "").strip()
    if not text:
        return IntentLabel.UNKNOWN
    phase = _resolve_phase(conv)
    try:
        cart = await _build_cart_summary(session, conv)
    except Exception:  # cart summary is best-effort context only
        cart = ""
    try:
        from app.llm.factory import get_router_classifier

        clf = get_router_classifier()
        return await clf.classify_intent(text, cart or "", phase)
    except Exception:  # never let the router break the pipeline
        _logger.warning("router intent classification failed; falling through",
                        exc_info=True)
        return IntentLabel.UNKNOWN


# Namespace for the per-conversation advisory lock (arbitrary constant, distinct
# from the dispatch/order-number lock namespaces so keys never collide).
_CONV_LOCK_NAMESPACE = 4_919_003


async def _acquire_conversation_lock(
    session: AsyncSession, restaurant_id: int, phone: str
) -> None:
    """Serialize inbound processing per (restaurant, phone) thread (TX-22/TX-46/F94/F115).

    Two near-simultaneous webhook deliveries for the SAME customer (a duplicate
    delivery, a client double-send, or two genuinely separate messages arriving a
    few ms apart — e.g. "No" then "confirm order") must be processed one at a time,
    never interleaved, so cart/state mutations from one turn can never race the
    other's read-modify-write of ``conv.state``. A transaction-scoped Postgres
    advisory lock blocks the second call until the first commits/rolls back;
    auto-released, no extra infra. Best effort — a non-Postgres backend (e.g. a
    narrow unit test against SQLite) just proceeds unserialized.
    """
    import hashlib

    from sqlalchemy import text

    key_bytes = hashlib.blake2b(f"{restaurant_id}:{phone}".encode(), digest_size=4).digest()
    key = int.from_bytes(key_bytes, byteorder="big", signed=True)
    try:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:c, :k)"),
            {"c": _CONV_LOCK_NAMESPACE, "k": key},
        )
    except Exception:  # noqa: BLE001 — non-Postgres backend; proceed without the lock
        _logger.debug("advisory conversation lock unavailable; proceeding unserialized")


async def handle_inbound(
    session: AsyncSession,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Main entry point: load conversation → record message → dispatch state handler."""
    from app.identity.phones import normalize_phone

    _normalized_phone = normalize_phone(inbound.from_phone)
    # Acquire the per-conversation lock BEFORE any read of conv/customer/order state,
    # so a concurrent inbound message for the same phone blocks here until the first
    # message's whole turn (including its commit) has completed (TX-22/TX-46).
    await _acquire_conversation_lock(session, restaurant_id, _normalized_phone)

    counterpart, rider = await _resolve_counterpart(
        session, restaurant_id, inbound.from_phone
    )

    conv = await get_or_create_conversation(
        session,
        restaurant_id=restaurant_id,
        phone=_normalized_phone,
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
    from app.conversation.media import download_inbound_media

    _voice_transcript: str | None = None
    _media_data: bytes | None = None
    _media_mime: str | None = None
    if inbound.type == MessageType.AUDIO:
        _voice_transcript, _media_data, _media_mime = await _download_and_transcribe_voice(
            inbound
        )
    elif inbound.type in {
        MessageType.IMAGE,
        MessageType.DOCUMENT,
        MessageType.VIDEO,
        MessageType.STICKER,
    }:
        _media_data, _media_mime = await download_inbound_media(inbound)

    _record_payload = dict(inbound.payload or {})
    if _voice_transcript:
        _record_payload["text"] = _voice_transcript
    elif inbound.type in {MessageType.IMAGE, MessageType.DOCUMENT, MessageType.VIDEO}:
        caption = (_record_payload.get("caption") or "").strip()
        if caption:
            _record_payload["text"] = caption

    await record_message(
        session,
        conversation_id=conv.id,
        direction="inbound",
        wa_message_id=inbound.wa_message_id,
        msg_type=str(inbound.type),
        payload=_record_payload,
        ts=inbound.timestamp,
        media_data=_media_data,
        media_mime=_media_mime,
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
        # "cancel"/"stop" double as WhatsApp opt-out keywords AND order-cancel
        # words. Order-cancel wins when the customer actually has an order to
        # cancel — treating it as opt-out silently discarded the real intent
        # (prod: cart had 1x Lemon mint, "Cancel" → "unsubscribed from
        # marketing" instead of cancelling the order).
        if _is_kw and _is_cancel_intent(_opt_text):
            _cancel_target = await _resolve_order_for_cancel(
                session, conv, inbound, restaurant_id
            )
            if _cancel_target is not None:
                await _execute_cancel_order(session, conv, inbound, restaurant_id)
                return
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

    # Rider conversations bypass the customer dialogue entirely. Process dispatch
    # actions (location/buttons) even during manual takeover — managers may be
    # chatting while the rider still taps Delivered or shares GPS.
    if counterpart == "rider":
        await _handle_rider_inbound(session, conv, inbound, restaurant_id, rider)
        return

    # Manual takeover: bot is silent, human handles it (customer threads only).
    if conv.manual_takeover:
        return

    # Browse-by-category: taps on the category picker are self-identifying interactive
    # ids, so they work in any dialogue state. Three shapes, all paginated so EVERY dish
    # is reachable by tapping:
    #   cat:<name>            -> first 30 cards of that category
    #   catmore:<offset>:<name> -> next 30 cards of that category ("Show more")
    #   catpage:<n>           -> next page of the category list ("More categories")
    # Only ever fires when the manager enabled the picker (that's how the customer got
    # the list in the first place), so it stays fully revertable.
    if inbound.type in (MessageType.LIST_REPLY, MessageType.BUTTON_REPLY):
        _iid = inbound.payload.get("id") or inbound.payload.get("button_id") or ""
        if _iid.startswith("upsell_add:"):
            _uarg = _iid.split(":", 1)[1]
            if _uarg.isdigit():
                if await _execute_upsell_add(
                    session, conv, inbound, restaurant_id, int(_uarg),
                ):
                    return
            await _handle_top_sellers(session, conv, inbound, restaurant_id)
            return
        if _iid.startswith(("cat:", "catmore:", "catpage:")):
            from app.catalog.service import send_catalog_categories, send_catalog_category

            _ik = f"catbrowse-{conv.id}-{inbound.wa_message_id}"
            if _iid.startswith("catpage:"):
                _pg = _iid[len("catpage:"):]
                await send_catalog_categories(
                    session, restaurant_id=restaurant_id, to_phone=inbound.from_phone,
                    page=int(_pg) if _pg.isdigit() else 0, idempotency_key=_ik,
                )
            elif _iid.startswith("catmore:"):
                _parts = _iid.split(":", 2)  # ["catmore", offset, name]
                _off = _parts[1] if len(_parts) > 1 else "0"
                _cat = _parts[2] if len(_parts) > 2 else ""
                await send_catalog_category(
                    session, restaurant_id=restaurant_id, to_phone=inbound.from_phone,
                    category=_cat, offset=int(_off) if _off.isdigit() else 0,
                    idempotency_key=_ik,
                )
            else:  # cat:<name>
                await send_catalog_category(
                    session, restaurant_id=restaurant_id, to_phone=inbound.from_phone,
                    category=_iid[len("cat:"):], offset=0, idempotency_key=_ik,
                )
            _set_state(conv, dialogue_state="menu_sent")
            return

    # ── Customer conversation (full AI) ────────────────────────────────────
    from app.identity.models import Restaurant as RestaurantModel
    restaurant = await session.get(RestaurantModel, restaurant_id)

    # Kitchen-note clarifications (e.g. "biryani with double masala and chest piece")
    # must run before menu / AI paths so modifiers are never misread as menu requests
    # or split into bogus multi-dish adds (RA-4 / biryani transcript).
    if inbound.type == MessageType.TEXT:
        if await _try_apply_kitchen_note_to_cart(session, conv, inbound, restaurant_id):
            return

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
            await _offer_resume_cart(session, conv, inbound, restaurant_id, draft_order_id=_draft.id)
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

    # Location pin → resale claim (pending fast-deal) or address capture.
    if inbound.type == MessageType.LOCATION:
        if conv.state.get("resale_offer_id"):
            await _handle_resale_location_pin(
                session, conv, inbound, restaurant_id, restaurant,
            )
            return
        phase = _resolve_phase(conv)
        if phase == "address_capture":
            await _handle_location_pin(session, conv, inbound, restaurant_id, restaurant)
            return
        # Pin shared during ordering (before checkout): don't silently drop it (the
        # customer got no reply, then the LLM faked "let me check the distance"). If there
        # is a cart, treat the pin as the delivery location and proceed; otherwise
        # acknowledge honestly and invite an order — deterministic, no LLM improvisation.
        # Other phases (awaiting_confirmation / post_order — e.g. repeated live-location
        # updates after the order is placed) stay silently dropped as before.
        if phase == "ordering":
            from app.ordering.models import Order

            _did = conv.state.get("draft_order_id")
            _order = await session.get(Order, _did) if _did else None
            _has_cart = (
                _order is not None
                and str(_order.status) == "draft"
                and await _order_has_items(session, _order.id)
            )
            _has_coords = (
                restaurant is not None
                and restaurant.lat is not None
                and restaurant.lng is not None
            )
            if _has_cart and _has_coords:
                await _handle_location_pin(session, conv, inbound, restaurant_id, restaurant)
                return
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="loc-ack",
                body=(
                    "Thanks for sharing your location 📍 "
                    + (
                        "Say 'done' when you're ready and I'll use it for delivery 😊"
                        if _has_cart
                        else "Tell me what you'd like to order and I'll work out delivery to you 😊"
                    )
                ),
            )
        return

    # Modify FSM states: route to dedicated handlers (preserves SLA-restart and audit logic)
    state_key = conv.state.get("dialogue_state", "")
    if state_key in ("modify_items", "modify_confirm"):
        # ESCAPE HATCH: a 'Cancel order' tap (often a stale summary button) or a
        # 'cancel' message must cancel the order — not be read as a dish, which
        # trapped the customer in the modify loop with no way out.
        _cancel_btn = (
            inbound.payload.get("id", "") == "cancel_order"
            if inbound.type == MessageType.BUTTON_REPLY
            else False
        )
        _cancel_txt = (
            _is_cancel_intent(inbound.payload.get("text"))
            if inbound.type == MessageType.TEXT
            else False
        )
        if _cancel_btn or _cancel_txt:
            await _handle_cancel_during_modify(session, conv, inbound, restaurant_id)
            return
        # GLOBAL READ-ONLY INTENTS during a modify sub-flow (F103/TX-28/TX-39):
        # 'show menu' and 'what's in my cart' must be answered even mid-modify,
        # instead of being misread as a dish to add/remove. Both are read-only —
        # they reply and RETURN, leaving the modify FSM state untouched so the
        # customer resumes their edit exactly where they left off.
        if inbound.type == MessageType.TEXT:
            _mod_text = (inbound.payload.get("text") or "").strip().lower()
            if _is_menu_request(_mod_text):
                # _send_menu_or_catalog flips dialogue_state to "menu_sent"; the
                # menu is read-only mid-modify, so restore the modify FSM keys
                # afterwards and the customer resumes their edit uninterrupted.
                _mod_snapshot = {
                    k: conv.state.get(k) for k in (
                        "dialogue_phase", "dialogue_state", "modify_order_id",
                        "modify_proposed", "pending_order_id", "draft_order_id",
                    )
                }
                await _send_menu_or_catalog(
                    session, conv, inbound, restaurant_id, prefix="modify-menu",
                )
                _set_state(conv, **_mod_snapshot)
                return
            if _is_cart_query(_mod_text):
                cart = await _build_cart_summary(session, conv)
                await _send_text(
                    session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                    prefix="modify-cart-query",
                    body=(f"🛒 Here's your cart:\n\n{cart}\n\nTell me what to change, "
                          "or send 'done' when you're happy 😊")
                    if cart else
                    "Your cart is empty right now 🛒 Tell me what you'd like to add 😊",
                )
                return
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
        # Post-add quick actions (every added-to-cart confirmation carries these).
        if btn_id == "proceed_delivery":
            await _handle_done_checkout(
                session, conv, inbound, restaurant_id, restaurant=restaurant
            )
            return
        if btn_id.startswith("upsell_add:"):
            _uarg = btn_id.split(":", 1)[1]
            if _uarg.isdigit() and await _execute_upsell_add(
                session, conv, inbound, restaurant_id, int(_uarg),
            ):
                return
            await _handle_top_sellers(session, conv, inbound, restaurant_id)
            return
        if btn_id == "suggest_dishes":
            await _handle_top_sellers(session, conv, inbound, restaurant_id)
            return
        if btn_id == "suggest_done":
            from app.ordering.models import Order as _SuggestDoneOrder

            cart = await _build_cart_summary(session, conv)
            _oid = conv.state.get("draft_order_id")
            _order = await session.get(_SuggestDoneOrder, _oid) if _oid else None
            if _order is not None and cart:
                upsell, buttons = await _post_add_extras(
                    session, conv, restaurant_id, _order,
                )
                body = f"Sounds good! 🛒 {cart}\n\nReady when you are 👇{upsell}"
            else:
                body = "Sounds good! Tell me what you'd like when you're ready 😊"
                buttons = [
                    {"id": "proceed_delivery", "title": "Proceed to delivery"},
                    {"id": "suggest_dishes", "title": "Suggestions"},
                    {"id": "clear_cart", "title": "Clear cart"},
                ]
            await _send_buttons(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="suggest-done", body=body, buttons=buttons,
            )
            return
        if btn_id == "clear_cart":
            from sqlalchemy import delete as sa_delete

            from app.ordering.models import Order as _CcOrder
            from app.ordering.models import OrderItem as _CcItem

            _ccid = conv.state.get("draft_order_id")
            _ccorder = await session.get(_CcOrder, _ccid) if _ccid else None
            if _ccorder is not None and str(_ccorder.status) == "draft":
                await session.execute(
                    sa_delete(_CcItem).where(_CcItem.order_id == _ccorder.id)
                )
                _ccorder.subtotal = Decimal("0.00")
                _ccorder.total = _ccorder.delivery_fee_aed
                await session.flush()
                _set_state(conv, dialogue_state="collecting_items", abandoned_nudged=None)
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="clear-cart-btn",
                body="Cleared your cart 🧹 What would you like to order?",
            )
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

    # Confirm/cancel taps must NEVER round-trip through the LLM (F23): route
    # directly to the deterministic executors regardless of phase/state so a
    # model mis-classification can never block or delay finalizing/cancelling
    # an order the customer has already decided on.
    if inbound.type == MessageType.BUTTON_REPLY:
        _btn_id = inbound.payload.get("id", "")
        if _btn_id == "confirm_order":
            await _execute_confirm_order(session, conv, inbound, restaurant_id)
            return
        if _btn_id == "cancel_order":
            await _execute_cancel_order(session, conv, inbound, restaurant_id)
            return
        # Post-confirm quick actions — same deterministic executors as the typed
        # "where is my order" / "modify my order" intents.
        if _btn_id == "track_order":
            await _handle_status_query(session, conv, inbound, restaurant_id)
            return
        if _btn_id == "modify_order":
            await _handle_modify_intent(session, conv, inbound, restaurant_id)
            return

    # Explicit menu request → render the REAL menu deterministically in ANY phase.
    # Outside the ordering phase the LLM has no show_menu action, so it emits
    # filler like "Sure! Here's our menu 🍛" with no dishes (or fabricates one).
    # After a completed order (post_order) a menu request means "order again", so
    # reset to a fresh ordering session so the next dish pick is valid.
    if inbound.type == MessageType.TEXT:
        text = (inbound.payload.get("text") or "").strip().lower()
        # PDPL data-subject request (access/deletion) → deterministic compliance
        # reply in ANY phase, zero LLM dependency, no state mutation.
        if _is_data_access_request(text):
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="data-access",
                body=_privacy_data_reply(restaurant.name),
            )
            return
        if _is_menu_request(text) and _menu_catalog_intercept_allowed(conv):
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
        # "Do you have any drinks?" → short filtered list or ONE category's catalogue
        # cards — never the full 500-line text menu (LLM / anti-menu guard used to dump it).
        _cat_kw = _parse_category_availability_query(
            (inbound.payload.get("text") or "").strip()
        )
        if _cat_kw:
            await _handle_category_availability_query(
                session, conv, inbound, restaurant_id, _cat_kw,
            )
            return
        # "I want boneless chicken" → short filtered list or ONE category's catalogue
        # cards — never the full menu and never the LLM.
        _dish_kw = _parse_dish_search_query(
            (inbound.payload.get("text") or "").strip()
        )
        if _dish_kw and await _dish_search_is_browse_only(
            session, restaurant_id, _dish_kw,
        ):
            _set_state(conv, browse_filter=_dish_kw)
            await _handle_dish_search(
                session, conv, inbound, restaurant_id, _dish_kw,
            )
            return
        # "OK show me" → full menu; "suggest/recommend" → grounded suggestion sub-agent.
        _raw_browse = (inbound.payload.get("text") or "").strip()
        if (
            _menu_catalog_intercept_allowed(conv)
            and _is_menu_browse_intent(_raw_browse)
            and not _parse_dish_search_query(_raw_browse)
        ):
            _maybe_reset_post_order_for_browse(conv, _raw_browse)
            if _is_suggestion_browse_intent(_raw_browse):
                await _handle_suggestions(session, conv, inbound, restaurant_id)
            else:
                await _handle_menu_browse(session, conv, inbound, restaurant_id)
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
        # "Done" at the confirm step must NOT re-ask for an address that's already on
        # the order (ordering-phase checkout was leaking through the LLM).
        if _resolve_phase(conv) == "awaiting_confirmation" and _is_checkout_shortcut(
            (inbound.payload.get("text") or "").strip()
        ):
            await _handle_confirmation_done(
                session, conv, inbound, restaurant_id, restaurant=restaurant,
            )
            return
        # Bare "ok" / "done" during ordering → checkout before the router/LLM (prod: ack
        # after a kitchen-note edit was hitting the AI and returning a generic error).
        if (
            _resolve_phase(conv) == "ordering"
            and _is_checkout_shortcut(text)
        ):
            from app.ordering.models import Order as _Ord_chk

            _did = conv.state.get("draft_order_id")
            _order = await session.get(_Ord_chk, _did) if _did else None
            if (
                _order is not None
                and str(_order.status) == "draft"
                and await _order_has_items(session, _order.id)
            ):
                await _handle_done_checkout(
                    session, conv, inbound, restaurant_id, restaurant=restaurant,
                )
                return
        # Bare ack ("ok", "thanks") after order confirm — brief reply, never LLM/status.
        if _resolve_phase(conv) == "post_order" and _is_ack_proceed_intent(text):
            await _send_text(
                session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
                prefix="post-order-ack",
                body="Got it! We'll keep you posted 🛵",
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

    # Pitch any ready-now resale (cancelled-after-cooking) food to this customer — ONCE,
    # regardless of how they engage. Previously this only fired on a pure greeting or an
    # explicit menu request, so a customer who typed a direct order (handled below) or
    # chatted with the AI never saw the offer. Idempotent via the resale_offer_id guard;
    # we don't return, so their actual message is still processed right after.
    await _maybe_offer_resale(session, conv, inbound, restaurant_id)

    # ── W4 top-level multilingual router ──────────────────────────────────────
    # Classify the turn (LLM-driven, language-agnostic) BEFORE any cart mutation.
    # A question / complaint / closing / reaction must NEVER reach the
    # deterministic catalogue fast-path (which mutates the cart) — only a genuine
    # mutation (or an UNKNOWN turn, which preserves the legacy flow) may. This
    # closes F49 / F20-A / RA-5: a rhetorical "why did you add 2" or a closing
    # can no longer be silently misread as an add. (Global navigation intents —
    # menu / cart / cancel / clear / tracking — are already intercepted by the
    # deterministic guards above, in every phase.)
    #
    # E-07 audit — router LLM is skipped when deterministic guards already own the
    # turn: pure greetings, menu/cart/tracking/checkout shortcuts, modify FSM,
    # confirm/cancel buttons, category queries, off-topic, dish-info, etc. (all
    # return before this block). One more skip: non-empty cart + done phrase in
    # ordering → checkout without spending a router call.
    from app.llm.port import IntentLabel, MUTATING_INTENTS

    _router_phase = _resolve_phase(conv)
    _router_intent = IntentLabel.UNKNOWN
    _router_text = (
        (inbound.payload.get("text") or "").strip()
        if inbound.type == MessageType.TEXT
        else ""
    )
    _skip_router = False
    if (
        inbound.type == MessageType.TEXT
        and _router_phase == "ordering"
        and _is_done_intent(_router_text)
    ):
        from app.ordering.models import Order as _Ord_router

        _did = conv.state.get("draft_order_id")
        _order = await session.get(_Ord_router, _did) if _did else None
        if (
            _order is not None
            and str(_order.status) == "draft"
            and await _order_has_items(session, _order.id)
        ):
            _skip_router = True
            _router_intent = IntentLabel.CHECKOUT

    if not _skip_router:
        _router_intent = await _router_classify_intent(session, conv, inbound)
    elif _router_intent == IntentLabel.CHECKOUT:
        await _handle_done_checkout(
            session, conv, inbound, restaurant_id, restaurant=restaurant,
        )
        return

    # Catalogue mode: remove / set-qty edits first (typed-order only ADDS), then a
    # clearly-typed single dish is ADDED deterministically so "one chicken biryani"
    # reliably goes to the cart instead of the model re-sending catalogue cards.
    #
    # W4 phase-gate: the typed-add fast-path only runs in the ORDERING phase AND
    # only for a mutating intent. Outside ordering (address_capture /
    # awaiting_confirmation / post_order) a typed dish is a correction/edit that
    # the phase-aware AI flow must own, not a silent catalogue add (F49/F20-A/RA-5).
    if await _try_apply_kitchen_note_to_cart(session, conv, inbound, restaurant_id):
        return

    if await _try_catalog_cart_edit(session, conv, inbound, restaurant_id, restaurant):
        return

    if (
        _router_phase == "ordering"
        and _router_intent in MUTATING_INTENTS
        and await _try_catalog_typed_order(
            session, conv, inbound, restaurant_id, restaurant
        )
    ):
        return

    # A clear order for an OFF-MENU dish always gets the warm decline here, so the
    # LLM can't sometimes mis-route it to clear_cart / modify (a valid dish is never
    # intercepted — it falls through to the AI unchanged).
    if await _maybe_decline_off_menu_order(session, conv, inbound, restaurant_id):
        return

    # Post-confirm item edits ("cancel chicken biriyani", "only lemon mint") — deterministic
    # so the LLM can't start modify on a stale order id or treat "only X" as checkout done.
    if await _try_post_order_item_edit(session, conv, inbound, restaurant_id):
        return

    # E-17: ToT-lite branch when the router could not classify the turn.
    if _router_intent == IntentLabel.UNKNOWN and inbound.type == MessageType.TEXT:
        if await _apply_tot_lite_branch(
            session, conv, inbound, restaurant_id, restaurant,
            text=_router_text, phase=_router_phase,
        ):
            return

    # E-21: vague short messages with no dish match → clarifying question (no LLM).
    if await _maybe_clarify_vague_inbound(
        session, conv, inbound, restaurant_id, router_intent=_router_intent,
    ):
        return

    # All remaining text + button_reply → AI
    await _handle_customer_ai(session, conv, inbound, restaurant_id, restaurant)
