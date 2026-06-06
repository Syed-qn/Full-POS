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
        raw = message.content[0].text.strip()
        # Safety strip — remove any price-like patterns that slipped through
        safe = _re.sub(r"\b(?:AED|aed|\d+\.\d{2})\b", "", raw).strip()
        return safe


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
        result = message.content[0].text.strip().lower()
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
        raw = message.content[0].text.strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except ValueError:
            pass
        return None
