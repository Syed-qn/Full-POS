from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.models import Conversation, Message


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
) -> None:
    conv = await session.get(Conversation, conversation_id)
    if conv is None:
        raise ValueError(f"conversation {conversation_id} not found")
    conv.manual_takeover = True
    conv.taken_over_by = taken_over_by
