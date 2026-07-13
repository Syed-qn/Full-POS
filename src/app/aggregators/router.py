"""HTTP surface for aggregators, channel ops, recon, and public storefront links."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.aggregators.channels import (
    AGGREGATOR_CHANNELS,
    CREDENTIAL_HINTS,
    get_channels_config,
    tenant_webhook_urls,
)
from app.aggregators.factory import get_aggregator_port, supported_providers
from app.aggregators.schemas import (
    ChannelConfigOut,
    ChannelsOut,
    ChannelsUpdateIn,
    SettlementIn,
    SettlementOut,
    SlugEnsureIn,
    SyncProvidersIn,
    SyncResultOut,
)
from app.aggregators.service import (
    ChannelPausedError,
    channel_commission_report,
    channel_profit_report,
    ensure_public_slug,
    ingest_inbound_order,
    list_channel_inbox,
    list_settlements,
    public_order_links,
    recon_vs_settlements,
    reconciliation,
    record_settlement,
    set_channel_accepting,
    sync_menu_to_providers,
    sync_stock_to_providers,
    update_channels,
)
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.partner.deps import partner_authenticated_restaurant

router = APIRouter(prefix="/api/v1/aggregators", tags=["aggregators"])


def _money_str(v: Decimal | float | int | str) -> str:
    return str(Decimal(str(v)).quantize(Decimal("0.01")))


def _channels_response(restaurant: Restaurant, *, base_url: str = "") -> ChannelsOut:
    """Serialize tenant channel config — secrets masked; webhook URLs included."""
    raw = get_channels_config(restaurant.settings)
    slug = restaurant.public_slug
    channels: dict[str, ChannelConfigOut] = {}
    for k, v in raw.items():
        pub_wh, partner_wh = tenant_webhook_urls(
            base_url=base_url, public_slug=slug, provider=k
        )
        is_agg = k in AGGREGATOR_CHANNELS
        channels[k] = ChannelConfigOut(
            enabled=bool(v.get("enabled")),
            accepting=bool(v.get("accepting", True)),
            commission_pct=float(v.get("commission_pct") or 0),
            mode=str(v.get("mode") or "mock"),
            # Never echo raw secrets; only presence flags for the dashboard.
            api_key=None,
            api_key_set=bool(v.get("api_key")),
            api_secret_set=bool(v.get("api_secret")),
            access_token_set=bool(v.get("access_token")),
            store_id=v.get("store_id"),
            base_url=v.get("base_url"),
            webhook_secret_set=bool(v.get("webhook_secret")),
            webhook_url=pub_wh if is_agg else None,
            partner_webhook_url=partner_wh if is_agg else None,
            order_url=v.get("order_url"),
            slug=v.get("slug"),
            credential_hint=CREDENTIAL_HINTS.get(k) if is_agg else None,
        )
    return ChannelsOut(
        channels=channels,
        providers=supported_providers(),
        public_slug=restaurant.public_slug,
        order_links=public_order_links(restaurant, base_url=base_url),
    )


@router.get("/providers")
async def list_providers(
    restaurant: Restaurant = Depends(current_restaurant),
):
    return {"providers": supported_providers()}


@router.get("/channels", response_model=ChannelsOut)
async def get_channels(
    request: Request,
    restaurant: Restaurant = Depends(current_restaurant),
):
    base = str(request.base_url).rstrip("/")
    return _channels_response(restaurant, base_url=base)


@router.put("/channels", response_model=ChannelsOut)
async def put_channels(
    body: ChannelsUpdateIn,
    request: Request,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    updates = {
        k: {kk: vv for kk, vv in v.model_dump(exclude_none=True).items()}
        for k, v in body.channels.items()
    }
    await update_channels(session, restaurant=restaurant, updates=updates)
    await session.commit()
    await session.refresh(restaurant)
    base = str(request.base_url).rstrip("/")
    return _channels_response(restaurant, base_url=base)


@router.post("/channels/{channel}/pause", response_model=ChannelsOut)
async def pause_channel(
    channel: str,
    request: Request,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        await set_channel_accepting(
            session, restaurant=restaurant, channel=channel, accepting=False
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(restaurant)
    return _channels_response(restaurant, base_url=str(request.base_url).rstrip("/"))


@router.post("/channels/{channel}/resume", response_model=ChannelsOut)
async def resume_channel(
    channel: str,
    request: Request,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        await set_channel_accepting(
            session, restaurant=restaurant, channel=channel, accepting=True
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(restaurant)
    return _channels_response(restaurant, base_url=str(request.base_url).rstrip("/"))


@router.post("/public-slug", response_model=ChannelsOut)
async def ensure_slug(
    body: SlugEnsureIn,
    request: Request,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await ensure_public_slug(session, restaurant=restaurant, preferred=body.slug)
    await session.commit()
    await session.refresh(restaurant)
    return _channels_response(restaurant, base_url=str(request.base_url).rstrip("/"))


@router.post("/sync/menu", response_model=list[SyncResultOut])
async def sync_menu(
    body: SyncProvidersIn | None = None,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    providers = body.providers if body else None
    results = await sync_menu_to_providers(
        session, restaurant=restaurant, providers=providers
    )
    await session.commit()
    return [SyncResultOut(**r) for r in results]


@router.post("/sync/stock", response_model=list[SyncResultOut])
async def sync_stock(
    body: SyncProvidersIn | None = None,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    providers = body.providers if body else None
    results = await sync_stock_to_providers(
        session, restaurant=restaurant, providers=providers
    )
    await session.commit()
    return [SyncResultOut(**r) for r in results]


@router.post("/sync/price", response_model=list[SyncResultOut])
async def sync_price(
    body: SyncProvidersIn | None = None,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Price sync reuses full menu push (names + prices + availability)."""
    providers = body.providers if body else None
    results = await sync_menu_to_providers(
        session, restaurant=restaurant, providers=providers
    )
    await session.commit()
    return [SyncResultOut(**r) for r in results]


