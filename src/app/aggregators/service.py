"""Aggregator ingest, channel config, menu/stock sync, recon & commission reports."""

from __future__ import annotations

import re
import secrets
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.aggregators.channels import (
    AGGREGATOR_CHANNELS,
    CHANNEL_KEYS,
    channel_is_accepting,
    commission_pct_for,
    get_channels_config,
    order_channel_key,
    set_channels_config,
)
from app.aggregators.factory import get_aggregator_port, supported_providers
from app.aggregators.models import ChannelSettlement, ChannelSyncLog
from app.aggregators.port import AggregatorPort, MenuPushItem, SyncResult
from app.audit.service import record_audit
from app.identity.models import Restaurant
from app.menu.models import Dish, Menu
from app.ordering.models import Order, OrderItem
from app.ordering.order_types import (
    ORDER_TYPE_AGGREGATOR,
    ORDER_TYPE_QR,
    ORDER_TYPE_TABLESIDE,
)
from app.ordering.service import get_or_create_customer


class ChannelPausedError(Exception):
    """Raised when inbound orders are rejected because the channel is paused."""


class ChannelDisabledError(Exception):
    """Raised when channel is not enabled for the restaurant."""


async def _get_or_create_active_menu(session: AsyncSession, *, restaurant_id: int) -> Menu:
    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
    if menu is not None:
        return menu
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    session.add(menu)
    await session.flush()
    return menu


async def _get_or_create_dish(
    session: AsyncSession,
    *,
    restaurant_id: int,
    menu_id: int,
    name: str,
    price_aed: Decimal,
) -> Dish:
    normalized = name.strip().lower()
    dish = await session.scalar(
        select(Dish).where(
            Dish.restaurant_id == restaurant_id, Dish.name_normalized == normalized
        )
    )
    if dish is not None:
        return dish
    max_number = await session.scalar(
        select(Dish.dish_number)
        .where(Dish.restaurant_id == restaurant_id)
        .order_by(Dish.dish_number.desc())
        .limit(1)
    )
    dish = Dish(
        menu_id=menu_id,
        restaurant_id=restaurant_id,
        dish_number=(max_number or 0) + 1,
        name=name,
        price_aed=price_aed,
        category="Aggregator Import",
        is_available=True,
        name_normalized=normalized,
    )
    session.add(dish)
    await session.flush()
    return dish


async def find_existing_aggregator_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    provider: str,
    provider_order_ref: str,
) -> Order | None:
    return await session.scalar(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.aggregator_source == provider,
            Order.aggregator_order_ref == provider_order_ref,
        )
    )


async def ingest_inbound_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    provider: str,
    payload: dict,
    gateway: AggregatorPort,
    restaurant: Restaurant | None = None,
) -> Order:
    """Parse marketplace payload → Order. Idempotent on provider+ref."""
    key = (provider or "").strip().lower()
    rest = restaurant
    if rest is None:
        rest = await session.get(Restaurant, restaurant_id)
    settings = rest.settings if rest is not None else None

    if not channel_is_accepting(settings, key):
        raise ChannelPausedError(f"channel {key} is not accepting orders")

    parsed = gateway.parse_inbound(payload)

    existing = await find_existing_aggregator_order(
        session,
        restaurant_id=restaurant_id,
        provider=key,
        provider_order_ref=parsed.provider_order_ref,
    )
    if existing is not None:
        return existing

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=parsed.customer_phone
    )
    if parsed.customer_name and not (customer.name or "").strip():
        customer.name = parsed.customer_name
    menu = await _get_or_create_active_menu(session, restaurant_id=restaurant_id)

    delivery_fee = parsed.delivery_fee_aed or Decimal("0.00")
    subtotal = parsed.total_aed - delivery_fee
    if subtotal < 0:
        subtotal = parsed.total_aed

    order = Order(
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        order_number=f"{key.upper()}-{parsed.provider_order_ref}"[:32],
        status="confirmed",
        subtotal=subtotal,
        delivery_fee_aed=delivery_fee,
        total=parsed.total_aed,
        aggregator_source=key,
        aggregator_order_ref=parsed.provider_order_ref,
        source_channel=key,
        order_type=ORDER_TYPE_AGGREGATOR,
        additional_details=parsed.notes,
    )
    session.add(order)
    await session.flush()

    for item in parsed.items:
        dish = await _get_or_create_dish(
            session,
            restaurant_id=restaurant_id,
            menu_id=menu.id,
            name=item.dish_name,
            price_aed=item.price_aed,
        )
        session.add(
            OrderItem(
                order_id=order.id,
                dish_id=dish.id,
                dish_number=dish.dish_number,
                dish_name=item.dish_name,
                price_aed=item.price_aed,
                qty=item.qty,
            )
        )
    await session.flush()

    try:
        await gateway.accept_order(provider_order_ref=parsed.provider_order_ref)
    except Exception:
        pass  # mock always succeeds; live adapters may soft-fail

    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor=f"aggregator:{key}",
        entity="order",
        entity_id=str(order.id),
        action="aggregator_ingest",
        after={
            "provider": key,
            "ref": parsed.provider_order_ref,
            "total": str(parsed.total_aed),
        },
    )
    return order


