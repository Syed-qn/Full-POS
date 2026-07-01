import base64
import re as _re

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config import get_settings
from app.llm.action_schema import CANON_PHASE_ACTIONS, build_anthropic_tool, to_engine_result
from app.llm.port import ConversationAgentResult, DishDraft, UploadedFile, strip_dashes

_TOOL = {
    "name": "submit_menu",
    "description": "Submit every dish extracted from the menu images/PDF.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dishes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dish_number": {"type": ["integer", "null"]},
                        "name": {"type": "string"},
                        "price_aed": {"type": ["string", "null"]},
                        "category": {"type": ["string", "null"]},
                        "description": {"type": ["string", "null"]},
                    },
                    "required": ["name"],
                },
            }
        },
        "required": ["dishes"],
    },
}

_PROMPT = (
    "Extract EVERY dish from this restaurant menu. For each dish capture: "
    "dish_number (the printed item number — null ONLY if truly absent), name, "
    "price_aed as a decimal string, category (menu section heading), and "
    "description if printed. Do not invent dishes, numbers, or prices. "
    "Preserve original spelling of names."
)

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class ClaudeExtractor:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
        self._model = settings.claude_model

    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]:
        if not files:
            raise ValueError("extract_menu requires at least one file")

        content: list[dict] = []
        for f in files:
            if f.mime == "application/pdf":
                content.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.b64encode(f.content).decode(),
                    },
                })
            elif f.mime in _IMAGE_MIMES:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": f.mime,
                        "data": base64.b64encode(f.content).decode(),
                    },
                })
            else:
                # Text-based menu (txt/csv/markdown). Include it verbatim. An
                # unknown "application/octet-stream" is accepted only if it cleanly
                # decodes as UTF-8 (a real binary like tiff/docx/xlsx won't, and is
                # rejected as unsupported).
                is_text = f.mime.startswith("text/")
                if not is_text and f.mime == "application/octet-stream":
                    try:
                        f.content.decode("utf-8")
                        is_text = True
                    except UnicodeDecodeError:
                        is_text = False
                if not is_text:
                    raise ValueError(f"Unsupported file type: {f.mime}")
                text = f.content.decode("utf-8", errors="replace")
                content.append({"type": "text", "text": f"--- {f.filename} ---\n{text}"})
        content.append({"type": "text", "text": _PROMPT})

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=16384,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_menu"},
            messages=[{"role": "user", "content": content}],
        )

        if response.stop_reason == "max_tokens":
            raise RuntimeError("Menu extraction truncated — output exceeded max_tokens")

        for block in response.content:
            if block.type == "tool_use":
                dishes = block.input.get("dishes")
                if not isinstance(dishes, list):
                    raise RuntimeError("Model response missing 'dishes' list")
                try:
                    return [DishDraft(**d) for d in dishes]
                except ValidationError as exc:
                    raise RuntimeError(f"Malformed dish from model: {exc}") from exc
        raise RuntimeError("Claude returned no tool_use block")


def _first_text(message) -> str:
    """Extract first text block; guard truncation/empty content (error contract: RuntimeError = model fault)."""
    if message.stop_reason == "max_tokens":
        raise RuntimeError("Claude response truncated (max_tokens)")
    if not message.content or not getattr(message.content[0], "text", None):
        raise RuntimeError("Claude returned empty content")
    return message.content[0].text


class ClaudeDescriber:
    """Production describer via Claude API. Max 3 lines, never includes price."""

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    def describe(self, name: str, raw_description: str, price_hint: str | None = None) -> str:
        prompt = (
            f"Write a customer-facing description for this dish:\n"
            f"Name: {name}\n"
            f"Details: {raw_description}\n\n"
            f"Rules: maximum 3 lines, no price, no currency amounts, "
            f"no 'AED', factual and appetising."
        )
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _first_text(message).strip()
        # Safety strip — remove any price-like patterns that slipped through
        safe = _re.sub(r"\b(?:AED|aed|\d+\.\d{2})\b", "", raw).strip()
        # Spec: max 3 lines — enforce programmatically, not just via prompt
        return "\n".join(safe.splitlines()[:3])


class ClaudeIntentClassifier:
    """Production intent classifier via Claude API."""

    _VALID = frozenset({"order_item", "dish_question", "cancel", "modify", "status", "other"})

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    def classify(self, text: str) -> str:
        prompt = (
            f"Classify this WhatsApp message from a restaurant customer.\n"
            f"Message: {text!r}\n\n"
            f"Reply with exactly one word from: "
            f"order_item, dish_question, cancel, modify, status, other"
        )
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=16,
            messages=[{"role": "user", "content": prompt}],
        )
        result = _first_text(message).strip().lower()
        return result if result in self._VALID else "other"


