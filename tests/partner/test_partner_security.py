"""Phase 5: partner API security — rate limit + audit trail."""
import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.identity.models import Restaurant

pytestmark = pytest.mark.asyncio


async def _api_key(client, auth_headers) -> str:
    return (
        await client.post(
            "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
        )
    ).json()["api_key"]


@pytest.mark.asyncio
async def test_partner_call_writes_audit_log(client, auth_headers, db_session):
    key = await _api_key(client, auth_headers)
    resp = await client.get(
        "/api/v1/partner/store", headers={"X-API-Key": key}
    )
    assert resp.status_code == 200

    rest = (
        await db_session.scalars(
            select(Restaurant).where(Restaurant.phone == "+971501234567")
        )
    ).one()
    row = await db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.restaurant_id == rest.id,
            AuditLog.actor == "pos",
            AuditLog.entity == "partner_api",
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    assert row is not None
    assert row.action == "get"
    assert "/api/v1/partner/store" in row.entity_id


@pytest.mark.asyncio
async def test_partner_rate_limit_429(client, auth_headers, rate_limiter):
    """60/min bucket — exhaust with a low cap via monkeypatched settings."""
    from app.config import get_settings

    get_settings.cache_clear()
    import os

    os.environ["APP_PARTNER_RATE_LIMIT"] = "3/minute"
    get_settings.cache_clear()

    key = await _api_key(client, auth_headers)
    headers = {"X-API-Key": key}
    for _ in range(3):
        assert (
            await client.get("/api/v1/partner/store", headers=headers)
        ).status_code == 200
    blocked = await client.get("/api/v1/partner/store", headers=headers)
    assert blocked.status_code == 429

    del os.environ["APP_PARTNER_RATE_LIMIT"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_integration_health_endpoint(client, auth_headers, db_session):
    from app.partner.integration import apply_partner_settings

    rest = (
        await db_session.scalars(
            select(Restaurant).where(Restaurant.phone == "+971501234567")
        )
    ).one()
    apply_partner_settings(
        rest,
        {
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "sec",
            "pos_store_id": "CRT-SBX",
        },
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/partner-integration/health", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["partner_enabled"] is True
    assert body["webhook_url_set"] is True
    assert body["pos_store_id"] == "CRT-SBX"