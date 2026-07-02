"""Partner integration health snapshot for manager dashboard (Phase 5)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.partner.integration import partner_settings
from app.partner.menu_api import get_partner_menu_sync_status
from app.partner.webhooks.models import PartnerWebhookDelivery


async def get_partner_integration_health(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
) -> dict:
    """Last webhook delivery, pending count, menu sync breadcrumb."""
    cfg = partner_settings(restaurant)
    last_row = await session.scalar(
        select(PartnerWebhookDelivery)
        .where(PartnerWebhookDelivery.restaurant_id == restaurant.id)
        .order_by(PartnerWebhookDelivery.id.desc())
        .limit(1)
    )
    pending = await session.scalar(
        select(func.count())
        .select_from(PartnerWebhookDelivery)
        .where(
            PartnerWebhookDelivery.restaurant_id == restaurant.id,
            PartnerWebhookDelivery.status == "pending",
        )
    )
    menu = await get_partner_menu_sync_status(session, restaurant=restaurant)

    last_webhook = None
    if last_row is not None:
        last_webhook = {
            "delivery_id": last_row.id,
            "event_type": last_row.event_type,
            "status": last_row.status,
            "attempts": last_row.attempts,
            "last_error": last_row.last_error,
            "delivered_at": (
                last_row.delivered_at.isoformat() if last_row.delivered_at else None
            ),
            "created_at": (
                last_row.created_at.isoformat() if last_row.created_at else None
            ),
        }

    return {
        "partner_enabled": cfg["partner_enabled"],
        "webhook_url_set": bool(cfg["partner_webhook_url"]),
        "webhook_secret_set": bool(cfg["partner_webhook_secret"]),
        "pos_store_id": cfg["pos_store_id"],
        "pos_order_push_mode": cfg["pos_order_push_mode"],
        "pending_webhook_count": int(pending or 0),
        "last_webhook": last_webhook,
        "menu_sync": menu,
    }