def _money(d: Decimal) -> Decimal:
    return Decimal(str(d)).quantize(Decimal("0.01"))


async def reconciliation(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date,
    end_date: date,
    restaurant_settings: dict | None = None,
) -> dict[str, dict]:
    """Per-provider order counts, revenue, estimated commission & net."""
    day_start = datetime.combine(start_date, time.min)
    day_end = datetime.combine(end_date, time.max)
    orders = (
        await session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant_id,
                Order.aggregator_source.is_not(None),
                Order.created_at >= day_start,
                Order.created_at <= day_end,
            )
        )
    ).all()

    result: dict[str, dict] = defaultdict(
        lambda: {
            "order_count": 0,
            "revenue_aed": Decimal("0.00"),
            "commission_pct": 0.0,
            "commission_aed": Decimal("0.00"),
            "net_aed": Decimal("0.00"),
        }
    )
    for order in orders:
        provider = (order.aggregator_source or "").lower()
        entry = result[provider]
        pct = commission_pct_for(restaurant_settings, provider)
        rev = _money(order.total or Decimal("0"))
        commission = _money(rev * Decimal(str(pct)) / Decimal("100"))
        entry["order_count"] += 1
        entry["revenue_aed"] = _money(entry["revenue_aed"] + rev)
        entry["commission_pct"] = pct
        entry["commission_aed"] = _money(entry["commission_aed"] + commission)
        entry["net_aed"] = _money(entry["net_aed"] + (rev - commission))
    return dict(result)


async def channel_commission_report(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date,
    end_date: date,
    restaurant_settings: dict | None = None,
) -> list[dict[str, Any]]:
    """All channels (not only aggregators) with commission estimates."""
    day_start = datetime.combine(start_date, time.min)
    day_end = datetime.combine(end_date, time.max)
    orders = (
        await session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant_id,
                Order.created_at >= day_start,
                Order.created_at <= day_end,
                Order.status.notin_(["cancelled", "draft"]),
            )
        )
    ).all()

    buckets: dict[str, dict] = defaultdict(
        lambda: {
            "channel": "",
            "order_count": 0,
            "gross_revenue_aed": Decimal("0.00"),
            "commission_pct": 0.0,
            "commission_aed": Decimal("0.00"),
            "net_revenue_aed": Decimal("0.00"),
        }
    )
    for order in orders:
        ch = (order.source_channel or order_channel_key(order)).lower()
        b = buckets[ch]
        b["channel"] = ch
        pct = commission_pct_for(restaurant_settings, ch)
        rev = _money(order.total or Decimal("0"))
        commission = _money(rev * Decimal(str(pct)) / Decimal("100"))
        b["order_count"] += 1
        b["gross_revenue_aed"] = _money(b["gross_revenue_aed"] + rev)
        b["commission_pct"] = pct
        b["commission_aed"] = _money(b["commission_aed"] + commission)
        b["net_revenue_aed"] = _money(b["net_revenue_aed"] + (rev - commission))
    return sorted(buckets.values(), key=lambda r: r["channel"])


