import time
from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.media import (
    ATTACHMENT_TYPES,
    attachment_preview_label,
    inbound_media_id,
)
from app.conversation.models import Conversation, Message
from app.identity.phones import normalize_phone

_STREAMABLE_TYPES = frozenset(str(t) for t in ATTACHMENT_TYPES)

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


def _message_preview_text(message: Message) -> str | None:
    display = message_display_text(message.payload or {})
    if display:
        return display
    if message.type in _STREAMABLE_TYPES:
        return attachment_preview_label(message.type, message.payload or {})
    return None


def message_view_payload(message: Message) -> dict:
    """Payload for the dashboard, guaranteeing a ``text`` key so the React
    MessageBubble (which reads ``payload.text``) renders body-only rows too."""
    payload = dict(message.payload or {})
    if "text" not in payload:
        display = message_display_text(payload)
        if display is not None:
            payload["text"] = display
    has_media = bool(message.media_data or inbound_media_id(payload))
    payload["has_media"] = has_media
    payload["has_audio"] = message.type == "audio" and has_media
    if message.type in _STREAMABLE_TYPES:
        payload["media_kind"] = message.type
    filename = payload.get("filename")
    if isinstance(filename, str) and filename.strip():
        payload["filename"] = filename.strip()
    return payload


async def get_message_media(
    session: AsyncSession,
    *,
    restaurant_id: int,
    conversation_id: int,
    message_id: int,
) -> tuple[bytes, str, str | None] | None:
    """Return attachment bytes for dashboard viewing, or None if unavailable."""
    from app.conversation.models import Conversation

    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.restaurant_id != restaurant_id:
        return None
    msg = await session.get(Message, message_id)
    if msg is None or msg.conversation_id != conversation_id:
        return None
    if msg.type not in _STREAMABLE_TYPES:
        return None
    payload = msg.payload or {}
    mime = (
        msg.media_mime
        or payload.get("mime")
        or ("audio/ogg" if msg.type == "audio" else "application/octet-stream")
    ).split(";")[0].strip()
    if msg.media_data:
        filename = payload.get("filename") if isinstance(payload.get("filename"), str) else None
        return msg.media_data, mime, filename
    media_id = inbound_media_id(payload)
    if not media_id:
        return None
    try:
        from app.whatsapp.factory import get_whatsapp_provider

        data, fetched_mime = await get_whatsapp_provider().download_media(media_id)
        if not data:
            return None
        resolved = (fetched_mime or mime).split(";")[0].strip()
        filename = payload.get("filename") if isinstance(payload.get("filename"), str) else None
        return data, resolved, filename
    except Exception:
        return None


async def get_message_audio(
    session: AsyncSession,
    *,
    restaurant_id: int,
    conversation_id: int,
    message_id: int,
) -> tuple[bytes, str] | None:
    """Backward-compatible voice-note fetch for older clients."""
    result = await get_message_media(
        session,
        restaurant_id=restaurant_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )
    if result is None:
        return None
    data, mime, _filename = result
    return data, mime


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
    media_data: bytes | None = None,
    media_mime: str | None = None,
) -> Message:
    msg = Message(
        conversation_id=conversation_id,
        direction=direction,
        wa_message_id=wa_message_id,
        type=msg_type,
        payload=payload,
        ts=ts or int(time.time()),
        media_data=media_data,
        media_mime=media_mime,
    )
    session.add(msg)
    # Bump conversation activity so the dashboard list surfaces new rider/customer msgs.
    conv = await session.get(Conversation, conversation_id)
    if conv is not None:
        conv.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return msg


def _mirror_payload_for_dashboard(msg_type: str, payload: dict) -> dict:
    """Shape outbox payload for dashboard Message rows (matches engine _send_*)."""
    clean = {k: v for k, v in payload.items() if k != "type"}
    if str(msg_type).lower() in {"cta_url", "outboundmessagetype.cta_url"}:
        return {"type": "cta_url", **clean}
    return clean