class ClaudeArbiter:
    """Production arbiter: given ambiguous dish candidates, returns best match."""

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    async def arbitrate(self, query: str, candidates: list) -> object | None:
        if not candidates:
            return None
        options = "\n".join(
            f"{i + 1}. {c.dish_number}. {c.name}" for i, c in enumerate(candidates)
        )
        prompt = (
            f"A customer typed: {query!r}\n"
            f"These menu items might match:\n{options}\n\n"
            f"Which number (1-{len(candidates)}) is the best match? "
            f"Reply with just the number, or 0 if none match."
        )
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=8,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _first_text(message).strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except ValueError:
            pass
        return None


class ClaudeForecastAdjuster:
    """Production ForecastAdjuster: plain-English override -> parsed_effect DSL.

    Constrained JSON-only output; any parse/API fault degrades to ``{}`` so a
    malformed manager note never raises into the forecast pipeline.
    """

    _ALLOWED_HORIZONS = frozenset(
        {"breakfast", "lunch", "dinner", "midnight", "morning", "evening"}
    )

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client

        self._client = _get_anthropic_client()

    def parse_override(self, text: str) -> dict:
        import json

        prompt = (
            "A restaurant manager wrote a plain-English forecast override. "
            "Convert it into a JSON object with these OPTIONAL keys ONLY:\n"
            '  "horizon": one of breakfast|lunch|dinner|midnight|morning|evening, or null\n'
            '  "dow": integer 0-6 (Monday=0 .. Sunday=6), or null\n'
            '  "order_count_delta": integer (default 0)\n'
            '  "order_count_mult": float (default 1.0)\n'
            '  "revenue_mult": float (default 1.0)\n'
            '  "dish_demand_delta": object mapping dish_id string -> integer\n\n'
            f"Manager note: {text!r}\n\n"
            "Reply with ONLY the JSON object, no prose. Omit keys you cannot infer."
        )
        try:
            message = self._client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = _first_text(message).strip()
            parsed = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return self._sanitise(parsed)

    def _sanitise(self, parsed: dict) -> dict:
        effect: dict = {}
        horizon = parsed.get("horizon")
        if isinstance(horizon, str) and horizon.lower() in self._ALLOWED_HORIZONS:
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
            cleaned = {
                str(k): int(v)
                for k, v in dish.items()
                if isinstance(v, int) and not isinstance(v, bool)
            }
            if cleaned:
                effect["dish_demand_delta"] = cleaned
        return effect


class ClaudeSegmentCompiler:
    """Production segment compiler: plain English -> validated DSL via haiku.

    The model is constrained to emit JSON-only DSL; we then run ``validate_dsl``
    which raises on anything outside the field/op allowlist. Invalid model output
    is rejected (RuntimeError) — never executed.
    """

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    def compile(self, text: str) -> dict:
        import json

        from app.marketing.segments import validate_dsl

        prompt = (
            "Translate this restaurant manager's audience description into a "
            "segment DSL JSON object. Reply with JSON ONLY, no prose.\n\n"
            f"Description: {text!r}\n\n"
            "Schema: top-level key 'all' (AND) or 'any' (OR) -> list of conditions.\n"
            "Each condition is {\"field\":..,\"op\":..,\"value\":..}.\n"
            "Allowed fields/ops:\n"
            "  total_spend: eq|gte|lte|gt|lt (numeric AED)\n"
            "  order_count: eq|gte|lte|gt|lt (integer)\n"
            "  last_order_days_ago: eq|gte|lte|gt|lt (integer days)\n"
            "  tag: contains (string tag label, e.g. 'vip')\n"
            "  ordered_dish_id: eq (integer dish id, optional 'min_count')\n"
            "Use ONLY these fields and ops. Output JSON only."
        )
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _first_text(message).strip()
        # Strip ```json fences if present.
        raw = _re.sub(r"^```(?:json)?|```$", "", raw, flags=_re.MULTILINE).strip()
        try:
            dsl = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SegmentCompiler returned non-JSON: {exc}") from exc
        # Security gate: reject anything outside the allowlist before returning.
        validate_dsl(dsl)
        return dsl


