from sqlalchemy import select

from app.conversation.models import Message
from app.conversation.service import (
    get_or_create_conversation,
    record_message,
    set_manual_takeover,
)


async def test_get_or_create_creates_new_conversation(db_session, restaurant):
    conv = await get_or_create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971509876543",
        counterpart="customer",
    )
    assert conv.id is not None
    assert conv.state == {}
    assert conv.manual_takeover is False


async def test_get_or_create_returns_existing(db_session, restaurant):
    conv1 = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971509876543", counterpart="customer"
    )
    await db_session.commit()
    conv2 = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971509876543", counterpart="customer"
    )
    assert conv1.id == conv2.id


async def test_record_inbound_message(db_session, restaurant):
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971509876543", counterpart="customer"
    )
    await db_session.commit()

    await record_message(
        db_session,
        conversation_id=conv.id,
        direction="inbound",
        wa_message_id="wamid.test1",
        msg_type="text",
        payload={"text": "hi"},
        ts=1717660800,
    )
    await db_session.commit()

    row = (await db_session.execute(select(Message))).scalar_one()
    assert row.direction == "inbound"
    assert row.payload["text"] == "hi"


async def test_set_manual_takeover(db_session, restaurant):
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971509876543", counterpart="customer"
    )
    await db_session.commit()

    await set_manual_takeover(db_session, conversation_id=conv.id, taken_over_by=42)
    await db_session.commit()

    await db_session.refresh(conv)
    assert conv.manual_takeover is True
    assert conv.taken_over_by == 42