async def channel_profit_report(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date,
    end_date: date,
    restaurant_settings: dict | None = None,
    food_cost_pct: float = 30.0,
) -> list[dict[str, Any]]:
    """Gross − commission − estimated food cost ≈ channel contribution margin."""
    rows = await channel_commission_report(
        session,
        restaurant_id=restaurant_id,
        start_date=start_date,
        end_date=end_date,
        restaurant_settings=restaurant_settings,
    )
    out = []
    for r in rows:
        gross = r["gross_revenue_aed"]
        food = _money(gross * Decimal(str(food_cost_pct)) / Decimal("100"))
        profit = _money(r["net_revenue_aed"] - food)
        out.append(
            {
                **r,
                "food_cost_pct": food_cost_pct,
                "estimated_food_cost_aed": food,
                "estimated_profit_aed": profit,
            }
        )
    return out


async def _log_sync(
    session: AsyncSession,
    *,
    restaurant_id: int,
    provider: str,
    result: SyncResult,
) -> ChannelSyncLog:
    row = ChannelSyncLog(
        restaurant_id=restaurant_id,
        provider=provider,
        action=result.action,
        success=result.success,
        detail=result.detail,
        items_touched=result.items_touched,
    )
    session.add(row)
    await session.flush()
    return row


async def _active_dishes(session: AsyncSession, restaurant_id: int) -> list[Dish]:
    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
    if menu is None:
        return []
    return list(
        (
            await session.scalars(
                select(Dish).where(
                    Dish.restaurant_id == restaurant_id, Dish.menu_id == menu.id
                )
            )
        ).all()
    )


def _dish_to_push_item(d: Dish) -> MenuPushItem:
    channels = list(d.channels_allowed or []) if d.channels_allowed else []
    available = bool(d.is_available)
    if d.stock_remaining is not None and d.stock_remaining <= 0:
        available = False
    return MenuPushItem(
        dish_id=d.id,
        dish_number=d.dish_number or 0,
        name=d.name,
        price_aed=d.price_aed or Decimal("0.00"),
        is_available=available,
        channels_allowed=channels,
    )


