import hashlib
import hmac
import json
from decimal import Decimal


async def _seed_restaurant_and_menu(client, db_session):
    from app.menu.models import Dish, Menu

    signup_resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Test Restaurant",
            "phone": "+97141234567",
            "password": "hunter2!",
            "lat": 25.2048,
            "lng": 55.2708,
        },
    )
    assert signup_resp.status_code == 201
    restaurant_id = signup_resp.json()["id"]
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(
        Dish(
            menu_id=menu.id,
            restaurant_id=restaurant_id,
            dish_number=110,
            name="Chicken Biryani",
            price_aed=Decimal("22.00"),
            category="Rice",
            is_available=True,
        )
    )
    await db_session.commit()
    return restaurant_id


def _signed_body(payload: dict, secret: str = "") -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


_TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "changes": [
                {
                    "value": {
                        "metadata": {
                            "display_phone_number": "+97141234567",
                            "phone_number_id": "111",
                        },
                        "messages": [
                            {
                                "id": "wamid.unique-e2e-001",
                                "from": "971509876543",
                                "timestamp": "1717660800",
                                "type": "text",
                                "text": {"body": "Hello"},
                            }
                        ],
                    },
                    "field": "messages",
                }
            ]
        }
    ],
}


async def test_get_verify_handshake_valid(client):
    # Use the actually-configured verify token (read from settings) so the test
    # is robust to a real token being set in .env, not just the dev default.
    from app.config import get_settings

    resp = await client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": get_settings().wa_verify_token,
            "hub.challenge": "1158201444",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "1158201444"


async def test_get_verify_handshake_wrong_token(client):
    resp = await client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "1158201444",
        },
    )
    assert resp.status_code == 403


async def test_post_webhook_processes_message_and_queues_outbox(client, db_session):
    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    await _seed_restaurant_and_menu(client, db_session)

    body, sig = _signed_body(_TEXT_PAYLOAD)
    resp = await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert resp.status_code == 200

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    assert "110. Chicken Biryani" in rows[0].payload["body"]


async def test_post_webhook_duplicate_event_is_ignored(client, db_session):
    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    await _seed_restaurant_and_menu(client, db_session)

    body, sig = _signed_body(_TEXT_PAYLOAD)
    await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    resp2 = await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert resp2.status_code == 200

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1  # not doubled


async def test_post_webhook_dispatches_celery_task(client, db_session):
    """After successful webhook processing, outbox.deliver must be dispatched."""
    from unittest.mock import patch
    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    await _seed_restaurant_and_menu(client, db_session)

    dispatched_ids: list[int] = []

    def fake_apply_async(args, kwargs=None, queue=None, **kw):
        dispatched_ids.append(args[0])

    body, sig = _signed_body(_TEXT_PAYLOAD)
    with patch(
        "app.webhook.router.deliver_outbox_message.apply_async",
        side_effect=fake_apply_async,
    ):
        resp = await client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 200

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id in dispatched_ids


async def test_post_webhook_sync_delivery_sends_in_request(client, db_session, monkeypatch):
    """With outbox_sync_delivery on, the reply is delivered IN the webhook request
    (no Celery worker) — the row ends up 'sent', not left pending/dispatching."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.outbox.models import OutboxMessage

    monkeypatch.setattr(get_settings(), "outbox_sync_delivery", True)
    await _seed_restaurant_and_menu(client, db_session)

    body, sig = _signed_body(_TEXT_PAYLOAD)
    resp = await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert resp.status_code == 200

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "sent"  # delivered synchronously, no worker needed
    assert rows[0].wa_message_id is not None
