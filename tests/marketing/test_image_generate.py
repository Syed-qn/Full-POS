"""Phase 5 — AI promo header image generation."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.marketing.models import MarketingMedia
from app.marketing.service import generate_promo_image

pytestmark = pytest.mark.asyncio


async def test_generate_image_placeholder_returns_url(client, auth_headers):
    resp = await client.post(
        "/api/v1/marketing/templates/image/generate",
        json={"describe": "20% off biryani this weekend"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "url" in body
    assert "/media/marketing/" in body["url"]


async def test_generate_image_rate_limit_429(client, auth_headers, monkeypatch):
    monkeypatch.setenv("APP_MARKETING_IMAGE_MAX_PER_DAY", "1")
    get_settings.cache_clear()
    try:
        first = await client.post(
            "/api/v1/marketing/templates/image/generate",
            json={"prompt": "fresh biryani platter"},
            headers=auth_headers,
        )
        assert first.status_code == 200
        second = await client.post(
            "/api/v1/marketing/templates/image/generate",
            json={"prompt": "another promo shot"},
            headers=auth_headers,
        )
        assert second.status_code == 429
        assert "limit" in second.json()["detail"].lower()
    finally:
        monkeypatch.delenv("APP_MARKETING_IMAGE_MAX_PER_DAY", raising=False)
        get_settings.cache_clear()


async def test_generate_image_persists_marketing_media(db_session, restaurant):
    url = await generate_promo_image(
        db_session,
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        describe="family feast combo",
        now_utc=datetime.now(timezone.utc),
    )
    assert "/media/marketing/" in url
    media = (
        await db_session.scalars(
            select(MarketingMedia).where(MarketingMedia.restaurant_id == restaurant.id)
        )
    ).all()
    assert len(media) == 1
    assert media[0].path.startswith(f"marketing/{restaurant.id}/gen_")
    assert len(media[0].data) > 500