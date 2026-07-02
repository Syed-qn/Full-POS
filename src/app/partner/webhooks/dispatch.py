"""Flush pending partner webhook deliveries after commit."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.partner.webhooks.enqueue import schedule_partner_webhook_delivery
from app.partner.webhooks.models import PartnerWebhookDelivery


async def flush_pending_partner_webhooks(
    session: AsyncSession,
    *,
    restaurant_id: int,
) -> int:
    """Schedule delivery for fresh pending partner webhooks (attempts=0).

    Call after ``session.commit()`` so rows are visible to the worker.
    Returns count scheduled.
    """
    ids = (
        await session.scalars(
            select(PartnerWebhookDelivery.id).where(
                PartnerWebhookDelivery.restaurant_id == restaurant_id,
                PartnerWebhookDelivery.status == "pending",
                PartnerWebhookDelivery.attempts == 0,
            )
        )
    ).all()
    for delivery_id in ids:
        await schedule_partner_webhook_delivery(delivery_id)
    return len(ids)