import base64
import re as _re

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.config import get_settings
from app.llm.port import DishDraft, UploadedFile

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
                raise ValueError(f"Unsupported file type: {f.mime}")
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
