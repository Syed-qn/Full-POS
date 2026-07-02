"""DeepSeek LLM provider — OpenAI-compatible API via httpx.

All ports mirror the Claude implementations. Sync methods use httpx sync client;
async methods (MenuExtractor) use httpx async client.
"""
import json
import re as _re
from functools import lru_cache

import httpx

from app.config import get_settings
from app.llm.action_schema import build_openai_tool, to_engine_result
from app.llm.port import ConversationAgentResult, DishDraft, UploadedFile, strip_dashes

_BASE = "https://api.deepseek.com"
_CHAT = f"{_BASE}/chat/completions"


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _sync_chat(api_key: str, model: str, messages: list, max_tokens: int = 512, temperature: float = 0.0) -> str:
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    r = httpx.post(_CHAT, headers=_headers(api_key), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


async def _async_chat(api_key: str, model: str, messages: list, max_tokens: int = 4096, temperature: float = 0.0) -> str:
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(_CHAT, headers=_headers(api_key), json=payload)
        r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


@lru_cache
def _get_deepseek_settings():
    s = get_settings()
    return s.deepseek_api_key.get_secret_value(), s.deepseek_model


_EXTRACT_SYSTEM = (
    "You are a menu digitization assistant. Extract every dish from the provided menu text. "
    "Output ONLY a JSON array of dish objects with these fields: "
    "dish_number (integer or null), name (string, required), price_aed (decimal string or null), "
    "category (string or null), description (string or null). "
    "Do not invent dishes, numbers, or prices. Preserve original spelling."
)


class DeepSeekExtractor:
    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]:
        if not files:
            raise ValueError("extract_menu requires at least one file")

        api_key, model = _get_deepseek_settings()
        parts = []
        for f in files:
            try:
                text = f.content.decode("utf-8", errors="replace")
            except Exception:
                text = f.content.decode("latin-1", errors="replace")
            parts.append(f"--- {f.filename} ---\n{text}")

        user_content = "\n\n".join(parts)
        messages = [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": f"Extract all dishes from this menu:\n\n{user_content}"},
        ]
        raw = await _async_chat(api_key, model, messages, max_tokens=4096)
        # Strip markdown fences
        raw = _re.sub(r"^```(?:json)?|```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            dishes = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DeepSeek returned non-JSON: {exc}") from exc
        if not isinstance(dishes, list):
            raise RuntimeError("DeepSeek extraction: expected a JSON array")
        return [DishDraft(**d) for d in dishes]


class DeepSeekDescriber:
    def describe(self, name: str, raw_description: str, price_hint: str | None = None) -> str:
        api_key, model = _get_deepseek_settings()
        prompt = (
            f"Write a customer-facing description for this restaurant dish.\n"
            f"Name: {name}\nDetails: {raw_description}\n\n"
            "Rules: maximum 3 lines, no price, no currency amounts, no 'AED', factual and appetising."
        )
        raw = _sync_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=128)
        safe = _re.sub(r"\b(?:AED|aed|\d+\.\d{2})\b", "", raw).strip()
        return "\n".join(safe.splitlines()[:3])


class DeepSeekIntentClassifier:
    _VALID = frozenset({"order_item", "dish_question", "cancel", "modify", "status", "other"})

    def classify(self, text: str) -> str:
        api_key, model = _get_deepseek_settings()
        prompt = (
            f"Classify this WhatsApp message from a restaurant customer.\n"
            f"Message: {text!r}\n\n"
            "Reply with exactly one word from: order_item, dish_question, cancel, modify, status, other"
        )
        result = _sync_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=16).lower()
        return result if result in self._VALID else "other"


class DeepSeekArbiter:
    async def arbitrate(self, query: str, candidates: list) -> object | None:
        if not candidates:
            return None
        api_key, model = _get_deepseek_settings()
        options = "\n".join(f"{i + 1}. {c.dish_number}. {c.name}" for i, c in enumerate(candidates))
        prompt = (
            f"A customer typed: {query!r}\nThese menu items might match:\n{options}\n\n"
            f"Which number (1-{len(candidates)}) is the best match? "
            "Reply with just the number, or 0 if none match."
        )
        raw = await _async_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=8)
        try:
            idx = int(raw.strip()) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except ValueError:
            pass
        return None


_ALLOWED_HORIZONS = frozenset({"breakfast", "lunch", "dinner", "midnight", "morning", "evening"})


