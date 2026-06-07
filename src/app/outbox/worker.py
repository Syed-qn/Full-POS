import asyncio
import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.metrics import OUTBOX_DELIVERIES
from app.outbox.models import OutboxMessage
from app.whatsapp.port import OutboundMessage, OutboundMessageType, WhatsAppPort

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_TASK_MAX_RETRIES = 5

# Statuses a delivery worker must never (re)send.
_TERMINAL_STATUSES = ("sent", "dead")


def _backoff_countdown(retries: int) -> int:
    """Return countdown seconds: base 10s, doubles each retry (10,20,40,80,160)."""
    return 10 * (2 ** retries)


def _is_permanent_failure(status_code: int) -> bool:
    """4xx (except 429) = permanent failure; 5xx/network = transient."""
    return 400 <= status_code < 500 and status_code != 429


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
            OUTBOX_DELIVERIES.labels(status="sent").inc()
        except Exception as exc:
            row.attempts += 1
            logger.warning("outbox delivery failed for id=%s: %s", outbox_id, exc)
            if row.attempts >= _MAX_ATTEMPTS:
                row.status = "dead"
                OUTBOX_DELIVERIES.labels(status="dead").inc()
            else:
                row.status = "failed"
                OUTBOX_DELIVERIES.labels(status="retry").inc()
        await session.commit()


async def _mark_dead(outbox_id: int, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Mark an outbox message as dead (unrecoverable) in the DB."""
    async with session_factory() as session:
        row = await session.get(OutboxMessage, outbox_id)
        if row is not None and row.status not in _TERMINAL_STATUSES:
            row.status = "dead"
            row.attempts += 1
            OUTBOX_DELIVERIES.labels(status="dead").inc()
            await session.commit()


@shared_task(name="outbox.deliver", bind=True, max_retries=_TASK_MAX_RETRIES)
def deliver_outbox_message(self, outbox_id: int) -> None:
    """Celery task: deliver one outbox message via the configured provider.

    Uses exponential back-off (10s, 20s, 40s, 80s, 160s).  After max_retries
    the message is marked ``dead`` and no further retries occur.
    """
    from app.db import async_session_factory
    from app.whatsapp.factory import get_whatsapp_provider

    provider = get_whatsapp_provider()
    try:
        asyncio.run(
            _deliver_one(outbox_id, provider=provider, session_factory=async_session_factory)
        )
    except Exception as exc:
        # Check for permanent 4xx failures (not 429) — mark dead immediately.
        status_code: int | None = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code is not None and _is_permanent_failure(status_code):
            logger.error(
                "outbox permanent failure id=%s status=%s — marking dead", outbox_id, status_code
            )
            asyncio.run(_mark_dead(outbox_id, session_factory=async_session_factory))
            return

        # Transient error — retry with exponential back-off or mark dead.
        if self.request.retries >= _TASK_MAX_RETRIES:
            logger.error(
                "outbox max retries reached for id=%s — marking dead", outbox_id
            )
            asyncio.run(_mark_dead(outbox_id, session_factory=async_session_factory))
            return

        countdown = _backoff_countdown(self.request.retries)
        logger.warning(
            "outbox transient failure id=%s retries=%s countdown=%ss: %s",
            outbox_id, self.request.retries, countdown, exc,
        )
        OUTBOX_DELIVERIES.labels(status="retry").inc()
        raise self.retry(exc=exc, countdown=countdown)


_SWEEPER_STALE_MINUTES = 5


async def _sweep_stale_pending(session_factory: async_sessionmaker[AsyncSession]) -> list[int]:
    """Find pending outbox rows stuck for > _SWEEPER_STALE_MINUTES and re-dispatch them.

    Rows matching: status='pending' AND updated_at < NOW()-5min AND attempts < _MAX_ATTEMPTS.
    Returns list of outbox IDs re-dispatched.
    """
    # DB stores timestamps as UTC naive (TimestampMixin uses server_default=func.now())
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=_SWEEPER_STALE_MINUTES)).replace(tzinfo=None)
    async with session_factory() as session:
        result = await session.execute(
            select(OutboxMessage.id).where(
                OutboxMessage.status == "pending",
                OutboxMessage.updated_at < cutoff,
                OutboxMessage.attempts < _MAX_ATTEMPTS,
            )
        )
        stale_ids = list(result.scalars().all())

    for outbox_id in stale_ids:
        deliver_outbox_message.apply_async(args=[outbox_id])
        logger.info("outbox sweeper re-dispatched stale id=%s", outbox_id)

    return stale_ids


@shared_task(name="outbox.sweep_failed")
def sweep_failed_outbox() -> int:
    """Celery beat task: orphan-recovery for stale pending outbox rows.

    Picks up rows with status='pending' that have not been updated in
    more than 5 minutes (e.g. worker crash before the deliver task was enqueued)
    and re-dispatches them via deliver_outbox_message.apply_async.

    Returns the count of rows re-dispatched.
    """
    from app.db import async_session_factory

    stale_ids = asyncio.run(_sweep_stale_pending(async_session_factory))
    if stale_ids:
        logger.info("outbox sweeper recovered %d stale rows: %s", len(stale_ids), stale_ids)
    return len(stale_ids)
