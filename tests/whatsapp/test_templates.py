"""Window-aware customer notifications + utility template registration."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.conversation.models import Message
from app.conversation.service import get_or_create_conversation
from app.identity.models import Restaurant
from app.marketing.models import WaTemplate
from app.outbox.models import OutboxMessage
from app.whatsapp.templates import (
    UTILITY_TEMPLATES,
    notify_customer,
    register_utility_templates,
)


@pytest.fixture
async def restaurant(db_session) -> Restaurant:
    r = Restaurant(name="Notify R", phone="+97140000099", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    return r


async def _conv_with_inbound(db_session, r, phone, *, ts: int):
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=phone, counterpart="customer")
    db_session.add(Message(conversation_id=conv.id, direction="inbound", type="text",
                           payload={"body": "hi"}, ts=ts))
    await db_session.flush()
    return conv


async def _last_outbox(db_session, r_id):
    rows = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.restaurant_id == r_id).order_by(OutboxMessage.id.desc())
    )).all()
    return rows[0] if rows else None


async def test_within_window_sends_session_text(db_session, restaurant):
    phone = "+971555000901"
    now = int(datetime.now(timezone.utc).timestamp())
    await _conv_with_inbound(db_session, restaurant, phone, ts=now - 3600)  # 1h ago
    await notify_customer(
        db_session, restaurant_id=restaurant.id, phone=phone,
        session_text="hello session", template_key="wallet_credit_added",
        variables=["10.00", "Notify R"], idempotency_key="n1",
    )
    msg = await _last_outbox(db_session, restaurant.id)
    assert msg.payload["type"] == "text"
    assert "hello session" in msg.payload["body"]


async def test_outside_window_sends_template(db_session, restaurant):
    phone = "+971555000902"
    now = int(datetime.now(timezone.utc).timestamp())
    await _conv_with_inbound(db_session, restaurant, phone, ts=now - 200000)  # >24h ago
    await notify_customer(
        db_session, restaurant_id=restaurant.id, phone=phone,
        session_text="hello session", template_key="wallet_credit_added",
        variables=["10.00", "Notify R"], idempotency_key="n2",
    )
    msg = await _last_outbox(db_session, restaurant.id)
    assert msg.payload["type"] == "template"
    assert msg.payload["name"] == "wallet_credit_added"
    params = msg.payload["components"][0]["parameters"]
    assert params[0]["text"] == "10.00"


async def test_no_conversation_uses_template(db_session, restaurant):
    await notify_customer(
        db_session, restaurant_id=restaurant.id, phone="+971555000903",
        session_text="x", template_key="coupon_issued",
        variables=["Notify R", "SAVE-X", "15.00"], idempotency_key="n3",
    )
    msg = await _last_outbox(db_session, restaurant.id)
    assert msg.payload["type"] == "template"


async def test_register_utility_templates(db_session, restaurant):
    names = await register_utility_templates(db_session, restaurant_id=restaurant.id)
    assert set(names) == set(UTILITY_TEMPLATES.keys())
    rows = (await db_session.scalars(
        select(WaTemplate).where(WaTemplate.restaurant_id == restaurant.id)
    )).all()
    assert {r.meta_template_name for r in rows} == set(UTILITY_TEMPLATES.keys())
    assert all(r.category == "utility" and r.ephemeral is False for r in rows)
    # Idempotent.
    again = await register_utility_templates(db_session, restaurant_id=restaurant.id)
    assert set(again) == set(UTILITY_TEMPLATES.keys())
    rows2 = (await db_session.scalars(
        select(WaTemplate).where(WaTemplate.restaurant_id == restaurant.id)
    )).all()
    assert len(rows2) == len(UTILITY_TEMPLATES)  # no duplicates
