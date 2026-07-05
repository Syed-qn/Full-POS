"""Dish images are compressed for WhatsApp catalog card reliability."""
from io import BytesIO

from PIL import Image

from app.menu.image_catalog import (
    CATALOG_IMAGE_MAX_BYTES,
    compress_for_catalog_image,
)


def _compressible_png() -> bytes:
    """Large dimensions — compress step must shrink for catalog cards."""
    img = Image.new("RGB", (2400, 2400), color=(200, 100, 50))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _uploadable_jpeg() -> bytes:
    """Realistic phone JPEG under the 5 MB upload cap."""
    img = Image.effect_noise((1200, 1200), 64).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    raw = buf.getvalue()
    assert len(raw) < 5 * 1024 * 1024
    return raw


def test_compress_shrinks_large_upload():
    raw = _compressible_png()
    out, ctype = compress_for_catalog_image(raw)
    assert ctype == "image/jpeg"
    assert len(out) <= CATALOG_IMAGE_MAX_BYTES
    img = Image.open(BytesIO(out))
    assert min(img.size) >= 500


async def test_upload_dish_image_stores_jpeg(client, auth_headers):
    raw = _uploadable_jpeg()
    resp = await client.post(
        "/api/v1/dishes/image",
        files=[("file", ("dish.jpg", raw, "image/jpeg"))],
        headers=auth_headers,
    )
    assert resp.status_code == 201
    url = resp.json()["url"]
    served = await client.get(url[url.index("/media/") :])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"
    assert len(served.content) <= CATALOG_IMAGE_MAX_BYTES