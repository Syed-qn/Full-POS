"""Optional DALL-E provider for prod (skipped when no API key)."""
from __future__ import annotations

import base64

import httpx

from app.config import get_settings


class OpenAIPromoImageGenerator:
    async def generate(self, *, prompt: str, restaurant_name: str) -> bytes:
        settings = get_settings()
        api_key = settings.openai_api_key.get_secret_value()
        if not api_key:
            raise RuntimeError("APP_OPENAI_API_KEY is required for openai image provider")

        model = settings.marketing_image_openai_model
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "prompt": prompt,
                    "n": 1,
                    "size": "1024x1024",
                    "response_format": "b64_json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        b64 = data["data"][0]["b64_json"]
        return base64.b64decode(b64)