async def maybe_record_customer_outbound(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    msg_type: str,
    payload: dict,
) -> Message | None:
    """Mirror outbound WhatsApp sends to the customer's dashboard thread.

    Skips riders (Drivers tab) and the restaurant's own business line (manager
    alerts). Best-effort: never raises."""
    from app.identity.models import Restaurant, Rider
    from app.identity.phones import normalize_phone, phone_lookup_values

    try:
        normalized = normalize_phone(to_phone)
        rider = await session.scalar(
            select(Rider).where(
                Rider.restaurant_id == restaurant_id,
                Rider.phone.in_(phone_lookup_values(normalized)),
            )
        )
        if rider is not None:
            return None

        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is not None and restaurant.phone:
            if normalized == normalize_phone(restaurant.phone):
                return None

        conv = await get_or_create_conversation(
            session,
            restaurant_id=restaurant_id,
            phone=normalized,
            counterpart="customer",
        )
        if conv.counterpart != "customer":
            conv.counterpart = "customer"

        record_payload = _mirror_payload_for_dashboard(msg_type, payload)
        msg_type_key = str(msg_type).lower().replace("outboundmessagetype.", "")
        return await record_message(
            session,
            conversation_id=conv.id,
            direction="outbound",
            wa_message_id=None,
            msg_type=msg_type_key,
            payload=record_payload,
        )
    except Exception:  # noqa: BLE001 — mirroring must never block delivery
        import logging

        logging.getLogger(__name__).exception(
            "failed to mirror customer outbound to conversation (restaurant %s)",
            restaurant_id,
        )
        return None


async def maybe_record_rider_outbound(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    msg_type: str,
    payload: dict,
) -> None:
    """Mirror outbound WhatsApp sends to a rider's dashboard thread (best-effort).

    Dispatch stop prompts and manager replies both flow through the outbox; recording
    them here lets the Chats → Drivers tab show the full conversation."""
    from app.identity.models import Rider
    from app.identity.phones import phone_lookup_values

    rider = await session.scalar(
        select(Rider).where(
            Rider.restaurant_id == restaurant_id,
            Rider.phone.in_(phone_lookup_values(to_phone)),
        )
    )
    if rider is None:
        return
    conv = await get_or_create_conversation(
        session,
        restaurant_id=restaurant_id,
        phone=normalize_phone(rider.phone),
        counterpart="rider",
    )
    if conv.counterpart != "rider":
        conv.counterpart = "rider"
    await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type=msg_type,
        payload=payload,
    )


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


async def reset_conversation_state(
    session: AsyncSession,
    *,
    conversation_id: int,
    restaurant_id: int | None = None,
) -> bool:
    """Clear a conversation's bot state and disable manual takeover.

    Keeps message history intact, but removes any stale draft/order pointers so
    the next inbound message starts a fresh ordering flow.
    """
    conv = await session.get(Conversation, conversation_id)
    if conv is None or (restaurant_id is not None and conv.restaurant_id != restaurant_id):
        return False
    conv.state = {}
    conv.manual_takeover = False
    conv.taken_over_by = None
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
    import uuid

    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.restaurant_id != restaurant_id:
        return None

    outbox = await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=conv.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": text},
        idempotency_key=f"manual:{conversation_id}:{uuid.uuid4().hex}",
        mirror_rider_conversation=False,
    )
    await session.flush()  # assign outbox.id
    msg = await session.scalar(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.direction == "outbound")
        .order_by(Message.id.desc())
        .limit(1)
    )
    if msg is None:
        return None
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
    if not convs:
        return []

    conv_ids = [c.id for c in convs]

    latest_ids = list(
        (
            await session.scalars(
                select(func.max(Message.id))
                .where(Message.conversation_id.in_(conv_ids))
                .group_by(Message.conversation_id)
            )
        ).all()
    )
    last_by_conv: dict[int, Message] = {}
    if latest_ids:
        for msg in (
            await session.scalars(select(Message).where(Message.id.in_(latest_ids)))
        ).all():
            last_by_conv[msg.conversation_id] = msg

    items: list[dict] = []
    for conv in convs:
        last = last_by_conv.get(conv.id)
        preview = _message_preview_text(last) if last else None
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
                "_last_msg_id": last.id if last else 0,
            }
        )
    items.sort(key=lambda row: row["_last_msg_id"], reverse=True)
    for row in items:
        row.pop("_last_msg_id", None)
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
