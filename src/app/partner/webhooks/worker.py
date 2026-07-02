"""Celery worker for partner webhook delivery."""
from __future__ import annotations

import asyncio
import logging

from celery import shared_task

logger = logging.getLogger(__name__)

_TASK_MAX_RETRIES = 5


def _backoff_countdown(retries: int) -> int:
    return 10 * (2 ** retries)


@shared_task(name="partner.deliver_webhook", bind=True, max_retries=_TASK_MAX_RETRIES)
def deliver_partner_webhook_task(self, delivery_id: int) -> None:  # type: ignore[override]
    """Deliver one partner webhook with exponential backoff."""
    from app.db import async_session_factory, get_engine
    from app.partner.webhooks.deliver import deliver_partner_webhook_one

    async def _run() -> str | None:
        await deliver_partner_webhook_one(
            delivery_id, session_factory=async_session_factory
        )
        async with async_session_factory() as session:
            from app.partner.webhooks.models import PartnerWebhookDelivery

            row = await session.get(PartnerWebhookDelivery, delivery_id)
            if row is None:
                return None
            return row.status

    async def _wrapped() -> str | None:
        try:
            return await _run()
        finally:
            await get_engine().dispose()

    try:
        final_status = asyncio.run(_wrapped())
    except Exception as exc:
        if self.request.retries >= _TASK_MAX_RETRIES:
            logger.error(
                "partner webhook max retries id=%s — giving up", delivery_id
            )
            return
        countdown = _backoff_countdown(self.request.retries)
        logger.warning(
            "partner webhook transient failure id=%s retries=%s countdown=%ss: %s",
            delivery_id,
            self.request.retries,
            countdown,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown) from exc

    if final_status == "failed":
        if self.request.retries >= _TASK_MAX_RETRIES:
            return
        countdown = _backoff_countdown(self.request.retries)
        raise self.retry(countdown=countdown)