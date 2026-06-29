"""Rider messages must surface on the manager Chats → Drivers tab."""

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation, Message
from app.conversation.service import list_dashboard_conversations
from app.identity.models import Restaurant, Rider
from app.outbox.models import OutboxMessage
from app.outbox.service import enqueue_message
from app.whatsapp.port import InboundMessage, MessageType, OutboundMessageType


async def _seed_rider(db_session, *, phone: str = "+971509990000"):
    r = Restaurant(name="R", phone="+9712223333", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="Rider Ali",
        phone=phone,
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.commit()
    return r, rider


async def test_rider_free_text_recorded_and_notifies_manager(db_session):
    """Legacy rider phone without '+' still matches; manager gets a WhatsApp alert."""
    r, rider = await _seed_rider(db_session, phone="971509990000")
    inbound = InboundMessage(
        wa_message_id="rider-text-1",
        from_phone="+971509990000",
        type=MessageType.TEXT,
        payload={"text": "Customer not answering, what should I do?"},
        restaurant_phone=r.phone,
        timestamp=1_700_000_000,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()

    conv = await db_session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == r.id,
            Conversation.phone == "+971509990000",
        )
    )
    assert conv is not None
    assert conv.counterpart == "rider"
    assert conv.manual_takeover is True

    inbound_msg = await db_session.scalar(
        select(Message).where(
            Message.conversation_id == conv.id, Message.direction == "inbound"
        )
    )
    assert inbound_msg is not None
    assert inbound_msg.payload["text"] == "Customer not answering, what should I do?"

    outbox = (
        await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.restaurant_id == r.id)
        )
    ).all()
    bodies = [row.payload.get("body", "") for row in outbox]
    assert any("manager has been notified" in b.lower() for b in bodies)
    mgr_alert = next(b for b in bodies if "Driver Rider Ali" in b)
    assert "Customer not answering" in mgr_alert
    assert "Chats" in mgr_alert


async def test_rider_outbound_dispatch_mirrored_to_conversation(db_session):
    r, rider = await _seed_rider(db_session)
    await enqueue_message(
        db_session,
        restaurant_id=r.id,
        to_phone=rider.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "New batch: 2 stops. Tap when picked up."},
        idempotency_key="test-stop-1",
    )
    await db_session.commit()

    conv = await db_session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == r.id, Conversation.phone == "+971509990000"
        )
    )
    assert conv is not None
    assert conv.counterpart == "rider"
    outbound = await db_session.scalar(
        select(Message).where(
            Message.conversation_id == conv.id, Message.direction == "outbound"
        )
    )
    assert outbound is not None
    assert "New batch" in outbound.payload["body"]


async def test_rider_inbound_surfaces_in_dashboard_list(db_session):
    r, rider = await _seed_rider(db_session)
    inbound = InboundMessage(
        wa_message_id="rider-text-2",
        from_phone=rider.phone,
        type=MessageType.TEXT,
        payload={"text": "Running 10 min late"},
        restaurant_phone=r.phone,
        timestamp=1_700_000_100,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()

    rows = await list_dashboard_conversations(db_session, restaurant_id=r.id)
    rider_row = next(row for row in rows if row["counterpart"] == "rider")
    assert rider_row["unread"] is True
    assert "Running 10 min late" in (rider_row["last_message_preview"] or "")