@router.get("/reconciliation")
async def get_reconciliation(
    start_date: date,
    end_date: date,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    result = await reconciliation(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
        restaurant_settings=restaurant.settings,
    )
    return {
        provider: {
            "order_count": v["order_count"],
            "revenue_aed": _money_str(v["revenue_aed"]),
            "commission_pct": v.get("commission_pct", 0),
            "commission_aed": _money_str(v.get("commission_aed", 0)),
            "net_aed": _money_str(v.get("net_aed", 0)),
        }
        for provider, v in result.items()
    }


@router.get("/reconciliation/detailed")
async def get_reconciliation_detailed(
    start_date: date,
    end_date: date,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await recon_vs_settlements(
        session, restaurant=restaurant, start_date=start_date, end_date=end_date
    )
    return {"rows": rows, "start_date": start_date.isoformat(), "end_date": end_date.isoformat()}


@router.get("/reports/commission")
async def get_commission_report(
    start_date: date,
    end_date: date,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await channel_commission_report(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
        restaurant_settings=restaurant.settings,
    )
    return {
        "rows": [
            {
                "channel": r["channel"],
                "order_count": r["order_count"],
                "gross_revenue_aed": _money_str(r["gross_revenue_aed"]),
                "commission_pct": r["commission_pct"],
                "commission_aed": _money_str(r["commission_aed"]),
                "net_revenue_aed": _money_str(r["net_revenue_aed"]),
            }
            for r in rows
        ]
    }


@router.get("/reports/profit")
async def get_profit_report(
    start_date: date,
    end_date: date,
    food_cost_pct: float = Query(default=30.0, ge=0, le=100),
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await channel_profit_report(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
        restaurant_settings=restaurant.settings,
        food_cost_pct=food_cost_pct,
    )
    return {
        "rows": [
            {
                "channel": r["channel"],
                "order_count": r["order_count"],
                "gross_revenue_aed": _money_str(r["gross_revenue_aed"]),
                "commission_pct": r["commission_pct"],
                "commission_aed": _money_str(r["commission_aed"]),
                "net_revenue_aed": _money_str(r["net_revenue_aed"]),
                "food_cost_pct": r["food_cost_pct"],
                "estimated_food_cost_aed": _money_str(r["estimated_food_cost_aed"]),
                "estimated_profit_aed": _money_str(r["estimated_profit_aed"]),
            }
            for r in rows
        ]
    }


@router.get("/inbox")
async def channel_inbox(
    channel: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    orders = await list_channel_inbox(
        session,
        restaurant_id=restaurant.id,
        channel=channel,
        limit=limit,
        offset=offset,
    )
    return {
        "orders": [
            {
                "id": o.id,
                "order_number": o.order_number,
                "status": o.status,
                "total_aed": _money_str(o.total or 0),
                "source_channel": o.source_channel
                or o.aggregator_source
                or o.order_type,
                "aggregator_source": o.aggregator_source,
                "aggregator_order_ref": o.aggregator_order_ref,
                "order_type": o.order_type,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ]
    }


@router.post("/settlements", response_model=SettlementOut, status_code=status.HTTP_201_CREATED)
async def create_settlement(
    body: SettlementIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    row = await record_settlement(
        session,
        restaurant_id=restaurant.id,
        provider=body.provider,
        period_start=body.period_start,
        period_end=body.period_end,
        order_count=body.order_count,
        gross_revenue_aed=body.gross_revenue_aed,
        commission_aed=body.commission_aed,
        net_aed=body.net_aed,
        external_ref=body.external_ref,
        notes=body.notes,
    )
    await session.commit()
    return SettlementOut(
        id=row.id,
        provider=row.provider,
        period_start=row.period_start,
        period_end=row.period_end,
        order_count=row.order_count,
        gross_revenue_aed=_money_str(row.gross_revenue_aed),
        commission_aed=_money_str(row.commission_aed),
        net_aed=_money_str(row.net_aed),
        status=row.status,
        external_ref=row.external_ref,
        notes=row.notes,
    )


@router.get("/settlements", response_model=list[SettlementOut])
async def get_settlements(
    provider: str | None = None,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_settlements(
        session, restaurant_id=restaurant.id, provider=provider
    )
    return [
        SettlementOut(
            id=r.id,
            provider=r.provider,
            period_start=r.period_start,
            period_end=r.period_end,
            order_count=r.order_count,
            gross_revenue_aed=_money_str(r.gross_revenue_aed),
            commission_aed=_money_str(r.commission_aed),
            net_aed=_money_str(r.net_aed),
            status=r.status,
            external_ref=r.external_ref,
            notes=r.notes,
        )
        for r in rows
    ]


@router.post("/{provider}/webhook", status_code=status.HTTP_201_CREATED)
async def aggregator_webhook(
    provider: str,
    request: Request,
    restaurant: Restaurant = Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        gateway = get_aggregator_port(provider, restaurant_settings=restaurant.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Read raw body for HMAC verification (live adapters), then parse JSON.
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
            provider=provider,
            payload=payload,
            gateway=gateway,
            restaurant=restaurant,
        )
    except ChannelPausedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail=f"malformed {provider} payload: {exc}"
        ) from exc
    await session.commit()
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "source_channel": order.source_channel,
        "aggregator_source": order.aggregator_source,
        "adapter_mode": (
            "live"
            if (
                (restaurant.settings or {})
                .get("channels", {})
                .get((provider or "").lower(), {})
                .get("mode")
                == "live"
            )
            else "mock"
        ),
    }


@router.post("/{provider}/live-health")
async def provider_live_health(
    provider: str,
    restaurant: Restaurant = Depends(current_restaurant),
):
    """Probe mock or live partner connectivity for one marketplace."""
    from app.aggregators.factory import is_live_mode

    try:
        gateway = get_aggregator_port(provider, restaurant_settings=restaurant.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    check = getattr(gateway, "health_check", None)
    if check is None:
        return {"provider": provider, "mode": "mock", "success": True, "detail": "no health API"}
    result = await check()
    return {
        "provider": provider,
        "mode": "live" if is_live_mode(restaurant.settings, provider) else "mock",
        "success": result.success,
        "detail": result.detail,
        "action": result.action,
    }


@router.post("/{provider}/reject/{order_ref}")
async def reject_marketplace_order(
    provider: str,
    order_ref: str,
    reason: str = Query(default="out_of_stock"),
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Reject a marketplace order on the partner API and cancel local order if present."""
    from app.aggregators.service import find_existing_aggregator_order
    from app.ordering.fsm import OrderStatus, transition as fsm_transition

    try:
        gateway = get_aggregator_port(provider, restaurant_settings=restaurant.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await gateway.reject_order(provider_order_ref=order_ref, reason=reason)
    local = await find_existing_aggregator_order(
        session,
        restaurant_id=restaurant.id,
        provider=provider,
        provider_order_ref=order_ref,
    )
    if local is not None and local.status not in (
        OrderStatus.CANCELLED,
        OrderStatus.DELIVERED,
    ):
        try:
            await fsm_transition(
                session, local, OrderStatus.CANCELLED, actor=f"aggregator:{provider}"
            )
        except Exception:  # noqa: BLE001
            pass
    await session.commit()
    return {
        "success": result.success,
        "detail": result.detail,
        "local_order_id": local.id if local else None,
    }