async def sync_menu_to_providers(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    providers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Push full active menu (names + prices + availability) to marketplace(s)."""
    dishes = await _active_dishes(session, restaurant.id)
    items = [_dish_to_push_item(d) for d in dishes]
    targets = providers or [
        p
        for p in supported_providers()
        if channel_is_accepting(restaurant.settings, p)
        or get_channels_config(restaurant.settings).get(p, {}).get("enabled")
    ]
    if not targets:
        targets = list(supported_providers())

    results = []
    for provider in targets:
        key = provider.strip().lower()
        if key not in AGGREGATOR_CHANNELS:
            continue
        gw = get_aggregator_port(key, restaurant_settings=restaurant.settings)
        res = await gw.push_menu(items)
        await _log_sync(session, restaurant_id=restaurant.id, provider=key, result=res)
        results.append(
            {
                "provider": key,
                "success": res.success,
                "action": res.action,
                "detail": res.detail,
                "items_touched": res.items_touched,
            }
        )
    await record_audit(
        session,
        restaurant_id=restaurant.id,
        actor="manager",
        entity="channel_sync",
        entity_id=str(restaurant.id),
        action="menu_sync",
        after={"providers": [r["provider"] for r in results], "items": len(items)},
    )
    return results


async def sync_stock_to_providers(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    providers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Push per-item availability (86 / stock) to marketplace(s)."""
    dishes = await _active_dishes(session, restaurant.id)
    targets = providers or list(supported_providers())
    results = []
    for provider in targets:
        key = provider.strip().lower()
        if key not in AGGREGATOR_CHANNELS:
            continue
        gw = get_aggregator_port(key, restaurant_settings=restaurant.settings)
        touched = 0
        for d in dishes:
            sku = str(d.dish_number or d.id)
            available = bool(d.is_available)
            if d.stock_remaining is not None and d.stock_remaining <= 0:
                available = False
            res = await gw.set_item_availability(external_sku=sku, available=available)
            touched += res.items_touched
        summary = SyncResult(
            success=True,
            provider=key,
            action="sync_stock",
            detail=f"updated {touched} skus",
            items_touched=touched,
        )
        await _log_sync(
            session, restaurant_id=restaurant.id, provider=key, result=summary
        )
        results.append(
            {
                "provider": key,
                "success": True,
                "action": "sync_stock",
                "detail": summary.detail,
                "items_touched": touched,
            }
        )
    await record_audit(
        session,
        restaurant_id=restaurant.id,
        actor="manager",
        entity="channel_sync",
        entity_id=str(restaurant.id),
        action="stock_sync",
        after={"providers": [r["provider"] for r in results]},
    )
    return results


async def set_channel_accepting(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    channel: str,
    accepting: bool,
) -> dict[str, dict]:
    """Pause/resume a channel; push store status to aggregator adapters when relevant."""
    key = channel.strip().lower()
    if key not in CHANNEL_KEYS:
        raise ValueError(f"unknown channel: {channel}")

    cfg = set_channels_config(restaurant, {key: {"accepting": accepting, "enabled": True}})
    flag_modified(restaurant, "settings")

    if key in AGGREGATOR_CHANNELS:
        gw = get_aggregator_port(key, restaurant_settings=restaurant.settings)
        res = await gw.set_store_status(accepting=accepting)
        await _log_sync(session, restaurant_id=restaurant.id, provider=key, result=res)

    await record_audit(
        session,
        restaurant_id=restaurant.id,
        actor="manager",
        entity="channel",
        entity_id=key,
        action="channel_resume" if accepting else "channel_pause",
        after={"accepting": accepting},
    )
    return cfg


async def update_channels(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    updates: dict[str, Any],
) -> dict[str, dict]:
    cfg = set_channels_config(restaurant, updates)
    flag_modified(restaurant, "settings")
    await record_audit(
        session,
        restaurant_id=restaurant.id,
        actor="manager",
        entity="channel",
        entity_id=str(restaurant.id),
        action="channels_updated",
        after={"keys": list(updates.keys())},
    )
    return cfg


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "store").lower()).strip("-")
    return (s or "store")[:48]


async def ensure_public_slug(
    session: AsyncSession, *, restaurant: Restaurant, preferred: str | None = None
) -> str:
    """Allocate a unique public_slug for website/QR/kiosk/social order links."""
    if restaurant.public_slug and not preferred:
        return restaurant.public_slug

    base = _slugify(preferred or restaurant.public_slug or restaurant.name)
    candidate = base
    for _ in range(12):
        clash = await session.scalar(
            select(Restaurant.id).where(
                Restaurant.public_slug == candidate,
                Restaurant.id != restaurant.id,
            )
        )
        if clash is None:
            restaurant.public_slug = candidate
            # Mirror into website channel order_url placeholder
            set_channels_config(
                restaurant,
                {
                    "website": {"slug": candidate, "enabled": True},
                    "mobile_app": {"slug": candidate, "enabled": True},
                    "instagram": {"slug": candidate, "enabled": True},
                    "google_business": {"slug": candidate, "enabled": True},
                    "kiosk": {"slug": candidate, "enabled": True},
                    "qr": {"enabled": True},
                },
            )
            flag_modified(restaurant, "settings")
            await session.flush()
            return candidate
        candidate = f"{base}-{secrets.token_hex(2)}"
    raise RuntimeError("could not allocate public_slug")


async def get_restaurant_by_slug(
    session: AsyncSession, *, slug: str
) -> Restaurant | None:
    return await session.scalar(
        select(Restaurant).where(Restaurant.public_slug == slug)
    )


