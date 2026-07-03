"""Catalog flow HTTP surface (manager-authed).

A small endpoint to push the WhatsApp catalog (multi-product message) to a phone,
so a manager can test the catalog ordering experience on demand. The customer-facing
trigger lives in the webhook (keyword), this is for manual sends / testing.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.meta_client import CatalogReadError, CatalogWriteError
from app.catalog.service import send_catalog
from app.catalog.sync_service import (
    list_catalog_products,
    push_dishes_to_meta,
    sync_catalog_from_meta,
    sync_full_bidirectional,
)
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.okf.producer import refresh_okf_for_restaurant
from app.outbox.service import deliver_pending

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


async def _refresh_grounding(session: AsyncSession, restaurant_id: int) -> None:
    """Rebuild OKF menu/policy docs after a Meta-catalog sync writes/updates dishes,
    so the bot grounds on the live menu. Best-effort: never fail the sync."""
    try:
        await refresh_okf_for_restaurant(session, restaurant_id=restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()


class SendCatalogIn(BaseModel):
    phone: str


class CatalogProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    retailer_id: str
    name: str
    price_aed: float | None = None
    currency: str | None = None
    availability: str | None = None
    image_url: str | None = None
    category: str | None = None
    is_active: bool = True
    synced_at: datetime | None = None


class SyncResultOut(BaseModel):
    added: int
    updated: int
    deactivated: int
    total_active: int
    linked: int = 0
    created: int = 0
    pushed: int = 0
    push_updated: int = 0
    push_errors: list[str] = []
    products: list[CatalogProductOut]


@router.post("/send")
async def send_catalog_to_phone(
    body: SendCatalogIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Send the catalog (tappable product cards) to a phone. For testing the flow."""
    phone = body.phone.strip()
    if not phone:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "phone required")
    sent = await send_catalog(session, restaurant_id=restaurant.id, to_phone=phone)
    if not sent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "no catalog_id configured or no linked, available products for this restaurant",
        )
    await session.commit()
    await deliver_pending(session, restaurant.id)
    return {"status": "sent", "phone": phone}


@router.get("/products", response_model=list[CatalogProductOut])
async def get_catalog_products(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """The products synced from this restaurant's Meta catalogue (for the OPS view)."""
    return await list_catalog_products(session, restaurant_id=restaurant.id)


@router.post("/sync", response_model=SyncResultOut)
async def sync_catalog(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Pull the latest products from Meta into the local catalogue mirror.

    Drives the OPS 'Sync from Meta' button. Needs APP_WA_CATALOG_TOKEN (a system-user
    token with catalog_management) and a catalog_id in Settings.
    """
    try:
        result = await sync_catalog_from_meta(session, restaurant_id=restaurant.id)
    except CatalogReadError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    await session.commit()
    # Reconcile: fold any dishes still living in old (superseded) menus into the active
    # menu, so the OPS list shows everything that's live on WhatsApp — a one-time cleanup
    # for menus split by the old replace-on-upload behaviour. Idempotent + best-effort.
    from app.menu.service import fold_history_into_active_menu

    try:
        await fold_history_into_active_menu(session, restaurant_id=restaurant.id)
    except Exception:  # noqa: BLE001 — reconcile must never fail the pull
        await session.rollback()
    await _refresh_grounding(session, restaurant.id)
    products = await list_catalog_products(session, restaurant_id=restaurant.id)
    return SyncResultOut(
        added=result.added,
        updated=result.updated,
        deactivated=result.deactivated,
        total_active=result.total_active,
        linked=result.linked,
        created=result.created,
        products=[CatalogProductOut.model_validate(p) for p in products],
    )


@router.post("/push", response_model=SyncResultOut)
async def push_catalog(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Push local dishes to Meta, then re-pull the catalogue mirror."""
    try:
        push = await push_dishes_to_meta(session, restaurant_id=restaurant.id)
        result = await sync_catalog_from_meta(session, restaurant_id=restaurant.id)
    except (CatalogReadError, CatalogWriteError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    await session.commit()
    await _refresh_grounding(session, restaurant.id)
    products = await list_catalog_products(session, restaurant_id=restaurant.id)
    return SyncResultOut(
        added=result.added,
        updated=result.updated,
        deactivated=result.deactivated,
        total_active=result.total_active,
        linked=result.linked,
        created=result.created,
        pushed=push.pushed,
        push_updated=push.push_updated,
        push_errors=push.push_errors,
        products=[CatalogProductOut.model_validate(p) for p in products],
    )


@router.post("/sync-full", response_model=SyncResultOut)
async def sync_catalog_full(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Bidirectional sync: pull Meta → link dishes → push dish-only → pull again."""
    try:
        result = await sync_full_bidirectional(session, restaurant_id=restaurant.id)
    except (CatalogReadError, CatalogWriteError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    await session.commit()
    await _refresh_grounding(session, restaurant.id)
    products = await list_catalog_products(session, restaurant_id=restaurant.id)
    return SyncResultOut(
        added=result.added,
        updated=result.updated,
        deactivated=result.deactivated,
        total_active=result.total_active,
        linked=result.linked,
        created=result.created,
        pushed=result.pushed,
        push_updated=result.push_updated,
        push_errors=result.push_errors,
        products=[CatalogProductOut.model_validate(p) for p in products],
    )
