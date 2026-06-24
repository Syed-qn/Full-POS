"""DeepSeek LLM provider — OpenAI-compatible API via httpx.

All ports mirror the Claude implementations. Sync methods use httpx sync client;
async methods (MenuExtractor) use httpx async client.
"""
import json
import re as _re
from functools import lru_cache

import httpx

from app.config import get_settings
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


_DS_TOOL = {
    "type": "function",
    "function": {
        "name": "take_action",
        "description": (
            "Record the structured action inferred from the customer message, plus your reply. "
            "ALWAYS call this tool — never reply without it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "add_item", "remove_item", "update_qty", "proceed_to_address",
                        "send_location_request", "save_address_text", "use_saved_address",
                        "proceed_to_confirmation",
                        "confirm_order", "request_modification", "cancel_order",
                        "status_query", "show_menu", "no_action",
                    ],
                    "description": (
                        "show_menu: customer asks to see the menu/dishes/prices — the "
                        "system sends the REAL menu, so do NOT write dishes in 'reply'. "
                        "add_item: customer NAMES a dish to add. "
                        "remove_item: customer wants a dish taken OFF the cart entirely "
                        "('remove X', 'cancel the X', 'take off X', 'I don't want X'). "
                        "update_qty: change the quantity of a dish already in the cart "
                        "('make it 4', 'change to 2', 'actually 3') — qty is the new TOTAL. "
                        "proceed_to_address: cart ready, move to delivery address capture. "
                        "send_location_request: ask customer to share their WhatsApp location pin. "
                        "save_address_text: all 3 address fields collected (apt_room + building + receiver_name). "
                        "use_saved_address: returning customer confirmed their saved address. "
                        "proceed_to_confirmation: address complete, show order summary. "
                        "confirm_order: customer confirmed the order. "
                        "request_modification: customer wants to change something in the order. "
                        "cancel_order: customer wants to cancel. "
                        "status_query: customer asked where their order is. "
                        "no_action: greeting, question, answer, anything that doesn't change state."
                    ),
                },
                "dish_query": {
                    "type": "string",
                    "description": (
                        "Dish name or number the customer referred to "
                        "(for add_item, remove_item, update_qty)."
                    ),
                },
                "qty": {
                    "type": "integer",
                    "description": (
                        "For add_item: how many to add (default 1). "
                        "For update_qty: the NEW TOTAL quantity, not a delta "
                        "(e.g. 'make it 4' → qty=4). "
                        "For remove_item: how many units to take off; OMIT it to "
                        "remove the dish entirely ('remove 2 biryani' → qty=2; "
                        "'remove the biryani' → no qty)."
                    ),
                },
                "special_note": {
                    "type": "string",
                    "description": "Kitchen note e.g. 'no onion', 'extra spicy' (for add_item).",
                },
                "apt_room": {
                    "type": "string",
                    "description": "Apartment / room / door number (for save_address_text).",
                },
                "building": {
                    "type": "string",
                    "description": "Building name or number (for save_address_text).",
                },
                "receiver_name": {
                    "type": "string",
                    "description": "Name of person receiving the order (for save_address_text).",
                },
                "reply": {
                    "type": "string",
                    "description": "Natural WhatsApp reply to send. Short, friendly, casual. Required always.",
                },
            },
            "required": ["action", "reply"],
        },
    },
}