class ClaudeCompletionDetector:
    """Production completion detector via Claude API (haiku, yes/no prompt)."""

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    async def is_completion(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        prompt = (
            "A restaurant customer sent this WhatsApp message during an order: "
            f"{text!r}\n\n"
            "Does the message mean the customer is FINISHED ordering / wants to proceed "
            "(in ANY language, any phrasing — 'done', 'khalas', 'bas', 'that\\'s all', "
            "bare 'no', or equivalent)?\n"
            "Answer with a single word: yes or no."
        )
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=4,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _first_text(message).strip()
        return raw.lower().startswith("y")


class ClaudeRouterClassifier:
    """Production W4 top-level router via Claude API (single enum, multilingual).

    LLM-driven: no English phrase tables.  The model receives the raw message in
    ANY language plus the current cart + phase, and returns exactly one
    ``IntentLabel`` value that decides whether the turn may mutate the cart.
    """

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    async def classify_intent(self, text: str, cart_context: str, phase: str):
        from app.llm.port import IntentLabel

        if not text or not text.strip():
            return IntentLabel.NON_ACTIONABLE
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
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=8,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = _first_text(message).strip().lower()
        raw = raw_text.split()[0] if raw_text else ""
        try:
            return IntentLabel(raw)
        except ValueError:
            return IntentLabel.UNKNOWN


# Tool definition is derived from the single-source-of-truth schema so providers
# can never drift from the canonical action vocabulary (W1 Task 3).
_CONVERSATION_TOOL = build_anthropic_tool("take_action")

_CONVERSATION_SYSTEM = """\
You are a friendly WhatsApp ordering assistant for {restaurant_name}.
Help customers order food in natural, conversational language.
Always refer to the restaurant by its EXACT name, "{restaurant_name}", never alter,
expand, abbreviate, or restyle it.

MENU:
{menu_text}

CURRENT CART: {cart_summary}

DELIVERY FEES — the ONLY correct numbers. Recite EXACTLY when asked about
delivery cost. NEVER invent or guess tiers/distances. The exact fee for an order
is set by the backend from the customer's location, not by you:
{delivery_info}

#1 RULE, ABSOLUTE — NEVER INVENT ANYTHING. Dishes, dish names, prices, sizes, combos,
drinks, sides, offers, ingredients, delivery fees, distances, area/landmarks, opening
times: use ONLY the exact facts in the MENU and the lines above. You may NEVER list,
name, suggest, describe, recommend, or upsell a dish that is not written in the MENU,
not even as an example. If the customer asks about ANYTHING you do not have a fact for,
do NOT guess: say you are not sure and give the contact number so they can ask the team.
Your job is ONLY to take orders from the MENU and capture delivery details.

STRICT RULES — read carefully before choosing an action:

1. GREETINGS ("hi", "hello", "what's on the menu?", "send menu", questions about the bot, etc.)
   → ALWAYS action="no_action". Greet warmly and show the full menu in your reply: group dishes by category with a *bold* heading, list each dish as a "• Name: AED price" bullet, and NEVER show internal dish numbers.

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

AVAILABILITY ("do you have X?", "any drinks?"): the MENU above is the ONLY truth.
If a matching item IS in the MENU, say YES and name it exactly as written, NEVER deny
an item that is in the MENU. If nothing matches, say we don't have it, and NEVER name
or price an item that is not in the MENU. Any upsell may ONLY name an item in the MENU.

LOCATION: NEVER invent or guess the restaurant's area, neighbourhood, or landmarks.
If asked where you are located, offer to share the exact location pin instead.

Keep replies short (WhatsApp style). COD only. Delivery ~40 minutes. For the delivery radius and fees, rely only on the delivery info provided; never invent a distance limit.
PUNCTUATION: Never use em dashes (—), en dashes (–), or hyphens to join or separate clauses. Write plainly with commas, periods, or separate sentences instead.
ALWAYS call take_action. Never reply without the tool.
"""


def _phase_guidance(phase: str) -> str:
    allowed = sorted(CANON_PHASE_ACTIONS.get(phase, CANON_PHASE_ACTIONS["ordering"]))
    return (
        f"\nCURRENT PHASE: {phase}. You may ONLY use these actions this phase: "
        f"{', '.join(allowed)}. cart_add.add_qty is a DELTA; cart_set_qty.new_total "
        f"is the ABSOLUTE new total ('only 1' -> cart_set_qty new_total=1, never add). "
        f"For multiple dishes in one message use items[] with an explicit op per dish.\n"
    )


class ClaudeConversationAgent:
    """AI-powered full-conversation agent for customer ordering via WhatsApp."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
        self._model = settings.claude_model

    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,
        history: list[dict],
        context: dict,
    ) -> ConversationAgentResult:
        # Matches ConversationAgentPort. The system prompt is grounded ONLY on the
        # menu_text the engine passes in (catalogue-bounded in catalogue mode), so the
        # model can never talk about an item that isn't on the active menu.
        system = _CONVERSATION_SYSTEM.format(
            restaurant_name=restaurant_name,
            menu_text=context.get("menu_text", "Menu unavailable."),
            cart_summary=context.get("cart_summary") or "empty",
            delivery_info=context.get("delivery_info") or "Delivery fees vary by distance.",
        ) + _phase_guidance(dialogue_phase)
        messages = history if history else [{"role": "user", "content": "hi"}]
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=system,
            tools=[_CONVERSATION_TOOL],
            tool_choice={"type": "tool", "name": "take_action"},
            messages=messages,
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "take_action":
                inp = dict(block.input)
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
        raise RuntimeError("ClaudeConversationAgent: no take_action block in response")
