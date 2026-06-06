import asyncio
import logging

from celery import shared_task
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.outbox.models import OutboxMessage
from app.whatsapp.port import OutboundMessage, OutboundMessageType, WhatsAppPort

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3

# Statuses a delivery worker must never (re)send.
_TERMINAL_STATUSES = ("sent", "dead")


async def claim_pending_outbox_ids(
    session: AsyncSession, *, to_phone: str, restaurant_id: int
) -> list[int]:
    """Atomically claim this conversation's pending outbox rows for dispatch.

    Transitions matching rows ``pending -> dispatching`` in a single
    ``UPDATE ... RETURNING`` so two concurrent webhooks (or a webhook racing the
    sweeper) can never grab the same row: PostgreSQL serializes the row-level
    writes, and only the transaction that flips a row out of ``pending`` gets it
    back in ``RETURNING``. The loser's ``WHERE status='pending'`` no longer
    matches, so it claims (and dispatches) nothing for those rows.

    Caller is responsible for committing the surrounding transaction.
    """
    claimed = await session.execute(
        update(OutboxMessage)
        .where(
            OutboxMessage.status == "pending",
            OutboxMessage.to_phone == to_phone,
            OutboxMessage.restaurant_id == restaurant_id,
        )
        .values(status="dispatching")
        .returning(OutboxMessage.id)
    )
    return list(claimed.scalars().all())


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
        if row is None or row.status in _TERMINAL_STATUSES:
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
