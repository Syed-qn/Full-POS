"""Partner integration API.

Two surfaces:
  * ``/api/v1/api-keys`` — manager-authed (JWT) key management (create/list/revoke).
  * ``/api/v1/partner``  — partner-authed (X-API-Key) read-only data pulls.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.ordering.models import Customer
from app.partner.deps import current_restaurant_via_api_key
from app.partner.keys import generate_api_key
from app.partner.models import PartnerApiKey
from app.partner.schemas import (
    ApiKeyCreatedOut,
    ApiKeyCreateIn,
    ApiKeyOut,
    PartnerCustomerListOut,
    PartnerCustomerOut,
)

# ── Key management (manager JWT) ─────────────────────────────────────────────
keys_router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])


@keys_router.post("", response_model=ApiKeyCreatedOut, status_code=201)
async def create_api_key(
    body: ApiKeyCreateIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreatedOut:
    """Mint a key for this restaurant. The full key is returned ONCE here and is
    never retrievable again — only its hash is stored."""
    full_key, prefix, key_hash = generate_api_key()
    row = PartnerApiKey(
        restaurant_id=restaurant.id,
        label=body.label.strip(),
        key_prefix=prefix,
        key_hash=key_hash,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ApiKeyCreatedOut(
        id=row.id,
        label=row.label,
        key_prefix=row.key_prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        api_key=full_key,
    )


@keys_router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyOut]:
    """List this restaurant's keys (active + revoked), newest first. Never the
    secret — only the display prefix."""
    rows = (
        await session.scalars(
            select(PartnerApiKey)
            .where(PartnerApiKey.restaurant_id == restaurant.id)
            .order_by(PartnerApiKey.id.desc())
        )
    ).all()
    return [
        ApiKeyOut(
            id=r.id,
            label=r.label,
            key_prefix=r.key_prefix,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            revoked_at=r.revoked_at,
        )
        for r in rows
    ]


@keys_router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke a key (soft delete). Idempotent — revoking an already-revoked key
    is a no-op."""
    row = await session.get(PartnerApiKey, key_id)
    if row is None or row.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Partner data pulls (X-API-Key) ───────────────────────────────────────────
partner_router = APIRouter(prefix="/api/v1/partner", tags=["partner"])

_MAX_PAGE = 500


@partner_router.get("/customers", response_model=PartnerCustomerListOut)
async def partner_list_customers(
    updated_since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    restaurant: Restaurant = Depends(current_restaurant_via_api_key),
    session: AsyncSession = Depends(get_session),
) -> PartnerCustomerListOut:
    """Read-only customer pull for a partner POS, scoped to the key's restaurant.

    Supports incremental sync: pass ``updated_since`` (ISO 8601) to fetch only
    customers changed at/after that time, ordered oldest-change first. The
    response echoes ``next_updated_since`` (the newest ``updated_at`` in the
    page) so the POS can resume from there.
    """
    page = max(1, min(limit, _MAX_PAGE))
    stmt = select(Customer).where(Customer.restaurant_id == restaurant.id)
    if updated_since is not None:
        stmt = stmt.where(Customer.updated_at >= updated_since)
    rows = (
        await session.scalars(
            stmt.order_by(Customer.updated_at.asc(), Customer.id.asc())
            .limit(page)
            .offset(max(0, offset))
        )
    ).all()
    items = [
        PartnerCustomerOut(
            id=c.id,
            name=c.name,
            phone=c.phone,
            total_orders=c.total_orders,
            total_spend=c.total_spend,
            first_order_at=c.first_order_at,
            last_order_at=c.last_order_at,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in rows
    ]
    return PartnerCustomerListOut(
        items=items,
        limit=page,
        offset=max(0, offset),
        next_updated_since=items[-1].updated_at if items else None,
    )
