"""Compress dish photos for Meta / WhatsApp catalog cards.

Meta accepts large images (up to ~8 MB) but WhatsApp product_list cards often fail to
render silently above ~500 KB (prod Lims Jul 2026). Every upload and publish path runs
through here so managers can upload any phone photo — we normalize it."""
from __future__ import annotations

import io

from PIL import Image, ImageOps

# Meta minimum 500×500; cap dimension + bytes for reliable WhatsApp card render.
CATALOG_IMAGE_MIN_PX = 500
CATALOG_IMAGE_MAX_PX = 1024
CATALOG_IMAGE_MAX_BYTES = 450_000
_JPEG_QUALITIES = (85, 78, 70, 62, 55, 48)


def compress_for_catalog_image(raw: bytes) -> tuple[bytes, str]:
    """Resize and JPEG-compress for catalogue product cards. Always returns JPEG."""
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if w < CATALOG_IMAGE_MIN_PX or h < CATALOG_IMAGE_MIN_PX:
        scale = CATALOG_IMAGE_MIN_PX / min(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    longest = max(img.size)
    if longest > CATALOG_IMAGE_MAX_PX:
        scale = CATALOG_IMAGE_MAX_PX / longest
        img = img.resize(
            (int(img.size[0] * scale), int(img.size[1] * scale)),
            Image.Resampling.LANCZOS,
        )

    for quality in _JPEG_QUALITIES:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if len(out) <= CATALOG_IMAGE_MAX_BYTES:
            return out, "image/jpeg"

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITIES[-1], optimize=True)
    return buf.getvalue(), "image/jpeg"


def media_path_from_url(image_url: str | None) -> str | None:
    """``/media/dishes/2/abc.jpg`` path from a public base URL."""
    url = (image_url or "").strip()
    if "/media/" not in url:
        return None
    return url.split("/media/", 1)[1].split("?", 1)[0].strip() or None