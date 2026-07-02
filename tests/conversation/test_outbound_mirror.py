"""Outbound WhatsApp sends must mirror into the customer Conversations thread."""

from sqlalchemy import func, select

from app.conversation.models import Conversation, Message
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType


async def test_enqueue_mirrors_customer_outbound_once(db_session, restaurant):
    phone = "+971509876543"
    await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone=phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "Order confirmed! 🎉"},
        idempotency_key="mirror-test-1",
    )
    await db_session.commit()

    conv = await db_session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant.id,
            Conversation.phone == phone,
        )
    )
    assert conv is not None
    assert conv.counterpart == "customer"
    count = await db_session.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conv.id, Message.direction == "outbound")
    )
    assert count == 1
    body = (
        await db_session.scalars(
            select(Message.payload).where(
                Message.conversation_id == conv.id, Message.direction == "outbound"
            )
        )
    ).first()
    assert body["body"] == "Order confirmed! 🎉"


async def test_enqueue_idempotent_does_not_duplicate_mirror(db_session, restaurant):
    phone = "+971509876544"
    key = "mirror-dup-1"
    await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone=phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "Hello"},
        idempotency_key=key,
    )
    await db_session.commit()
    await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone=phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "Hello again"},
        idempotency_key=key,
    )
    await db_session.commit()

    conv = await db_session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant.id,
            Conversation.phone == phone,
        )
    )
    count = await db_session.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conv.id, Message.direction == "outbound")
    )
    assert count == 1


async def test_error_apology_payload_mirrored_via_enqueue(db_session, restaurant):
    """Webhook error apologies use enqueue_message — same mirror path as all outbound."""
    phone = "+971509876545"
    await enqueue_message(
        db_session,
        restaurant_id=restaurant.id,
        to_phone=phone,
        msg_type=OutboundMessageType.TEXT,
        payload={
            "body": (
                "Sorry, something went wrong on our end 🙏 Please send that "
                "again in a moment and we'll take care of it."
            ),
        },
        idempotency_key="err-apology-wamid.err-test",
    )
    await db_session.commit()

    conv = await db_session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant.id,
            Conversation.phone == phone,
        )
    )
    assert conv is not None
    msg = await db_session.scalar(
        select(Message).where(
            Message.conversation_id == conv.id, Message.direction == "outbound"
        )
    )
    assert msg is not None
    assert "something went wrong" in msg.payload.get("body", "").lower()