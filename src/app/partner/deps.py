"""Partner API-key authentication dependency.

Resolves an ``X-API-Key`` header to the owning restaurant, enforces per-key rate
limits, and records an audit row (``actor=pos``) for every authenticated call.
"""
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.db import get_session
from app.identity.models import Restaurant
from app.partner.keys import hash_api_key
from app.partner.models import PartnerApiKey


async def _enforce_partner_rate_limit(
    request: Request, x_api_key: str | None
) -> None:
    from app.config import get_settings
    from app.ratelimit.deps import enforce_rate_limit

    if x_api_key:
        bucket = f"partner:{hash_api_key(x_api_key)}"
    else:
        ip = request.client.host if request.client else "unknown"
        bucket = f"partner:ip:{ip}"
    await enforce_rate_limit(bucket, get_settings().partner_rate_limit)


async def partner_authenticated_restaurant(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> Restaurant:
    """Authenticate partner API key, rate-limit, audit, return tenant restaurant."""
    await _enforce_partner_rate_limit(request, x_api_key)
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

    key.last_used_at = datetime.now(timezone.utc)
    await record_audit(
        session,
        actor="pos",
        restaurant_id=restaurant.id,
        entity="partner_api",
        entity_id=request.url.path,
        action=request.method.lower(),
        after={
            "path": request.url.path,
            "query": request.url.query or None,
            "key_prefix": key.key_prefix,
        },
    )
    await session.commit()
    return restaurant


# Back-compat alias used in tests and older imports.
current_restaurant_via_api_key = partner_authenticated_restaurant