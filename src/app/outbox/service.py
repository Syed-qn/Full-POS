from sqlalchemy.ext.asyncio import AsyncSession

from app.outbox.models import OutboxMessage
from app.whatsapp.port import OutboundMessageType


async def enqueue_message(
    session: AsyncSession,
    *,
    restaurant_id: int,
    to_phone: str,
    msg_type: OutboundMessageType,
    payload: dict,
    idempotency_key: str,
) -> OutboxMessage:
    """Write an outbox row in the caller's transaction. Commit is the caller's responsibility."""
    row = OutboxMessage(
        restaurant_id=restaurant_id,
        to_phone=to_phone,
        payload={"type": str(msg_type), **payload},
        idempotency_key=idempotency_key,
    )
    session.add(row)
    return row
