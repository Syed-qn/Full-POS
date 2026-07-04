import base64
import json
import re as _re

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config import get_settings
from app.llm.action_schema import CANON_PHASE_ACTIONS, build_anthropic_tool, to_engine_result
from app.llm.conversation_prompts import (
    CLAUDE_POST_ORDER_GUIDANCE,
    build_claude_system,
)
from app.llm.port import ConversationAgentResult, DishDraft, UploadedFile, strip_dashes
from app.llm.prompts_menu import (
    ARBITRATE_TEMPLATE,
    DESCRIBE_DISH_TEMPLATE,
    EXTRACT_SYSTEM,
    FORECAST_OVERRIDE_TEMPLATE,
    INTENT_CLASSIFY_TEMPLATE,
    SEGMENT_COMPILE_TEMPLATE,
)
from app.llm.prompts_router import COMPLETION_DETECT_TEMPLATE, ROUTER_CLASSIFY_TEMPLATE

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
                        "variants": {
                            "type": "array",
                            "description": (
                                "Size/portion options when a dish has more than one price. "
                                "Set price_aed to the smallest/first price and list the larger "
                                "sizes here, each with a size name and its own price."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "price_aed": {"type": "string"},
                                },
                                "required": ["name", "price_aed"],
                            },
                        },
                    },
                    "required": ["name"],
                },
            }
        },
        "required": ["dishes"],
    },
}

_PROMPT = (
    EXTRACT_SYSTEM.replace("JSON array of dish objects", "structured dish list via submit_menu")
    + " Use the submit_menu tool with a dishes array."
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
        prompt = DESCRIBE_DISH_TEMPLATE.format(name=name, raw_description=raw_description)
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
        prompt = INTENT_CLASSIFY_TEMPLATE.format(text=text)
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
        prompt = ARBITRATE_TEMPLATE.format(
            query=query,
            options=options,
            candidate_count=len(candidates),
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

        prompt = FORECAST_OVERRIDE_TEMPLATE.format(text=text)
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

        from app.marketing.segments import validate_dsl

        prompt = SEGMENT_COMPILE_TEMPLATE.format(text=text)
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
        prompt = COMPLETION_DETECT_TEMPLATE.format(text=text)
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
        prompt = ROUTER_CLASSIFY_TEMPLATE.format(
            phase=phase,
            cart_context=cart_context or "(empty)",
            text=text,
            labels=labels,
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

def _phase_guidance(phase: str, context: dict | None = None) -> str:
    if phase == "post_order":
        ctx = context or {}
        return CLAUDE_POST_ORDER_GUIDANCE.format(
            order_number=ctx.get("order_number") or "",
            order_status=ctx.get("order_status") or "unknown",
            rider_eta=ctx.get("rider_eta") or "calculating",
        )
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
        from app.llm.context_management import claude_request_kwargs, format_memory_context

        system = build_claude_system(restaurant_name, dialogue_phase, context) + _phase_guidance(
            dialogue_phase, context
        )
        memory = format_memory_context(context.get("session_notes"))
        if memory:
            system = memory + "\n\n" + system
        messages = history if history else [{"role": "user", "content": "hi"}]
        create_kwargs: dict = {
            "model": self._model,
            "max_tokens": 512,
            "system": system,
            "tools": [_CONVERSATION_TOOL],
            "tool_choice": {"type": "tool", "name": "take_action"},
            "messages": messages,
        }
        create_kwargs.update(claude_request_kwargs())
        if create_kwargs.get("betas"):
            response = await self._client.beta.messages.create(**create_kwargs)
        else:
            response = await self._client.messages.create(**create_kwargs)
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


class ClaudeKitchenSummarizer:
    """Tier-2 kitchen chat compressor — parity with DeepSeekKitchenSummarizer."""

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

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
        prompt = build_tier2_prompt(structured_block, inbound_messages)
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=120,
            system=_TIER2_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _first_text(message).strip()
        return parse_tier2_response(raw)