async def public_menu_for_restaurant(
    session: AsyncSession,
    *,
    restaurant_id: int,
    channel: str = "website",
) -> list[dict[str, Any]]:
    dishes = await _active_dishes(session, restaurant_id)
    out = []
    for d in dishes:
        if not d.is_available:
            continue
        if d.stock_remaining is not None and d.stock_remaining <= 0:
            continue
        allowed = d.channels_allowed or []
        # empty channels_allowed = all channels
        if allowed:
            tags = {str(c).lower() for c in allowed}
            ch = channel.lower()
            aliases = {ch}
            if ch in ("website", "mobile_app", "instagram", "google_business"):
                aliases.update({"online", "website", "delivery"})
            if ch == "kiosk":
                aliases.update({"tableside", "dine_in", "kiosk"})
            if ch == "qr":
                aliases.update({"qr", "dine_in", "tableside"})
            if ch in AGGREGATOR_CHANNELS:
                aliases.add("aggregator")
            if not tags.intersection(aliases) and "all" not in tags:
                continue
        out.append(
            {
                "id": d.id,
                "dish_number": d.dish_number,
                "name": d.name,
                "description": (d.description or "")[:240] or None,
                "price_aed": str(d.price_aed or Decimal("0.00")),
                "category": d.category,
                "image_url": d.image_url,
                "is_available": True,
            }
        )
    return out


async def place_public_channel_order(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    channel: str,
    customer_phone: str,
    customer_name: str | None,
    items: list[dict],
    table_id: int | None = None,
    notes: str | None = None,
) -> Order:
    """Website / mobile / kiosk / social-link order entry (COD default)."""
    from app.ordering.pos_orders import create_pos_order

    ch = (channel or "website").strip().lower()
    if ch not in CHANNEL_KEYS:
        raise ValueError(f"unknown channel: {channel}")
    if not channel_is_accepting(restaurant.settings, ch):
        raise ChannelPausedError(f"channel {ch} is not accepting orders")

    from app.ordering.order_types import ORDER_TYPE_TAKEAWAY

    # Map channel → order_type. Public website/app/social default to takeaway
    # (no address required). Delivery/online address flows stay on POS/manual.
    if ch == "qr":
        order_type = ORDER_TYPE_QR
        if table_id is None:
            raise ValueError("qr orders require table_id")
    elif ch == "kiosk":
        order_type = ORDER_TYPE_TABLESIDE if table_id is not None else ORDER_TYPE_TAKEAWAY
    elif ch in ("website", "mobile_app", "instagram", "google_business"):
        order_type = ORDER_TYPE_TAKEAWAY
    elif ch == "call_center":
        order_type = ORDER_TYPE_TAKEAWAY
    else:
        order_type = ORDER_TYPE_TAKEAWAY

    order = await create_pos_order(
        session,
        restaurant_id=restaurant.id,
        order_type=order_type,
        customer_phone=customer_phone,
        customer_name=customer_name,
        items=items,
        table_id=table_id,
        delivery_fee_aed=Decimal("0.00"),
        auto_confirm=True,
        customer_allergy_notes=notes,
    )
    order.source_channel = ch
    if ch in AGGREGATOR_CHANNELS:
        order.aggregator_source = ch
        order.order_type = ORDER_TYPE_AGGREGATOR
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant.id,
        actor=f"public:{ch}",
        entity="order",
        entity_id=str(order.id),
        action="public_channel_order",
        after={"channel": ch, "order_number": order.order_number},
    )
    return order


