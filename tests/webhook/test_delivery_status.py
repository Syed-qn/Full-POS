"""Meta delivery-status webhooks must mark failed outbounds dead (gap #1)."""
import hashlib
import hmac
import json

from sqlalchemy import select

from app.outbox.models import OutboxMessage


def _signed_body(payload: dict, secret: str = "") -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


async def _seed_restaurant(client, db_session):
    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Status Test Restaurant",
            "email": "status@rest.ae",
            "phone": "+97141234567",
            "password": "hunter2!",
            "lat": 25.2048,
            "lng": 55.2708,
        },
    )
    assert signup_resp.status_code == 201
    return signup_resp.json()["id"]


async def test_failed_delivery_status_marks_outbox_dead(client, db_session):
    restaurant_id = await _seed_restaurant(client, db_session)
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone="+971509876543",
        payload={"type": "text", "body": "Hello"},
        idempotency_key="status-webhook-test-1",
        status="sent",
        wa_message_id="wamid.OUT-FAIL-001",
    )
    db_session.add(row)
    await db_session.commit()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"display_phone_number": "+97141234567"},
                    "statuses": [{
                        "id": "wamid.OUT-FAIL-001",
                        "status": "failed",
                        "timestamp": "1717660800",
                        "recipient_id": "971509876543",
                        "errors": [{"code": 131047, "title": "Re-engagement required"}],
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    body, sig = _signed_body(payload)
    resp = await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert resp.status_code == 200

    updated = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.id == row.id)
    )
    assert updated is not None
    assert updated.status == "dead"
    assert updated.payload.get("fail_reason") == "24h_window"