"""Partner API-key authentication dependency.

Resolves an ``X-API-Key`` header to the owning restaurant, so partner endpoints
are tenant-scoped exactly like the manager (JWT) ones — a key only ever sees its
own restaurant's data.
"""
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.models import Restaurant
from app.partner.keys import hash_api_key
from app.partner.models import PartnerApiKey


async def current_restaurant_via_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> Restaurant:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing API key")
    key = (
        await session.scalars(
            select(PartnerApiKey).where(
                PartnerApiKey.key_hash == hash_api_key(x_api_key),
                PartnerApiKey.revoked_at.is_(None),
            )
        )
    ).first()
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or revoked API key")
    restaurant = await session.get(Restaurant, key.restaurant_id)
    if restaurant is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown restaurant")
    # Best-effort "last seen" stamp for the dashboard; never block the request on it.
    key.last_used_at = datetime.now(timezone.utc)
    await session.commit()
    return restaurant
