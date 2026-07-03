"""Promo header image generation port (swappable provider)."""
from __future__ import annotations

from typing import Protocol


class PromoImageGeneratorPort(Protocol):
    async def generate(self, *, prompt: str, restaurant_name: str) -> bytes:
        """Return PNG or JPEG bytes, ≥500×500 px (Meta header guidance)."""