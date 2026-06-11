"""Manager-dashboard conversations read API (/api/v1/conversations)."""

from sqlalchemy import select

from app.conversation.models import Conversation, Message
from app.identity.models import Restaurant


async def _seed_conversation(db_session, restaurant_id: int, phone: str) -> Conversation:
    conv = Conversation(
        restaurant_id=restaurant_id, phone=phone, counterpart="customer", state={}
    )
    db_session.add(conv)
    await db_session.flush()
    # outbound first (lower id), inbound last (higher id) -> "customer spoke last"
    db_session.add(
        Message(conversation_id=conv.id, direction="outbound", type="text",
                payload={"body": "Here is our menu"}, ts=100)
    )
    db_session.add(
        Message(conversation_id=conv.id, direction="inbound", type="text",
                payload={"text": "I want biryani"}, ts=200)
    )
    await db_session.flush()
    return conv


async def _restaurant(db_session) -> Restaurant:
    return await db_session.scalar(
        select(Restaurant).where(Restaurant.phone == "+971501234567")
    )


async def test_list_conversations_returns_real_data(client, auth_headers, db_session):
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000001")

    resp = await client.get("/api/v1/conversations", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    row = next(r for r in rows if r["id"] == conv.id)
    assert row["phone"] == "+971500000001"
    assert row["counterpart"] == "customer"
    assert row["manual_takeover"] is False
    assert row["last_message_preview"] == "I want biryani"  # from the last message
    assert row["unread"] is True  # customer spoke last
    assert row["updated_at"]  # ISO timestamp present


async def test_messages_endpoint_normalizes_body_to_text(client, auth_headers, db_session):
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000002")

    resp = await client.get(
        f"/api/v1/conversations/{conv.id}/messages", headers=auth_headers
    )
    assert resp.status_code == 200
    msgs = resp.json()
    assert [m["direction"] for m in msgs] == ["outbound", "inbound"]  # id-ascending
    # outbound stored under 'body' must surface as 'text' for the React bubble
    assert msgs[0]["payload"]["text"] == "Here is our menu"
    assert msgs[1]["payload"]["text"] == "I want biryani"


async def test_messages_unknown_conversation_is_404(client, auth_headers, db_session):
    resp = await client.get("/api/v1/conversations/999999/messages", headers=auth_headers)
    assert resp.status_code == 404


async def test_other_restaurants_conversation_is_404(client, auth_headers, db_session):
    # Conversation owned by a DIFFERENT restaurant must not be visible.
    other = Restaurant(
        name="Other", phone="+971599999999", password_hash="x", lat=25.0, lng=55.0
    )
    db_session.add(other)
    await db_session.flush()
    conv = await _seed_conversation(db_session, other.id, "+971500000003")

    resp = await client.get(
        f"/api/v1/conversations/{conv.id}/messages", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_requires_auth(client):
    resp = await client.get("/api/v1/conversations")
    assert resp.status_code == 401


async def test_takeover_toggles_flag(client, auth_headers, db_session):
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000010")
    await db_session.commit()

    on = await client.post(
        f"/api/v1/conversations/{conv.id}/takeover",
        headers=auth_headers,
        json={"active": True},
    )
    assert on.status_code == 204
    await db_session.refresh(conv)
    assert conv.manual_takeover is True
    assert conv.taken_over_by == restaurant.id

    off = await client.post(
        f"/api/v1/conversations/{conv.id}/takeover",
        headers=auth_headers,
        json={"active": False},
    )
    assert off.status_code == 204
    await db_session.refresh(conv)
    assert conv.manual_takeover is False
    assert conv.taken_over_by is None


async def test_takeover_other_tenant_is_404(client, auth_headers, db_session):
    other = Restaurant(
        name="Other2", phone="+971599999998", password_hash="x", lat=25.0, lng=55.0
    )
    db_session.add(other)
    await db_session.flush()
    conv = await _seed_conversation(db_session, other.id, "+971500000011")
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/conversations/{conv.id}/takeover",
        headers=auth_headers,
        json={"active": True},
    )
    assert resp.status_code == 404


async def test_send_message_records_outbound_and_delivers(
    client, auth_headers, db_session, monkeypatch
):
    """Manager send must (1) store an outbound message visible in the thread and
    (2) actually deliver via WhatsApp — with sync delivery the outbox row ends
    'sent'. This is the bug the user hit: takeover/send were 404 no-ops."""
    from app.config import get_settings
    from app.outbox.models import OutboxMessage

    monkeypatch.setattr(get_settings(), "outbox_sync_delivery", True)
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000012")
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/conversations/{conv.id}/messages",
        headers=auth_headers,
        json={"text": "Your order is on the way 🚴"},
    )
    assert resp.status_code == 201
    assert resp.json()["direction"] == "outbound"
    assert resp.json()["payload"]["text"] == "Your order is on the way 🚴"

    # the thread now shows the manager message
    thread = await client.get(
        f"/api/v1/conversations/{conv.id}/messages", headers=auth_headers
    )
    assert any(
        m["direction"] == "outbound" and m["payload"]["text"].startswith("Your order")
        for m in thread.json()
    )

    # delivered synchronously to the customer's phone (mock provider -> 'sent')
    rows = (
        await db_session.execute(
            select(OutboxMessage).where(OutboxMessage.to_phone == "+971500000012")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "sent"
    assert rows[0].wa_message_id is not None


async def test_send_message_unknown_conversation_is_404(client, auth_headers):
    resp = await client.post(
        "/api/v1/conversations/999999/messages",
        headers=auth_headers,
        json={"text": "hello"},
    )
    assert resp.status_code == 404
