"""Partner chat: POS reads WhatsApp threads and replies (X-API-Key authed).

The POS can list a store's conversations, read one thread, send a reply (which
by default takes the bot off the thread), and toggle takeover back. Tenant-scoped
by the API key's restaurant.
"""
import pytest
from sqlalchemy import select

from app.conversation.models import Conversation, Message
from app.identity.models import Restaurant

pytestmark = pytest.mark.asyncio


async def _api_key(client, auth_headers) -> str:
    return (
        await client.post(
            "/api/v1/api-keys", json={"label": "POS"}, headers=auth_headers
        )
    ).json()["api_key"]


async def _restaurant(db_session) -> Restaurant:
    return await db_session.scalar(
        select(Restaurant).where(Restaurant.phone == "+971501234567")
    )


async def _seed_conversation(db_session, restaurant_id: int, phone: str) -> Conversation:
    conv = Conversation(
        restaurant_id=restaurant_id, phone=phone, counterpart="customer", state={}
    )
    db_session.add(conv)
    await db_session.flush()
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


async def test_partner_lists_conversations(client, auth_headers, db_session):
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000001")
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.get("/api/v1/partner/conversations", headers={"X-API-Key": key})
    assert resp.status_code == 200
    rows = resp.json()["items"]
    row = next(r for r in rows if r["id"] == conv.id)
    assert row["phone"] == "+971500000001"
    assert row["counterpart"] == "customer"
    assert row["manual_takeover"] is False
    assert row["last_message_preview"] == "I want biryani"
    assert row["unread"] is True  # customer spoke last


async def test_partner_reads_conversation_messages(client, auth_headers, db_session):
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000002")
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.get(
        f"/api/v1/partner/conversations/{conv.id}/messages",
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["phone"] == "+971500000002"
    assert body["manual_takeover"] is False
    items = body["items"]
    assert [m["direction"] for m in items] == ["outbound", "inbound"]  # id-ascending
    # outbound stored under 'body' surfaces as text
    assert items[0]["text"] == "Here is our menu"
    assert items[1]["text"] == "I want biryani"


async def test_partner_send_message_delivers_and_takes_over(
    client, auth_headers, db_session, monkeypatch
):
    from app.config import get_settings
    from app.outbox.models import OutboxMessage

    monkeypatch.setattr(get_settings(), "outbox_sync_delivery", True)
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000003")
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/conversations/{conv.id}/messages",
        headers={"X-API-Key": key},
        json={"text": "Your order is on the way 🚴"},
    )
    assert resp.status_code == 201
    assert resp.json()["direction"] == "outbound"
    assert resp.json()["text"] == "Your order is on the way 🚴"

    # thread shows the reply
    thread = await client.get(
        f"/api/v1/partner/conversations/{conv.id}/messages",
        headers={"X-API-Key": key},
    )
    assert any(
        m["direction"] == "outbound" and (m["text"] or "").startswith("Your order")
        for m in thread.json()["items"]
    )

    # delivered synchronously (mock provider -> 'sent')
    rows = (
        await db_session.execute(
            select(OutboxMessage).where(OutboxMessage.to_phone == "+971500000003")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "sent"

    # default take_over=True flips the flag so the bot stops answering
    await db_session.refresh(conv)
    assert conv.manual_takeover is True
    assert conv.taken_over_by == restaurant.id


async def test_partner_send_message_without_takeover(
    client, auth_headers, db_session, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "outbox_sync_delivery", True)
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000004")
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    resp = await client.post(
        f"/api/v1/partner/conversations/{conv.id}/messages",
        headers={"X-API-Key": key},
        json={"text": "quick note", "take_over": False},
    )
    assert resp.status_code == 201
    await db_session.refresh(conv)
    assert conv.manual_takeover is False


async def test_partner_takeover_toggle(client, auth_headers, db_session):
    restaurant = await _restaurant(db_session)
    conv = await _seed_conversation(db_session, restaurant.id, "+971500000005")
    await db_session.commit()
    key = await _api_key(client, auth_headers)

    on = await client.post(
        f"/api/v1/partner/conversations/{conv.id}/takeover",
        headers={"X-API-Key": key},
        json={"active": True},
    )
    assert on.status_code == 200
    assert on.json()["manual_takeover"] is True
    await db_session.refresh(conv)
    assert conv.manual_takeover is True

    off = await client.post(
        f"/api/v1/partner/conversations/{conv.id}/takeover",
        headers={"X-API-Key": key},
        json={"active": False},
    )
    assert off.status_code == 200
    await db_session.refresh(conv)
    assert conv.manual_takeover is False
    assert conv.taken_over_by is None


async def test_partner_chat_tenant_isolation(client, auth_headers, db_session):
    """A key for restaurant A cannot read/reply to restaurant B's conversation."""
    other = Restaurant(
        name="Other Store", email="other@example.com", phone="+971509999999",
        password_hash="x", lat=25.2, lng=55.3, settings={},
    )
    db_session.add(other)
    await db_session.flush()
    foreign = await _seed_conversation(db_session, other.id, "+971500000006")
    await db_session.commit()
    key = await _api_key(client, auth_headers)  # key belongs to +971501234567

    msgs = await client.get(
        f"/api/v1/partner/conversations/{foreign.id}/messages",
        headers={"X-API-Key": key},
    )
    assert msgs.status_code == 404

    send = await client.post(
        f"/api/v1/partner/conversations/{foreign.id}/messages",
        headers={"X-API-Key": key},
        json={"text": "hi"},
    )
    assert send.status_code == 404

    takeover = await client.post(
        f"/api/v1/partner/conversations/{foreign.id}/takeover",
        headers={"X-API-Key": key},
        json={"active": True},
    )
    assert takeover.status_code == 404


async def test_partner_send_unknown_conversation_is_404(client, auth_headers):
    key = await _api_key(client, auth_headers)
    resp = await client.post(
        "/api/v1/partner/conversations/999999/messages",
        headers={"X-API-Key": key},
        json={"text": "hi"},
    )
    assert resp.status_code == 404
