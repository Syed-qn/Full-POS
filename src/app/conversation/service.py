from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.models import Conversation, Message

_PREVIEW_MAX = 80


def message_display_text(payload: dict) -> str | None:
    """Best human-readable string for a stored message payload.

    Outbound rows store the text under ``body``; inbound text under ``text``;
    interactive replies under ``title``; locations have lat/lng. Falls back to
    None so callers can decide how to render non-text events.
    """
    for key in ("text", "body", "title", "caption"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if "latitude" in payload and "longitude" in payload:
        return "📍 Location"
    return None


def message_view_payload(message: Message) -> dict:
    """Payload for the dashboard, guaranteeing a ``text`` key so the React
    MessageBubble (which reads ``payload.text``) renders body-only rows too."""
    payload = dict(message.payload or {})
    if "text" not in payload:
        display = message_display_text(payload)
        if display is not None:
            payload["text"] = display
    return payload


async def get_or_create_conversation(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
    counterpart: str,
) -> Conversation:
    existing = await session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant_id,
            Conversation.phone == phone,
        )
    )
    if existing is not None:
        return existing
    conv = Conversation(
        restaurant_id=restaurant_id,
        phone=phone,
        counterpart=counterpart,
        state={},
    )
    session.add(conv)
    await session.flush()
    return conv


async def record_message(
    session: AsyncSession,
    *,
    conversation_id: int,
    direction: str,
    wa_message_id: str | None,
    msg_type: str,
    payload: dict,
    ts: int = 0,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        direction=direction,
        wa_message_id=wa_message_id,
        type=msg_type,
        payload=payload,
        ts=ts,
    )
    session.add(msg)
    return msg


async def set_manual_takeover(
    session: AsyncSession,
    *,
    conversation_id: int,
    taken_over_by: int,
    active: bool = True,
    restaurant_id: int | None = None,
) -> bool:
    """Toggle manual takeover. When ``restaurant_id`` is given it acts as a tenant
    guard: returns False (no change) if the conversation is missing or owned by a
    different restaurant. Turning takeover off clears ``taken_over_by``."""
    conv = await session.get(Conversation, conversation_id)
    if conv is None or (restaurant_id is not None and conv.restaurant_id != restaurant_id):
        return False
    conv.manual_takeover = active
    conv.taken_over_by = taken_over_by if active else None
    return True


async def send_manual_message(
    session: AsyncSession,
    *,
    restaurant_id: int,
    conversation_id: int,
    text: str,
) -> tuple[Message, int] | None:
    """Record a manager-authored outbound message and enqueue it for WhatsApp
    delivery. Returns (message, outbox_id) or None if the conversation is missing
    or belongs to another restaurant. Caller commits, then dispatches outbox_id."""
    import time
    import uuid

    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.restaurant_id != restaurant_id:
        return None

    ts = int(time.time())
    payload = {"body": text}
    msg = await record_message(
        session,
        conversation_id=conversation_id,
        direction="outbound",
        wa_message_id=None,
        msg_type="text",
        payload=payload,
        ts=ts,
    )
    await session.flush()  # assign msg.id

    outbox = await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=conv.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": text},
        idempotency_key=f"manual:{conversation_id}:{uuid.uuid4().hex}",
    )
    await session.flush()  # assign outbox.id
    return msg, outbox.id


async def list_dashboard_conversations(
    session: AsyncSession, *, restaurant_id: int
) -> list[dict]:
    """Conversations for the manager dashboard, newest-activity first, each with
    a last-message preview and an unread flag (unread = customer spoke last)."""
    convs = (
        await session.scalars(
            select(Conversation)
            .where(Conversation.restaurant_id == restaurant_id)
            .order_by(desc(Conversation.updated_at))
        )
    ).all()

    items: list[dict] = []
    for conv in convs:
        last = await session.scalar(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(desc(Message.id))
            .limit(1)
        )
        preview = message_display_text(last.payload) if last else None
        if preview and len(preview) > _PREVIEW_MAX:
            preview = preview[:_PREVIEW_MAX].rstrip() + "…"
        items.append(
            {
                "id": conv.id,
                "phone": conv.phone,
                "counterpart": conv.counterpart,
                "manual_takeover": conv.manual_takeover,
                "last_message_preview": preview,
                "unread": bool(last and last.direction == "inbound"),
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else "",
            }
        )
    return items


async def get_dashboard_messages(
    session: AsyncSession, *, restaurant_id: int, conversation_id: int
) -> list[Message] | None:
    """All messages for one conversation, oldest-first. Returns None when the
    conversation does not exist or belongs to another restaurant (tenant guard)."""
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.restaurant_id != restaurant_id:
        return None
    return list(
        (
            await session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.id.asc())
            )
        ).all()
    )
