import base64

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
