"""Unauthenticated public storefront + QR menu + tenant marketplace webhooks.

Marketplace webhooks are multi-tenant: ``/store/{slug}/aggregators/{provider}/webhook``
resolves the restaurant by public slug, then verifies the webhook using **that**
restaurant's ``settings.channels.<provider>`` secrets (HMAC / shared secret).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.aggregators.channels import AGGREGATOR_CHANNELS
from app.aggregators.factory import get_aggregator_port
from app.aggregators.schemas import PublicMenuItemOut, PublicStoreOrderIn
from app.aggregators.service import (
    ChannelPausedError,
    get_restaurant_by_slug,
    ingest_inbound_order,
    place_public_channel_order,
    public_menu_for_restaurant,
)
from app.db import get_session
from app.ordering.qr_orders import create_qr_order, get_table_by_qr_token
from app.ordering.schemas import QrOrderIn

router = APIRouter(prefix="/api/v1/public", tags=["public-store"])


@router.get("/store/{slug}", response_model=dict)
async def public_store_info(
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    restaurant = await get_restaurant_by_slug(session, slug=slug)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="store not found")
    return {
        "slug": restaurant.public_slug,
        "name": restaurant.name,
        "channels": {
            "website": True,
            "mobile_app": True,
            "kiosk": True,
            "instagram": True,
            "google_business": True,
        },
    }


@router.get("/store/{slug}/menu", response_model=list[PublicMenuItemOut])
async def public_store_menu(
    slug: str,
    channel: str = Query(default="website"),
    session: AsyncSession = Depends(get_session),
):
    restaurant = await get_restaurant_by_slug(session, slug=slug)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="store not found")
    items = await public_menu_for_restaurant(
        session, restaurant_id=restaurant.id, channel=channel
    )
    return [PublicMenuItemOut(**i) for i in items]


@router.post("/store/{slug}/orders", status_code=201)
async def public_store_order(
    slug: str,
    body: PublicStoreOrderIn,
    session: AsyncSession = Depends(get_session),
):
    restaurant = await get_restaurant_by_slug(session, slug=slug)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="store not found")
    try:
        order = await place_public_channel_order(
            session,
            restaurant=restaurant,
            channel=body.channel or "website",
            customer_phone=body.customer_phone,
            customer_name=body.customer_name,
            items=[i.model_dump() for i in body.items],
            table_id=body.table_id,
            notes=body.notes,
        )
    except ChannelPausedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "order_type": order.order_type,
        "source_channel": order.source_channel,
        "total_aed": str(order.total),
    }


@router.get("/qr/{qr_token}/menu", response_model=list[PublicMenuItemOut])
async def public_qr_menu(
    qr_token: str,
    session: AsyncSession = Depends(get_session),
):
    table = await get_table_by_qr_token(session, qr_token=qr_token)
    if table is None:
        raise HTTPException(status_code=404, detail="invalid QR token")
    items = await public_menu_for_restaurant(
        session, restaurant_id=table.restaurant_id, channel="qr"
    )
    return [PublicMenuItemOut(**i) for i in items]


@router.get("/qr/{qr_token}/table")
async def public_qr_table_info(
    qr_token: str,
    session: AsyncSession = Depends(get_session),
):
    table = await get_table_by_qr_token(session, qr_token=qr_token)
    if table is None:
        raise HTTPException(status_code=404, detail="invalid QR token")
    from app.identity.models import Restaurant

    restaurant = await session.get(Restaurant, table.restaurant_id)
    return {
        "table_id": table.id,
        "table_label": getattr(table, "label", None) or getattr(table, "name", None),
        "restaurant_id": table.restaurant_id,
        "restaurant_name": restaurant.name if restaurant else None,
        "qr_token": qr_token,
    }


# Keep QR order under /public for discoverability; also re-exported from public_router alias.
@router.post("/qr/{qr_token}/orders", status_code=201)
async def public_qr_order_v2(
    qr_token: str,
    body: QrOrderIn,
    session: AsyncSession = Depends(get_session),
):
    from app.aggregators.channels import channel_is_accepting
    from app.identity.models import Restaurant

    table = await get_table_by_qr_token(session, qr_token=qr_token)
    if table is None:
        raise HTTPException(status_code=404, detail="invalid QR token")
    restaurant = await session.get(Restaurant, table.restaurant_id)
    if restaurant is not None and not channel_is_accepting(restaurant.settings, "qr"):
        raise HTTPException(status_code=409, detail="channel qr is not accepting orders")
    try:
        order = await create_qr_order(
            session,
            qr_token=qr_token,
            customer_phone=body.customer_phone,
            customer_name=body.customer_name,
            items=[i.model_dump() for i in body.items],
        )
        order.source_channel = "qr"
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "invalid QR" in msg.lower() else 422
        raise HTTPException(status_code=code, detail=msg) from exc
    await session.commit()
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "order_type": order.order_type,
        "source_channel": order.source_channel,
        "table_id": order.table_id,
        "total_aed": str(order.total),
    }


@router.post(
    "/store/{slug}/aggregators/{provider}/webhook",
    status_code=201,
    tags=["public-store", "aggregators"],
)
async def public_tenant_aggregator_webhook(
    slug: str,
    provider: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Inbound marketplace order for **one restaurant** (multi-tenant).

    Tenant resolution: public store ``slug`` → restaurant.
    Auth: that restaurant's ``channels.<provider>`` webhook_secret / HMAC
    (via adapter ``verify_webhook``). No JWT; partners paste this URL once.
    """
    key = (provider or "").strip().lower()
    if key not in AGGREGATOR_CHANNELS:
        raise HTTPException(status_code=400, detail=f"unsupported provider: {provider}")

    restaurant = await get_restaurant_by_slug(session, slug=slug)
    if restaurant is None:
        raise HTTPException(status_code=404, detail="store not found")

    try:
        gateway = get_aggregator_port(key, restaurant_settings=restaurant.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not gateway.verify_webhook(headers, raw):
        raise HTTPException(status_code=401, detail="invalid webhook signature")

    try:
        import json as _json

        payload = _json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"invalid JSON body: {exc}") from exc

    try:
        order = await ingest_inbound_order(
            session,
            restaurant_id=restaurant.id,
            provider=key,
            payload=payload,
            gateway=gateway,
            restaurant=restaurant,
        )
    except ChannelPausedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail=f"malformed {key} payload: {exc}"
        ) from exc

    await session.commit()
    mode = (
        ((restaurant.settings or {}).get("channels") or {})
        .get(key, {})
        .get("mode")
        or "mock"
    )
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "source_channel": order.source_channel,
        "aggregator_source": order.aggregator_source,
        "restaurant_slug": restaurant.public_slug,
        "adapter_mode": "live" if mode == "live" else "mock",
    }
