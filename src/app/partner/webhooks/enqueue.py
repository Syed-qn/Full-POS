"""Enqueue outbound partner webhook deliveries."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.partner.integration import partner_webhook_config
from app.partner.webhooks.models import PartnerWebhookDelivery


def build_webhook_envelope(
    *,
    event_type: str,
    idempotency_key: str,
    data: dict,
) -> dict:
    """Standard wrapper POS receivers expect on every outbound webhook."""
    return {
        "event": event_type,
        "idempotency_key": idempotency_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


async def enqueue_partner_webhook(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    event_type: str,
    data: dict,
    idempotency_key: str,
) -> PartnerWebhookDelivery | None:
    """Write a delivery row in the caller's transaction.

    Returns None when partner webhooks are not configured (no URL or disabled).
    On duplicate ``idempotency_key``, returns None (idempotent — already queued).
    Caller must commit, then call ``schedule_partner_webhook_delivery``.
    """
    target_url, _secret = partner_webhook_config(restaurant)
    if not target_url:
        return None

    payload = build_webhook_envelope(
        event_type=event_type,
        idempotency_key=idempotency_key,
        data=data,
    )
    row = PartnerWebhookDelivery(
        restaurant_id=restaurant.id,
        event_type=event_type,
        payload=payload,
        target_url=target_url,
        idempotency_key=idempotency_key,
        status="pending",
    )
    dup = await session.scalar(
        select(PartnerWebhookDelivery.id).where(
            PartnerWebhookDelivery.idempotency_key == idempotency_key
        )
    )
    if dup is not None:
        return None

    session.add(row)
    await session.flush()
    return row


async def schedule_partner_webhook_delivery(delivery_id: int) -> None:
    """Hand off one delivery row to Celery (or deliver in-process when no worker)."""
    from app.config import get_settings
    from app.db import async_session_factory
    from app.partner.webhooks.deliver import deliver_partner_webhook_one

    if get_settings().outbox_sync_delivery:
        await deliver_partner_webhook_one(
            delivery_id, session_factory=async_session_factory
        )
        return

    from app.partner.webhooks.worker import deliver_partner_webhook_task

    deliver_partner_webhook_task.apply_async(args=[delivery_id], queue="maintenance")