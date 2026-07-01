"""Generate a dish image from its name.

The POS gives no product images, so we render a clean, deterministic placeholder from the
dish name: a name-derived background colour with the name centred on top. Output is a PNG
(Meta requires a raster image), stored like any uploaded dish photo so Meta can fetch it.
Swap this for a real text-to-image generator later without touching the sync service.
"""
from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageDraw, ImageFont

_SIZE = 600
_PAD = 60
_MAX_LINES = 6


def _bg_color(name: str) -> tuple[int, int, int]:
    """Deterministic, mid-tone colour from the name (legible against white text)."""
    h = hashlib.md5((name or "Dish").encode("utf-8")).digest()
    return (40 + h[0] % 120, 40 + h[1] % 120, 40 + h[2] % 120)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:  # noqa: BLE001 - font not present on this host
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # older Pillow without size arg
        return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:_MAX_LINES]


def generate_dish_image(name: str, *, size: int = _SIZE) -> bytes:
    """Render the dish name onto a name-coloured square and return PNG bytes."""
    label = (name or "Dish").strip().upper()
    img = Image.new("RGB", (size, size), _bg_color(name))
    draw = ImageDraw.Draw(img)
    font = _font(46)
    lines = _wrap(draw, label, font, size - 2 * _PAD)
    line_h = 56
    total_h = line_h * len(lines)
    y = (size - total_h) // 2
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((size - w) // 2, y), line, fill=(255, 255, 255), font=font)
        y += line_h
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