async def list_channel_inbox(
    session: AsyncSession,
    *,
    restaurant_id: int,
    channel: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    stmt = (
        select(Order)
        .where(Order.restaurant_id == restaurant_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if channel:
        ch = channel.strip().lower()
        stmt = stmt.where(
            (Order.source_channel == ch)
            | (Order.aggregator_source == ch)
        )
    return list((await session.scalars(stmt)).all())


async def record_settlement(
    session: AsyncSession,
    *,
    restaurant_id: int,
    provider: str,
    period_start: date,
    period_end: date,
    order_count: int,
    gross_revenue_aed: Decimal,
    commission_aed: Decimal,
    net_aed: Decimal | None = None,
    external_ref: str | None = None,
    notes: str | None = None,
) -> ChannelSettlement:
    key = provider.strip().lower()
    net = net_aed if net_aed is not None else _money(gross_revenue_aed - commission_aed)
    existing = await session.scalar(
        select(ChannelSettlement).where(
            ChannelSettlement.restaurant_id == restaurant_id,
            ChannelSettlement.provider == key,
            ChannelSettlement.period_start == period_start,
            ChannelSettlement.period_end == period_end,
        )
    )
    if existing:
        existing.order_count = order_count
        existing.gross_revenue_aed = _money(gross_revenue_aed)
        existing.commission_aed = _money(commission_aed)
        existing.net_aed = _money(net)
        existing.external_ref = external_ref
        existing.notes = notes
        existing.status = "recorded"
        await session.flush()
        return existing

    row = ChannelSettlement(
        restaurant_id=restaurant_id,
        provider=key,
        period_start=period_start,
        period_end=period_end,
        order_count=order_count,
        gross_revenue_aed=_money(gross_revenue_aed),
        commission_aed=_money(commission_aed),
        net_aed=_money(net),
        external_ref=external_ref,
        notes=notes,
        status="recorded",
    )
    session.add(row)
    await session.flush()
    return row


async def list_settlements(
    session: AsyncSession,
    *,
    restaurant_id: int,
    provider: str | None = None,
) -> list[ChannelSettlement]:
    stmt = (
        select(ChannelSettlement)
        .where(ChannelSettlement.restaurant_id == restaurant_id)
        .order_by(ChannelSettlement.period_end.desc())
    )
    if provider:
        stmt = stmt.where(ChannelSettlement.provider == provider.strip().lower())
    return list((await session.scalars(stmt)).all())


async def recon_vs_settlements(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Compare internal aggregator totals to recorded settlements."""
    internal = await reconciliation(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
        restaurant_settings=restaurant.settings,
    )
    settlements = await list_settlements(session, restaurant_id=restaurant.id)
    by_provider: dict[str, list[ChannelSettlement]] = defaultdict(list)
    for s in settlements:
        if s.period_start <= end_date and s.period_end >= start_date:
            by_provider[s.provider].append(s)

    providers = set(internal.keys()) | set(by_provider.keys()) | set(supported_providers())
    rows = []
    for p in sorted(providers):
        inn = internal.get(
            p,
            {
                "order_count": 0,
                "revenue_aed": Decimal("0.00"),
                "commission_aed": Decimal("0.00"),
                "net_aed": Decimal("0.00"),
            },
        )
        sett_gross = sum((s.gross_revenue_aed for s in by_provider.get(p, [])), Decimal("0"))
        sett_comm = sum((s.commission_aed for s in by_provider.get(p, [])), Decimal("0"))
        sett_orders = sum(s.order_count for s in by_provider.get(p, []))
        rows.append(
            {
                "provider": p,
                "internal_order_count": inn["order_count"],
                "internal_revenue_aed": str(_money(inn["revenue_aed"])),
                "internal_commission_aed": str(_money(inn.get("commission_aed", Decimal("0")))),
                "settlement_order_count": sett_orders,
                "settlement_gross_aed": str(_money(sett_gross)),
                "settlement_commission_aed": str(_money(sett_comm)),
                "revenue_delta_aed": str(_money(inn["revenue_aed"] - sett_gross)),
                "matched": sett_orders == 0
                or (
                    sett_orders == inn["order_count"]
                    and abs(inn["revenue_aed"] - sett_gross) < Decimal("0.02")
                ),
            }
        )
    return rows


def public_order_links(restaurant: Restaurant, *, base_url: str = "") -> dict[str, str]:
    """Build shareable order URLs for website / social / kiosk."""
    slug = restaurant.public_slug or ""
    root = (base_url or "").rstrip("/")
    prefix = f"{root}/order/{slug}" if slug else ""
    return {
        "website": prefix,
        "mobile_app": f"{prefix}?channel=mobile_app" if prefix else "",
        "instagram": f"{prefix}?channel=instagram" if prefix else "",
        "google_business": f"{prefix}?channel=google_business" if prefix else "",
        "kiosk": f"{prefix}?channel=kiosk" if prefix else "",
        "slug": slug,
    }
