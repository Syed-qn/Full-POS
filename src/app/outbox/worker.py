import asyncio
import logging

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.outbox.models import OutboxMessage
from app.whatsapp.port import OutboundMessage, OutboundMessageType, WhatsAppPort

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3


def _outbox_row_to_outbound(row: OutboxMessage) -> OutboundMessage:
    payload = dict(row.payload)
    msg_type = OutboundMessageType(payload.pop("type"))
    return OutboundMessage(
        to_phone=row.to_phone,
        type=msg_type,
        payload=payload,
        idempotency_key=row.idempotency_key,
    )


async def _deliver_one(
    outbox_id: int,
    *,
    provider: WhatsAppPort,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        row = await session.get(OutboxMessage, outbox_id)
        if row is None or row.status in ("sent", "dead"):
            return
        msg = _outbox_row_to_outbound(row)
        try:
            wa_id = await provider.send(msg)
            row.status = "sent"
            row.wa_message_id = wa_id
            row.attempts += 1
        except Exception as exc:
            row.attempts += 1
            logger.warning("outbox delivery failed for id=%s: %s", outbox_id, exc)
            row.status = "dead" if row.attempts >= _MAX_ATTEMPTS else "failed"
        await session.commit()


@shared_task(name="outbox.deliver", bind=True, max_retries=0)
def deliver_outbox_message(self, outbox_id: int) -> None:
    """Celery task: deliver one outbox message via the configured provider."""
    from app.db import async_session_factory
    from app.whatsapp.factory import get_whatsapp_provider

    provider = get_whatsapp_provider()
    asyncio.run(
        _deliver_one(outbox_id, provider=provider, session_factory=async_session_factory)
    )
