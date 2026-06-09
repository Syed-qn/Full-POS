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


_DS_CONVERSATION_TOOL = {
    "type": "function",
    "function": {
        "name": "take_action",
        "description": "Record the structured action inferred from the customer message, plus your reply text.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add_item", "proceed_checkout", "cancel_cart", "no_action"],
                    "description": "add_item: customer wants to add a dish. proceed_checkout: cart ready, move to delivery. cancel_cart: customer wants to cancel. no_action: greeting, question, or unclear.",
                },
                "dish_query": {
                    "type": "string",
                    "description": "Dish name or number the customer wants (only for add_item).",
                },
                "qty": {
                    "type": "integer",
                    "description": "Quantity to add (only for add_item, default 1).",
                },
                "reply": {
                    "type": "string",
                    "description": "Natural WhatsApp reply to send to the customer (keep it short and friendly).",
                },
            },
            "required": ["action", "reply"],
        },
    },
}

_DS_CONVERSATION_SYSTEM = """\
You are a friendly WhatsApp ordering assistant for {restaurant_name}.
Help customers order food in natural, conversational language.

MENU:
{menu_text}

CURRENT CART: {cart_summary}

STRICT RULES — read carefully before choosing an action:

1. GREETINGS ("hi", "hello", "what's on the menu?", "send menu", questions about the bot, etc.)
   → ALWAYS action="no_action". Greet warmly and show the full menu in your reply (all dishes with numbers and prices).

2. ORDERING ("I want X", "give me Y", "add Z", "order N biryani", etc.)
   → action="add_item", fill dish_query and qty.

3. CHECKOUT — ONLY when ALL of these are true:
   a. The cart is NOT empty (current cart shows items)
   b. The customer explicitly says "done", "that's all", "proceed", "checkout", or equivalent
   → action="proceed_checkout"
   If cart is empty, NEVER use "proceed_checkout". Use "no_action" instead.

4. CANCEL — only when customer says they want to cancel the whole order
   → action="cancel_cart"

5. EVERYTHING ELSE (questions, "are you AI?", unclear messages, status queries)
   → action="no_action"

Keep replies short (WhatsApp style). COD only. Delivery ~40 minutes. Max 10 km.
ALWAYS call take_action — never reply without the tool.
"""


class DeepSeekConversationAgent:
    """AI-powered conversation agent using DeepSeek's OpenAI-compatible function calling."""

    def __init__(self) -> None:
        self._api_key, self._model = _get_deepseek_settings()

    async def respond(
        self,
        *,
        restaurant_name: str,
        menu_text: str,
        history: list[dict],
        cart_summary: str,
    ) -> ConversationAgentResult:
        system = _DS_CONVERSATION_SYSTEM.format(
            restaurant_name=restaurant_name,
            menu_text=menu_text,
            cart_summary=cart_summary or "empty",
        )
        messages = history if history else [{"role": "user", "content": "hi"}]
        inp = await _async_chat_tools(
            self._api_key, self._model, system, messages,
            tools=[_DS_CONVERSATION_TOOL], tool_name="take_action",
        )
        return ConversationAgentResult(
            message=inp.get("reply", ""),
            action=inp.get("action", "no_action"),
            action_data={
                "dish_query": inp.get("dish_query", ""),
                "qty": int(inp.get("qty") or 1),
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
