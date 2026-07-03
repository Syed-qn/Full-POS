"""Deterministic Pillow promo header for tests/dev (no paid APIs)."""
from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageDraw, ImageFont

_SIZE = 600
_PAD = 48


def _bg_color(seed: str) -> tuple[int, int, int]:
    h = hashlib.md5((seed or "promo").encode("utf-8")).digest()
    return (50 + h[0] % 100, 60 + h[1] % 90, 40 + h[2] % 80)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


class PlaceholderPromoImageGenerator:
    async def generate(self, *, prompt: str, restaurant_name: str) -> bytes:
        label = (restaurant_name or "Restaurant").strip()
        img = Image.new("RGB", (_SIZE, _SIZE), _bg_color(prompt))
        draw = ImageDraw.Draw(img)
        # Warm accent band — "food promo" aesthetic without real photography.
        draw.rectangle((0, _SIZE - 180, _SIZE, _SIZE), fill=(180, 90, 40))
        title_font = _font(36)
        sub_font = _font(22)
        title = label[:40]
        draw.text((_PAD, _PAD), title, fill=(255, 255, 255), font=title_font)
        draw.text((_PAD, _PAD + 48), "PROMO", fill=(255, 220, 180), font=sub_font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()