"""Phase 0: partner outbound webhook plumbing."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant
from app.partner.integration import apply_partner_settings
from app.partner.webhooks.deliver import deliver_partner_webhook_one
from app.partner.webhooks.enqueue import enqueue_partner_webhook
from app.partner.webhooks.models import PartnerWebhookDelivery
from app.partner.webhooks.signing import sign_body, verify_signature




async def _restaurant(db_session, phone: str = "+971501234567") -> Restaurant:
    return (
        await db_session.scalars(select(Restaurant).where(Restaurant.phone == phone))
    ).one()


# ── signing ──────────────────────────────────────────────────────────────────
def test_sign_and_verify_roundtrip():
    body = b'{"event":"order.created"}'
    secret = "test-secret"
    header = sign_body(secret, body)
    assert header.startswith("sha256=")
    assert verify_signature(secret, body, header)
    assert not verify_signature(secret, body, "sha256=bad")
    assert not verify_signature(secret, body, None)


# ── enqueue ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_enqueue_skips_when_partner_disabled(db_session, auth_headers, client):
    _ = auth_headers  # ensures restaurant exists
    rest = await _restaurant(db_session)
    row = await enqueue_partner_webhook(
        db_session,
        restaurant=rest,
        event_type="order.created",
        data={"order_id": 1},
        idempotency_key="pos-order-created-1",
    )
    assert row is None


@pytest.mark.asyncio
async def test_enqueue_creates_row_when_configured(db_session, auth_headers, client):
    _ = client
    rest = await _restaurant(db_session)
    apply_partner_settings(
        rest,
        {
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "sec",
        },
    )
    await db_session.commit()

    row = await enqueue_partner_webhook(
        db_session,
        restaurant=rest,
        event_type="order.created",
        data={"order_id": 99},
        idempotency_key="pos-order-created-99",
    )
    assert row is not None
    assert row.event_type == "order.created"
    assert row.target_url == "https://pos.example.com/hooks"
    assert row.payload["event"] == "order.created"
    assert row.payload["data"]["order_id"] == 99
    await db_session.commit()

    dup = await enqueue_partner_webhook(
        db_session,
        restaurant=rest,
        event_type="order.created",
        data={"order_id": 99},
        idempotency_key="pos-order-created-99",
    )
    assert dup is None


# ── deliver ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_deliver_posts_signed_payload(db_session, auth_headers):
    _ = auth_headers
    rest = await _restaurant(db_session)
    apply_partner_settings(
        rest,
        {
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "sec",
        },
    )
    row = PartnerWebhookDelivery(
        restaurant_id=rest.id,
        event_type="integration.ping",
        payload={
            "event": "integration.ping",
            "idempotency_key": "ping-1",
            "data": {"ok": True},
        },
        target_url="https://pos.example.com/hooks",
        idempotency_key="ping-1",
        status="pending",
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    factory = db_session.bind
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(bind=factory, expire_on_commit=False)

    await deliver_partner_webhook_one(row.id, session_factory=session_factory, client=mock_client)

    mock_client.post.assert_called_once()
    _url, kwargs = mock_client.post.call_args[0][0], mock_client.post.call_args[1]
    assert _url == "https://pos.example.com/hooks"
    assert kwargs["headers"]["X-Partner-Event"] == "integration.ping"
    assert kwargs["headers"]["X-Partner-Signature"].startswith("sha256=")

    async with session_factory() as session:
        updated = await session.get(PartnerWebhookDelivery, row.id)
        assert updated.status == "sent"
        assert updated.delivered_at is not None


# ── manager config + test endpoint ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_integration_config_patch_and_store(client, auth_headers, db_session):
    patched = await client.patch(
        "/api/v1/partner-integration/config",
        json={
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "s3cr3t",
            "pos_store_id": "CRT-001",
        },
        headers=auth_headers,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["partner_enabled"] is True
    assert body["partner_webhook_url"] == "https://pos.example.com/hooks"
    assert body["partner_webhook_secret_set"] is True
    assert body["pos_store_id"] == "CRT-001"
    assert "partner_webhook_secret" not in body

    key = (await client.post(
        "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
    )).json()["api_key"]

    store = await client.get(
        "/api/v1/partner/store",
        headers={"X-API-Key": key},
    )
    assert store.status_code == 200
    assert store.json()["pos_store_id"] == "CRT-001"
    assert store.json()["partner_enabled"] is True


@pytest.mark.asyncio
async def test_webhook_test_endpoint_queues_delivery(client, auth_headers, db_session):
    await client.patch(
        "/api/v1/partner-integration/config",
        json={
            "partner_enabled": True,
            "partner_webhook_url": "https://pos.example.com/hooks",
            "partner_webhook_secret": "s3cr3t",
        },
        headers=auth_headers,
    )

    with patch(
        "app.partner.router.schedule_partner_webhook_delivery",
        new_callable=AsyncMock,
    ) as mock_schedule:
        resp = await client.post(
            "/api/v1/partner-integration/webhooks/test",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["queued"] is True
    assert data["delivery_id"] is not None
    mock_schedule.assert_awaited_once()