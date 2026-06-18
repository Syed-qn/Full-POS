"""DeepSeek LLM provider — OpenAI-compatible API via httpx.

All ports mirror the Claude implementations. Sync methods use httpx sync client;
async methods (MenuExtractor) use httpx async client.
"""
import json
import re as _re
from functools import lru_cache

import httpx

from app.config import get_settings
from app.llm.port import ConversationAgentResult, DishDraft, UploadedFile

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
                        "add_item: customer wants to add a dish. "
                        "remove_item: customer wants to remove a dish. "
                        "update_qty: change quantity of a dish already in cart. "
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
                    "description": "Dish name or number (for add_item, remove_item, update_qty).",
                },
                "qty": {
                    "type": "integer",
                    "description": "Quantity (for add_item, update_qty). Default 1.",
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
You are {restaurant_name}'s friendly WhatsApp ordering assistant.

LANGUAGE: Detect the customer's language and reply in the SAME language automatically.
Supported: English, Arabic (عربي), Urdu/Hindi (اردو/हिंदी), Turkish, Russian, Filipino (Tagalog), Malayalam (മലയാളം).
If they mix languages, match their mix. Never switch language unless the customer does.

TONE: Friendly and casual — like a helpful friend, not a corporate bot.
SHORT replies (WhatsApp style). Emoji: sparingly, only where natural.

ALWAYS call take_action. Never reply without calling it.
COD only (cash on delivery). Delivery ~40 minutes. Max {max_radius_km} km range.

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
"""

_ORDERING_BLOCK = """
PHASE: Taking order

MENU:
{menu_text}

CURRENT CART: {cart_summary}

YOUR JOB:
- Greet warmly. You may mention 1-2 dish names from the MENU above as highlights,
  but NEVER invent dishes/prices that are not in it.
- If the customer asks to see the menu (menu / full menu / what do you have / options),
  use action="show_menu" and keep 'reply' short (e.g. "Here's our menu! 😊") — the
  system sends the real menu. NEVER type the dish list yourself.
- Understand shorthand orders in ANY language:
    "2 bry + karahi"         → add_item dish_query="biryani" qty=2, then add_item dish_query="karahi"
    "ek biryani dena bhai"   → add_item dish_query="biryani" qty=1
    "bhai no onion"          → add_item with special_note="no onion"
    "extra spicy plz"        → add_item with special_note="extra spicy"
    "rm that" / "cancel last"→ remove_item
    "make it 3"              → update_qty qty=3
    "bas" / "khalaas" / "that's all" / "done" / "checkout" → proceed_to_address
- Handle questions: spice level, halal, portion size, ingredients, vegetarian, allergens.
  Max 3 lines per answer. Never include price in dish descriptions.
- Upsell ONCE (only if cart has ≥1 item and you haven't already suggested): "Want to add a drink? 😊"
- NEVER ask for address or location in this phase.
- If cart is not empty and customer says they are done → proceed_to_address.
- A NEGATIVE or closing reply to "anything else?" — "no" / "nope" / "no more" /
  "that's it" / "nothing else" / "I'm good" / "np" — when the cart is NOT empty
  means they are finished → proceed_to_address. If the cart IS empty, no_action.
- CRITICAL: ONLY use add_item when the customer NAMES a dish (or a number/qty of
  one). NEVER re-add a dish the customer did not just name. If the message is not
  a dish, a quantity change, a removal, or a question, do NOT use add_item —
  choose proceed_to_address (cart not empty) or no_action.
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

        return ConversationAgentResult(
            message=inp.get("reply", ""),
            action=inp.get("action", "no_action"),
            action_data={
                "dish_query": inp.get("dish_query", ""),
                "qty": int(inp.get("qty") or 1),
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