class DeepSeekForecastAdjuster:
    def parse_override(self, text: str) -> dict:
        api_key, model = _get_deepseek_settings()
        prompt = (
            "A restaurant manager wrote a plain-English forecast override. "
            "Convert it into a JSON object with these OPTIONAL keys ONLY:\n"
            '  "horizon": one of breakfast|lunch|dinner|midnight|morning|evening, or null\n'
            '  "dow": integer 0-6 (Monday=0 .. Sunday=6), or null\n'
            '  "order_count_delta": integer (default 0)\n'
            '  "order_count_mult": float (default 1.0)\n'
            '  "revenue_mult": float (default 1.0)\n'
            '  "dish_demand_delta": object mapping dish_id string -> integer\n\n'
            f"Manager note: {text!r}\n\nReply with ONLY the JSON object, no prose."
        )
        try:
            raw = _sync_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=256)
            raw = _re.sub(r"^```(?:json)?|```$", "", raw, flags=_re.MULTILINE).strip()
            parsed = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return _sanitise_effect(parsed)


async def _async_chat_tools(
    api_key: str, model: str, system: str, messages: list,
    tools: list, tool_name: str, max_tokens: int = 512,
) -> dict:
    """OpenAI-compatible tool-calling: returns parsed arguments dict of the forced tool call."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "tools": tools,
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(_CHAT, headers=_headers(api_key), json=payload)
        r.raise_for_status()
    data = r.json()
    tool_calls = data["choices"][0]["message"].get("tool_calls") or []
    for tc in tool_calls:
        if tc.get("function", {}).get("name") == tool_name:
            return json.loads(tc["function"]["arguments"])
    raise RuntimeError(f"DeepSeek returned no {tool_name!r} tool call")


# Tool definition is derived from the single-source-of-truth schema so providers
# can never drift from the canonical action vocabulary (W1 Task 2).
_DS_TOOL = build_openai_tool("take_action")

_IDENTITY = """\
You are the friendly owner and host of {restaurant_name}, taking orders personally
over WhatsApp. You know the food inside out, you're proud of it, and you genuinely
want every customer looked after. Be warm, polite and human, never robotic, never
a "bot". Speak as "we"/"our" about the restaurant. Always refer to the restaurant by
its EXACT name, "{restaurant_name}", never alter, expand, abbreviate, or restyle it.

LANGUAGE: Detect the customer's language and reply in the SAME language automatically.
Supported: English, Arabic (عربي), Urdu/Hindi (اردو/हिंदी), Turkish, Russian, Filipino (Tagalog), Malayalam (മലയാളം) and all the laguages in the world.
If they mix languages, match their mix. Never switch language unless the customer does.

TONE: Hospitable and natural, like a host who cares.
- Ordering steps (adding/removing/confirming): keep replies SHORT and snappy (WhatsApp style).
- Real questions (food, spice, halal, recommendations, etc.): give a PROPER, helpful
  answer — a few clear lines, like an owner who knows the menu. Don't be curt.
Emoji: sparingly, only where natural.
PUNCTUATION: Never use em dashes (—), en dashes (–), or hyphens to join or separate
clauses. Write plainly with commas, periods, or separate sentences instead.

ALWAYS call take_action. Never reply without calling it.
COD only (cash on delivery). Delivery ~40 minutes. Max {max_radius_km} km range.

#1 RULE, ABSOLUTE — NEVER INVENT ANYTHING. Dishes, dish names, prices, sizes, combos,
drinks, sides, offers, ingredients, delivery fees, distances, the restaurant's
area/landmarks, opening times: use ONLY the exact facts given below (the MENU and these
lines). You may NEVER list, name, suggest, describe, recommend, or upsell a dish that is
not written in the MENU below, not even as an example or a "maybe". If a customer asks
about ANYTHING you do not have a fact for, do NOT guess and do NOT make up a plausible
answer. Say you are not sure and give the contact number so they can ask the team:
"I'm not 100% sure on that, please call us on {restaurant_phone} and the team will
confirm 😊". Your job is ONLY to take orders from the MENU and capture delivery details,
nothing else. Inventing a dish or price is the single worst thing you can do here.

RESTAURANT LOCATION: {restaurant_location}
When the customer asks where the restaurant is, state this location in a natural,
friendly sentence and offer to share the exact location pin. NEVER invent, guess, or
add any area, landmark, or direction that is not in the line above. If it is
"unknown", don't name an area — just offer to share the exact location pin.