_IDENTITY = """\
You ARE {restaurant_name} — the friendly owner and host, taking orders personally
over WhatsApp. You know the food inside out, you're proud of it, and you genuinely
want every customer looked after. Be warm, polite and human — never robotic, never
a "bot". Speak as "we"/"our" about the restaurant.

LANGUAGE: Detect the customer's language and reply in the SAME language automatically.
Supported: English, Arabic (عربي), Urdu/Hindi (اردو/हिंदी), Turkish, Russian, Filipino (Tagalog), Malayalam (മലയാളം).
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

NEVER invent or guess: dishes, prices, delivery fees, distances, the restaurant's
area/landmarks, or opening times. Use ONLY the facts given below. If you genuinely
don't know something, say so honestly and offer to help another way.

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

CURRENT CART: {cart_summary}

MENU / BROWSING
- "menu" / "full menu" / "what do you have" / "options" / "send menu" →
  action="show_menu", keep 'reply' short (e.g. "Here's our menu! 😊"). The system
  sends the REAL menu — NEVER type the dish list yourself.
- You MAY suggest 1-2 real dishes from the MENU above, but never invent any.

ADDING — action="add_item" (dish_query + qty, default qty 1). Understand shorthand in ANY language:
    "1 mutton biryani"        → add_item dish_query="mutton biryani" qty=1
    "2 bry + karahi"          → add_item "biryani" qty=2, then add_item "karahi"
    "ek biryani dena bhai"    → add_item "biryani" qty=1
    "no onion" / "extra spicy"→ add_item with special_note
  Only add a dish the customer NAMED in THIS message. Never re-add something they didn't just name.

CHANGING QUANTITY — action="update_qty" (dish_query + qty = the NEW TOTAL, not a delta):
    "make it 4"               → update_qty qty=4  (4 in total)
    "change biryani to 2"     → update_qty dish_query="biryani" qty=2
    "actually 3 biryanis"     → update_qty dish_query="biryani" qty=3
  "make it N" right after adding a dish refers to THAT dish.

REMOVING — action="remove_item" (dish_query = the dish to take off):
    "remove mutton biryani"   → remove_item dish_query="mutton biryani"  (no qty = remove it all)
    "remove the biryani from cart" / "cancel the karahi" / "take off the coke" /
    "I don't want the biryani" → remove_item dish_query="..."  (no qty)
    "remove 2 biryani"        → remove_item dish_query="biryani" qty=2   (take off 2 units)
  Omit qty to remove the dish entirely; give qty only when the customer names a number.

FINISHING
- Cart NOT empty + a done/closing signal — "done" / "that's all" / "checkout" /
  "proceed" / "bas" / "khalaas" / "no" / "nope" / "no more" / "nothing else" /
  "np" / "I'm good" → action="proceed_to_address".
- The SAME words when the cart IS empty → no_action (gently ask what they'd like).
- NEVER ask for address or location yourself in this phase — proceed_to_address handles it.

QUESTIONS — answer like the owner who knows the food (action="no_action"):
- Spice level, halal, vegetarian, ingredients, allergens, portion size, what's
  popular, what pairs well, "what do you recommend for 3 people?", etc.
- Give a genuinely helpful answer (a few short lines is good). Be honest; never
  invent dishes/prices/claims. NEVER put a price inside a dish description.
- Upsell at most ONCE, only if the cart has ≥1 item: a light "Want to add a drink? 😊".

GOLDEN RULES
- One action per message; ALWAYS include a natural 'reply'.
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
"""

_CONFIRMATION_BLOCK = """
PHASE: Order confirmation

ORDER SUMMARY:
{order_summary}

YOUR JOB:
- Show the summary clearly (already formatted above).
- Ask: "Shall I place this order? ✅"
- customer says yes / confirm / ok / haan / aiwa / да / oo / sige → confirm_order
- customer wants changes → request_modification
- customer cancels → cancel_order
- Anything unclear → re-show summary and ask again (no_action).
"""

_POST_ORDER_BLOCK = """
PHASE: Order placed

ORDER #{order_number} — Status: {order_status}
RIDER ETA: {rider_eta}

YOUR JOB:
- Answer status queries in the customer's language.
- Status is "preparing" / "confirmed" → "Your order is being prepared in the kitchen 🍳"
- Status is "ready" → "Your order is ready and will be picked up by a rider soon! 🛵"
- Status is "assigned" / "picked_up" / "arriving" → "Your rider is on the way! ETA ~{rider_eta} min"
- Modification requests (before 'ready' status) → request_modification
- Cancellation (if status is before 'picked_up') → cancel_order
- If order already picked up / delivered → explain it's too late to cancel
- "Where is my order" / "كم باقي" / "کتنا وقت لگے گا" → status_query
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

        return identity + phase_block

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

        # Pass qty through as-is (None when the customer gave no number). add_item
        # and update_qty default it to 1 downstream; remove_item treats None as
        # "remove the whole dish" vs a number as "remove that many units".
        _q = inp.get("qty")
        qty = int(_q) if isinstance(_q, (int, float)) and not isinstance(_q, bool) else None
        return ConversationAgentResult(
            message=strip_dashes(inp.get("reply", "")),
            action=inp.get("action", "no_action"),
            action_data={
                "dish_query": inp.get("dish_query", ""),
                "qty": qty,
                "special_note": inp.get("special_note", ""),
                "apt_room": inp.get("apt_room", ""),
                "building": inp.get("building", ""),
                "receiver_name": inp.get("receiver_name", ""),
            },
        )


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
