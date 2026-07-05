"""Dish images are compressed for WhatsApp catalog card reliability."""
from io import BytesIO

from PIL import Image

from app.menu.image_catalog import (
    CATALOG_IMAGE_MAX_BYTES,
    compress_for_catalog_image,
)


def _big_png() -> bytes:
    img = Image.effect_noise((2400, 2400), 64).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def test_compress_shrinks_large_upload():
    raw = _big_png()
    assert len(raw) > 100_000  # realistic phone photo dimensions
    out, ctype = compress_for_catalog_image(raw)
    assert ctype == "image/jpeg"
    assert len(out) <= CATALOG_IMAGE_MAX_BYTES
    img = Image.open(BytesIO(out))
    assert min(img.size) >= 500


async def test_upload_dish_image_stores_jpeg(client, auth_headers):
    raw = _big_png()
    resp = await client.post(
        "/api/v1/dishes/image",
        files=[("file", ("dish.png", raw, "image/png"))],
        headers=auth_headers,
    )
    assert resp.status_code == 201
    url = resp.json()["url"]
    served = await client.get(url[url.index("/media/") :])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"
    assert len(served.content) <= CATALOG_IMAGE_MAX_BYTES