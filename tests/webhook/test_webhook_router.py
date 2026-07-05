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
            "email": "webhook@rest.ae",
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
    # Greeting renders the menu without internal dish numbers (not shown to
    # customers per spec); name + price on one bullet line.
    assert "Chicken Biryani: AED 22" in rows[0].payload["body"]


async def test_post_webhook_duplicate_skips_engine_before_second_outbox(client, db_session):
    """Insert-first idempotency: the duplicate must not enqueue a second reply."""
    from unittest.mock import patch

    from sqlalchemy import func, select

    from app.webhook.models import WebhookEvent

    await _seed_restaurant_and_menu(client, db_session)

    calls: list[str] = []

    async def _spy(session, inbound, restaurant_id):
        calls.append(inbound.wa_message_id)
        from app.conversation.engine import handle_inbound as real

        return await real(session, inbound, restaurant_id=restaurant_id)

    body, sig = _signed_body(_TEXT_PAYLOAD)
    with patch("app.webhook.router.handle_inbound", side_effect=_spy):
        await client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        await client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )

    assert calls == ["wamid.unique-e2e-001"]
    evt_count = await db_session.scalar(
        select(func.count()).select_from(WebhookEvent).where(
            WebhookEvent.provider_event_id == "wamid.unique-e2e-001"
        )
    )
    assert evt_count == 1


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


def _confirm_button_payload(*, wa_id: str, from_digits: str = "971585997894") -> dict:
    return {
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
                                    "id": wa_id,
                                    "from": from_digits,
                                    "timestamp": "1717660800",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": "confirm_order",
                                            "title": "Confirm order",
                                        },
                                    },
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ]
            }
        ],
    }


async def _seed_confirm_ready_state(db_session, restaurant_id: int) -> None:
    """Customer at awaiting_confirmation with a pending order ready to confirm."""
    from sqlalchemy import select

    from app.conversation.models import Conversation
    from app.menu.models import Dish
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

    customer = Customer(
        restaurant_id=restaurant_id,
        phone="+971585997894",
        name="Syed",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id,
        latitude=25.21,
        longitude=55.27,
        room_apartment="816",
        building="1-14",
        receiver_name="Syed",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        order_number="R1-0140",
        status="pending_confirmation",
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("15.00"),
        total=Decimal("15.00"),
        address_id=addr.id,
        distance_km=1.5,
    )
    db_session.add(order)
    await db_session.flush()
    dish = (
        await db_session.scalars(
            select(Dish).where(
                Dish.restaurant_id == restaurant_id, Dish.dish_number == 110
            )
        )
    ).first()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=110,
            dish_name="Chicken Soup",
            price_aed=Decimal("15.00"),
            qty=1,
        )
    )
    conv = Conversation(
        restaurant_id=restaurant_id,
        phone="+971585997894",
        counterpart="customer",
        state={
            "dialogue_phase": "awaiting_confirmation",
            "dialogue_state": "order_confirmation",
            "pending_order_id": order.id,
        },
    )
    db_session.add(conv)
    await db_session.commit()


async def test_confirm_order_celery_enqueue_failure_no_error_apology(
    client, db_session,
):
    """Order confirm must not send the generic apology when only delivery enqueue fails."""
    from unittest.mock import patch

    from sqlalchemy import select

    from app.ordering.models import Order
    from app.outbox.models import OutboxMessage

    restaurant_id = await _seed_restaurant_and_menu(client, db_session)
    await _seed_confirm_ready_state(db_session, restaurant_id)

    payload = _confirm_button_payload(wa_id="wamid.confirm-0140")
    body, sig = _signed_body(payload)

    def _boom(*args, **kwargs):
        raise ConnectionError("redis unavailable")

    with patch(
        "app.webhook.router.deliver_outbox_message.apply_async",
        side_effect=_boom,
    ):
        resp = await client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert resp.status_code == 200

    order = await db_session.scalar(
        select(Order).where(Order.order_number == "R1-0140")
    )
    assert order is not None
    assert order.status == "confirmed"

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    bodies = [r.payload.get("body", "") for r in rows]
    assert any("Order confirmed" in b for b in bodies), bodies
    assert not any(
        "something went wrong on our end" in b.lower() for b in bodies
    ), bodies


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