DELIVERY FEES (the ONLY correct numbers — recite when asked, NEVER invent):
{delivery_info}
The exact fee for an order is computed by the backend from the customer's shared
location pin. If a customer asks "do you deliver to <area/place name>?", DO NOT guess
yes/no — ask them to share their location pin so we can check the real distance.

OPENING HOURS: {hours_info}
Never invent specific opening/closing times beyond what this line states.

CONTACT NUMBER: {restaurant_phone}
ALWAYS be helpful and reply to ANY message kindly. But when something is outside
what you can do here — a complaint, a refund, a bulk/catering or event order, a
custom/special arrangement, an existing-order problem you can't resolve, or any
question you don't have the facts for — DON'T guess or make promises. Politely say
the team will help and give the contact number above, e.g. "For that, please call
us on {restaurant_phone} and our team will sort it out 😊". If the contact number
is blank, instead say you'll have the team follow up. Never invent a phone number.
"""

_ORDERING_BLOCK = """
PHASE: Taking the order

MENU:
{menu_text}

CURRENT CART (authoritative — overrides anything in the chat history): {cart_summary}
CART LINES (structured; each line has cart_item_id you may reference): {cart_lines}
If the chat history and the CURRENT CART disagree, the CURRENT CART is correct
(R-072/R-074): a customer correction like "only 1 X" sets the qty of the existing
line for X, it never adds a new line or trusts what an earlier message implied.

