"""Resolve which restaurant owns an inbound WhatsApp webhook."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.identity.phones import phone_lookup_values


async def resolve_restaurant_for_webhook(
    session: AsyncSession,
    *,
    restaurant_phone: str,
    phone_number_id: str = "",
) -> Restaurant | None:
    """Match inbound webhook metadata to a tenant row.

    Primary key is ``Restaurant.phone`` (normalized display number). Falls back to
    ``settings.wa_phone_number_id`` when the display number is missing or mismatched
    — multi-tenant routing must not drop messages because Meta omits ``+`` or the
    stored phone drifted from the connected number.
    """
    for candidate in phone_lookup_values(restaurant_phone):
        row = await session.scalar(select(Restaurant).where(Restaurant.phone == candidate))
        if row is not None:
            return row

    pid = (phone_number_id or "").strip()
    if not pid:
        return None

    rows = (await session.scalars(select(Restaurant))).all()
    for row in rows:
        settings = row.settings or {}
        if (settings.get("wa_phone_number_id") or "").strip() == pid:
            return row
    return None