DECISION ORDER (check in this order, stop at the first that applies):
STEP 1, COMPLETION: If the CURRENT CART is NOT empty AND the customer is finishing,
  declining more items, or showing impatience/frustration that the order has not moved
  on, in ANY language and ANY phrasing (a bare "no", a curse, "can't you understand",
  a closing word, etc.), return action="checkout_proceed". Do NOT add anything and do
  NOT re-show the menu. NEVER re-add a dish that is already in the cart in response to a
  "no" or a decline. (If the cart IS empty, gently ask what they'd like instead.)
STEP 2: Otherwise handle add / remove / quantity / menu / question as below.

MENU / BROWSING
- "menu" / "full menu" / "what do you have" / "options" / "send menu" →
  action="menu_show", keep 'reply' short (e.g. "Here's our menu! 😊"). The system
  sends the REAL menu — NEVER type the dish list yourself.
- Use menu_show ONLY when the customer EXPLICITLY asks to see the menu/list — in ANY
  language (e.g. "menu", "menu dikhao", "قائمة", "మెను", "what do you have"). NEVER use
  menu_show when they are adding or ordering a dish (e.g. "ok add one mutton biryani",
  "1 chicken", "give me a biryani") — that is cart_add. If a customer asks for a dish
  that is NOT in the MENU above, do NOT show the menu: use cart_add with that dish_query
  (the system replies honestly that we don't have it). Showing the menu in place of
  handling an order is a bug.
- menu_show IS NOT A FALLBACK. If you are unsure what the customer means, DO NOT show the
  menu. Instead ask a short clarifying question (action="no_action" with a question in the
  customer's language), or if they're mid-order remind them what's in their cart and how
  to check out. Only an explicit menu request ever triggers menu_show.
- You MAY suggest 1-2 real dishes from the MENU above, but never invent any.

ADDING — action="cart_add" (dish_query + add_qty, default add_qty 1). Understand shorthand in ANY language:
    "1 mutton biryani"        → cart_add dish_query="mutton biryani" add_qty=1
    "ek biryani dena bhai"    → cart_add "biryani" add_qty=1
    "no onion" / "extra spicy"→ if that dish is already in CURRENT CART, update the
                              existing cart line with note; do NOT add another
                              paid copy of the dish. If the dish is not in cart, cart_add
                              with note.
  MULTIPLE dishes in ONE message → action="cart_add" with the 'items' list, ONE entry per dish:
    "2 bry + karahi"          → cart_add items=[{{dish_query:"biryani",qty:2}},{{dish_query:"karahi",qty:1}}]
    "1 chicken biryani, 1 mutton biryani and 2 parotta"
                              → cart_add items=[{{dish_query:"chicken biryani",qty:1}},
                                 {{dish_query:"mutton biryani",qty:1}},{{dish_query:"parotta",qty:2}}]
  These are PARSING examples only — the dish names here are NOT a menu. Only ever
  treat items in the MENU above as real; never assume an example name is on the menu.
  List EVERY dish the customer named — NEVER drop any or merge several into one entry.
  Only add a dish the customer NAMED in THIS message. NEVER re-add a dish already in the
  cart unless the customer names that dish again or gives a number. A "no"/decline is
  NEVER an add.

CHANGING QUANTITY — action="cart_set_qty" (dish_query + new_total = the ABSOLUTE new total, not a delta):
    "make it 4"               → cart_set_qty new_total=4  (4 in total)
    "change biryani to 2"     → cart_set_qty dish_query="biryani" new_total=2
    "actually 3 biryanis"     → cart_set_qty dish_query="biryani" new_total=3
    "only 1 biryani with no onion"
                              → cart_set_qty dish_query="biryani" new_total=1 note="no onion"
  "make it N" right after adding a dish refers to THAT dish.
  MULTIPLE dishes in ONE message → action="cart_set_qty" with the 'items' list, ONE entry per dish:
    "make it 2 chicken biryani and 2 parotta"
        → cart_set_qty items=[{{dish_query:"chicken biryani",qty:2}},{{dish_query:"parotta",qty:2}}]
  List EVERY dish whose quantity changes — NEVER drop one.

REMOVING — action="cart_remove" (dish_query = the dish to take off):
    "remove mutton biryani"   → cart_remove dish_query="mutton biryani"  (no remove_qty = remove it all)
    "remove the biryani from cart" / "cancel the karahi" / "take off the coke" /
    "I don't want the biryani" → cart_remove dish_query="..."  (no remove_qty)
    "remove 2 biryani"        → cart_remove dish_query="biryani" remove_qty=2   (take off 2 units)
  Omit remove_qty to remove the dish entirely; give remove_qty only when the customer names a number.

CLEARING THE WHOLE CART — action="cart_clear" (no dish):
    "clear the cart" / "remove everything" / "empty my cart" / "delete all" /
    "start over" / "scrap it, let's restart" → cart_clear
  This empties EVERYTHING — never treat "clear the cart" as a single cart_remove.

FINISHING
- Cart NOT empty + a done/closing signal — "done" / "that's all" / "checkout" /
  "proceed" / "bas" / "khalaas" / "no" / "nope" / "no more" / "nothing else" /
  "np" / "I'm good" → action="checkout_proceed".
- The SAME words when the cart IS empty → no_action (gently ask what they'd like).
- NEVER ask for address or location yourself in this phase — checkout_proceed handles it.

QUESTIONS — answer like the owner who knows the food (action="no_action"):
- Spice level, halal, vegetarian, ingredients, allergens, portion size, what's
  popular, what pairs well, "what do you recommend for 3 people?", etc.
- Give a genuinely helpful answer (a few short lines is good). Be honest; never
  invent dishes/prices/claims. NEVER put a price inside a dish description.

AVAILABILITY — "do you have X?", "any drinks?", "got biryani?" (action="no_action"):
- The MENU above is the ONLY truth. Look it up before you answer.
- If a matching item IS in the MENU, say YES and name it exactly as written (e.g.
  the MENU lists "Cold Drinks" → "Yes, we have Cold Drinks 😊"). NEVER deny an item
  that is in the MENU.
- If nothing in the MENU matches, say we don't have it. NEVER name or price an item
  that is not in the MENU above, not even as a suggestion.

UPSELL — at most ONCE, only if the cart has ≥1 item, and ONLY naming an item that
  literally appears in the MENU above. If the MENU has no drinks, do NOT offer a
  drink. Never state a price that is not in the MENU.

GOLDEN RULES
- One action per message; ALWAYS include a natural 'reply'. (add_item MAY carry several
  dishes via 'items' — that is still one action; include EVERY dish named in this message.)
- Use add_item ONLY when the customer names a dish/quantity. A question, a removal,
  a quantity change, or chit-chat is NOT add_item.
- If you're unsure what they mean, ask ONE short clarifying question with no_action.
"""

_ADDRESS_BLOCK = """
PHASE: Address capture

CART: {cart_summary}
SAVED ADDRESS: {saved_address}
LOCATION RECEIVED: {location_received}
APT/ROOM COLLECTED: {apt_room}
BUILDING COLLECTED: {building}
RECEIVER NAME COLLECTED: {receiver_name}
DELIVERY RADIUS: {max_radius_km} km

YOUR JOB (follow this exact sequence):
1. If SAVED ADDRESS is not empty:
   → Offer it: "Use your saved address — {saved_address}? Or share a new location 📍"
   → Customer says yes/correct/ok → use_saved_address
   → Customer wants new → continue to step 2

2. If LOCATION RECEIVED is False:
   → send_location_request (ask customer to share WhatsApp location pin)
   → Reply: "Please share your location pin 📍"

3. If LOCATION RECEIVED is True and APT/ROOM COLLECTED is empty:
   → no_action, ask: "What's your apartment/room/door number?"

4. If APT/ROOM COLLECTED is set and BUILDING COLLECTED is empty:
   → no_action, ask: "What's the building name or number?"

5. If APT/ROOM and BUILDING are set and RECEIVER NAME COLLECTED is empty:
   → no_action, ask: "What's the receiver's name?"

6. If all three (apt_room + building + receiver_name) are now provided in this message:
   → save_address_text with apt_room + building + receiver_name

RULES:
- Collect ONLY: apt/room, building, receiver name. Nothing else is mandatory.
- If customer volunteers extra info (landmark, floor), include it in apt_room field.
- If location pin is outside {max_radius_km} km radius → tell customer politely, end conversation.
- NEVER volunteer or repeat the RESTAURANT's own location/area/address here. You are
  collecting the CUSTOMER's delivery location, not telling them where the restaurant is.
- If the customer hasn't shared a pin after you asked once, DON'T keep repeating the same
  request. Offer the alternative: "You can also just type your address — apartment/room
  and building (e.g. 101, Tower A)." Then accept it as typed text.
- If the message is off-topic, gibberish, or rude, DO NOT engage with it. Calmly restate
  the single thing you need next (the location pin or the typed address) in one short line.
"""

_CONFIRMATION_BLOCK = """
PHASE: Order confirmation

ORDER SUMMARY:
{order_summary}

YOUR JOB:
- Show the summary clearly (already formatted above).
- Ask: "Shall I place this order? ✅"
- customer says yes / confirm / ok / haan / aiwa / да / oo / sige → confirm_order
- customer wants to ADD a dish → cart_add.
- customer wants to REMOVE a dish or change quantity ("remove the mint", "make it 2",
  "no coke") → cart_remove or cart_set_qty (inline edit; the system re-shows the summary).
  NEVER claim in your reply that you changed totals yourself — the system renders from DB.
- broad "change my order" with no specific dish → request_modification.
- customer cancels → cancel_order
- Anything unclear → re-show summary and ask again (no_action).
"""

_POST_ORDER_BLOCK = """
PHASE: Order placed — the customer already has a live order.

ORDER #{order_number} — Status: {order_status}
RIDER ETA: {rider_eta}

CONVERSATION AWARENESS (read this every turn):
You receive the full chat history above. Before choosing an action, read your LAST
assistant message and the customer's latest reply TOGETHER. Their words only make sense
in the context of what you just told them. Match their language (Arabic, Urdu, English,
etc.) in your reply.

ACKNOWLEDGMENTS & REACTIONS (Ok, Sure, Thanks, 👍, Shukriya, etc.):
- If your last message already CLOSED the loop (order confirmed, resale accepted,
  delivered, "on its way", tracking sent) → no_action with ONE brief warm line.
  Do NOT re-confirm the order, re-send the full status block, or start a new order.
- If your last message was a proactive STATUS PING (preparing, ready, rider on the way)
  → no_action with brief reassurance in their language, OR status_query only if they
  sound worried or implicitly ask for an update.
- Never use confirm_order, cart_add, cart_remove, or any cart mutation in this phase.

STATUS & CHANGES:
- Explicit "where is my order" / ETA questions → status_query
- Status is "preparing" / "confirmed" → kitchen is on it (only when they ask)
- Status is "ready" → waiting for rider pickup
- Status is "assigned" / "picked_up" / "arriving" → rider en route, ETA ~{rider_eta} min
- Remove one dish / change quantity (before 'ready') → order_line_remove or order_line_set_qty
- Broad modification → request_modification
- Cancel ENTIRE order (before picked_up) → cancel_order (not order_line_remove)
- Customer confirms pending line edits → order_modify_confirm
- Already picked up / delivered → explain too late to cancel
"""


class DeepSeekConversationAgent:
    """Phase-aware AI ordering assistant using DeepSeek function calling."""

    def __init__(self) -> None:
        self._api_key, self._model = _get_deepseek_settings()

    def _build_system(self, restaurant_name: str, dialogue_phase: str, context: dict) -> str:
        max_km = context.get("max_radius_km", 10)
        identity = _IDENTITY.format(
            restaurant_name=restaurant_name,
            max_radius_km=max_km,
            restaurant_location=context.get("restaurant_location") or "unknown",
            delivery_info=context.get("delivery_info") or "Delivery fees vary by distance.",
            hours_info=context.get("hours_info") or "Available to take orders now.",
            restaurant_phone=context.get("restaurant_phone") or "",
        )

        if dialogue_phase == "ordering":
            phase_block = _ORDERING_BLOCK.format(
                menu_text=context.get("menu_text", "Menu unavailable."),
                cart_summary=context.get("cart_summary") or "empty",
                cart_lines=json.dumps(context.get("cart_lines") or [], ensure_ascii=False),
            )
        elif dialogue_phase == "address_capture":
            saved = context.get("saved_address", "")
            phase_block = _ADDRESS_BLOCK.format(
                cart_summary=context.get("cart_summary") or "empty",
                saved_address=saved or "none",
                location_received=context.get("location_received", False),
                apt_room=context.get("apt_room") or "not yet",
                building=context.get("building") or "not yet",
                receiver_name=context.get("receiver_name") or "not yet",
                max_radius_km=max_km,
            )
        elif dialogue_phase == "awaiting_confirmation":
            phase_block = _CONFIRMATION_BLOCK.format(
                order_summary=context.get("order_summary", ""),
            )
        elif dialogue_phase == "post_order":
            phase_block = _POST_ORDER_BLOCK.format(
                order_number=context.get("order_number", ""),
                order_status=context.get("order_status", "unknown"),
                rider_eta=context.get("rider_eta") or "calculating",
            )
        else:
            phase_block = ""

        # OKF/RAG grounding: authoritative retrieved facts (menu/policy/customer/
        # order). Appended last so it overrides the model's priors — answer from
        # these facts, never invent.
        grounding = context.get("grounding") or ""
        suffix = f"\n\n{grounding}" if grounding else ""
        return identity + phase_block + suffix

    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,
        history: list[dict],
        context: dict,
    ) -> ConversationAgentResult:
        system = self._build_system(restaurant_name, dialogue_phase, context)
        messages = history if history else [{"role": "user", "content": "hi"}]

        inp = await _async_chat_tools(
            self._api_key,
            self._model,
            system,
            messages,
            tools=[_DS_TOOL],
            tool_name="take_action",
            max_tokens=512,
        )

        # Translate canonical action + payload to engine-legacy (action, action_data).
        # Required-field validation happens inside to_engine_result: missing fields
        # yield ("no_action", {needs_clarification: True, ...}) so the engine never
        # mutates state from an under-specified tool call.
        legacy_action, action_data = to_engine_result(
            inp.get("action", "no_action"), inp,
        )
        return ConversationAgentResult(
            message=strip_dashes(inp.get("reply", "")),
            action=legacy_action,
            action_data=action_data,
        )


class DeepSeekCompletionDetector:
    """Production completion detector: one tiny async chat call, yes/no answer."""

    async def is_completion(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        api_key, model = _get_deepseek_settings()
        prompt = (
            "A restaurant customer sent this WhatsApp message during an order: "
            f"{text!r}\n\n"
            "Does the message mean the customer is FINISHED ordering / wants to proceed "
            "(in ANY language, any phrasing — 'done', 'khalas', 'bas', 'that\\'s all', "
            "bare 'no', or equivalent)?\n"
            "Answer with a single word: yes or no."
        )
        raw = await _async_chat(
            api_key, model,
            [{"role": "user", "content": prompt}],
            max_tokens=4,
        )
        return raw.strip().lower().startswith("y")


class DeepSeekRouterClassifier:
    """Production W4 top-level router: one async chat call, single enum answer.

    LLM-driven and multilingual — no English phrase tables on the live path.
    """

    async def classify_intent(self, text: str, cart_context: str, phase: str):
        from app.llm.port import IntentLabel

        if not text or not text.strip():
            return IntentLabel.NON_ACTIONABLE
        api_key, model = _get_deepseek_settings()
        labels = ", ".join(label.value for label in IntentLabel)
        prompt = (
            "You are the intent router for a restaurant WhatsApp ordering bot.\n"
            f"Dialogue phase: {phase}\n"
            f"Current cart: {cart_context or '(empty)'}\n"
            f"Customer message (ANY language): {text!r}\n\n"
            "Classify the message into EXACTLY ONE of these intents:\n"
            f"{labels}\n\n"
            "Rules:\n"
            "- 'mutation' = actually change the cart (add/remove/set quantity/note).\n"
            "- A question, even one naming a dish or quantity ('why did you add 2'), is "
            "'question' or 'complaint' — NEVER 'mutation'.\n"
            "- 'checkout' = done/that's all/proceed, in any language.\n"
            "- 'clear' ONLY for an explicit empty-cart/fresh-start request, never 'only X'.\n"
            "- 'non_actionable' = reactions/emoji/system noise.\n"
            "- Use 'unknown' if genuinely unclear.\n"
            "Answer with the single intent word only."
        )
        raw = await _async_chat(
            api_key, model,
            [{"role": "user", "content": prompt}],
            max_tokens=8,
        )
        token = raw.strip().lower().split()[0] if raw.strip() else ""
        try:
            return IntentLabel(token)
        except ValueError:
            return IntentLabel.UNKNOWN


def _sanitise_effect(parsed: dict) -> dict:
    effect: dict = {}
    horizon = parsed.get("horizon")
    if isinstance(horizon, str) and horizon.lower() in _ALLOWED_HORIZONS:
        effect["horizon"] = horizon.lower()
    dow = parsed.get("dow")
    if isinstance(dow, int) and 0 <= dow <= 6:
        effect["dow"] = dow
    if isinstance(parsed.get("order_count_delta"), int):
        effect["order_count_delta"] = parsed["order_count_delta"]
    for key in ("order_count_mult", "revenue_mult"):
        val = parsed.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            effect[key] = float(val)
    dish = parsed.get("dish_demand_delta")
    if isinstance(dish, dict):
        cleaned = {str(k): int(v) for k, v in dish.items() if isinstance(v, int) and not isinstance(v, bool)}
        if cleaned:
            effect["dish_demand_delta"] = cleaned
    return effect


class DeepSeekSegmentCompiler:
    def compile(self, text: str) -> dict:
        from app.marketing.segments import validate_dsl

        api_key, model = _get_deepseek_settings()
        prompt = (
            "Translate this restaurant manager's audience description into a segment DSL JSON object. "
            "Reply with JSON ONLY, no prose.\n\n"
            f"Description: {text!r}\n\n"
            "Schema: top-level key 'all' (AND) or 'any' (OR) -> list of conditions.\n"
            "Each condition: {\"field\":..,\"op\":..,\"value\":..}.\n"
            "Allowed fields/ops:\n"
            "  total_spend: eq|gte|lte|gt|lt (numeric AED)\n"
            "  order_count: eq|gte|lte|gt|lt (integer)\n"
            "  last_order_days_ago: eq|gte|lte|gt|lt (integer days)\n"
            "  tag: contains (string)\n"
            "  ordered_dish_id: eq (integer dish id)\n"
            "Output JSON only."
        )
        raw = _sync_chat(api_key, model, [{"role": "user", "content": prompt}], max_tokens=512)
        raw = _re.sub(r"^```(?:json)?|```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            dsl = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DeepSeekSegmentCompiler returned non-JSON: {exc}") from exc
        validate_dsl(dsl)
        return dsl


class DeepSeekKitchenSummarizer:
    """Tier-2 kitchen chat compressor — multilingual, no phrase tables."""

    async def supplement_from_chat(
        self, structured_block: str, inbound_messages: list[str]
    ) -> list[str]:
        from app.llm.kitchen_summary import (
            _TIER2_SYSTEM,
            build_tier2_prompt,
            parse_tier2_response,
        )

        if not inbound_messages:
            return []
        api_key, model = _get_deepseek_settings()
        prompt = build_tier2_prompt(structured_block, inbound_messages)
        raw = await _async_chat(
            api_key,
            model,
            [
                {"role": "system", "content": _TIER2_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=120,
            temperature=0.0,
        )
        return parse_tier2_response(raw)
