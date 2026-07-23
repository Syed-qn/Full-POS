"""Kitchen Display System service — tickets, stations, printer fallback, performance."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kds.models import (
    DEFAULT_STATION_PRESETS,
    STATION_TYPES,
    CategoryStationDefault,
    KitchenStation,
    PrintJob,
)
from app.kds.printer_status import get_printer_status
from app.menu.models import Dish
from app.ordering.models import Order, OrderItem

# Age thresholds (minutes) for urgency — shared with frontend kdsApi.
WARNING_AFTER_MINUTES = 8
LATE_AFTER_MINUTES = 15

# Orders that must never appear on a live kitchen board. `cancelled` covers a
# void; `on_resale` is a cancelled-after-cooking order being re-sold, whose food
# already exists and must not be cooked again.
DEAD_ORDER_STATUSES = ("cancelled", "on_resale")


async def get_or_create_main_station(
    session: AsyncSession, *, restaurant_id: int, kitchen_code: str = "main"
) -> KitchenStation:
    existing = await session.scalar(
        select(KitchenStation).where(
            KitchenStation.restaurant_id == restaurant_id,
            KitchenStation.kitchen_code == kitchen_code,
            KitchenStation.name == "Main",
        )
    )
    if existing is not None:
        return existing
    station = KitchenStation(
        restaurant_id=restaurant_id,
        name="Main",
        station_type="main",
        kitchen_code=kitchen_code,
    )
    session.add(station)
    await session.flush()
    return station


async def ensure_default_stations(
    session: AsyncSession, *, restaurant_id: int, kitchen_code: str = "main"
) -> list[KitchenStation]:
    """Create grill/fry/beverage/dessert/pizza/cloud/main presets if missing."""
    existing = (
        await session.scalars(
            select(KitchenStation).where(
                KitchenStation.restaurant_id == restaurant_id,
                KitchenStation.kitchen_code == kitchen_code,
            )
        )
    ).all()
    by_name = {s.name.lower(): s for s in existing}
    created: list[KitchenStation] = []
    for name, stype in DEFAULT_STATION_PRESETS:
        if name.lower() in by_name:
            continue
        station = KitchenStation(
            restaurant_id=restaurant_id,
            name=name,
            station_type=stype,
            kitchen_code=kitchen_code,
        )
        session.add(station)
        created.append(station)
    if created:
        await session.flush()
    all_stations = (
        await session.scalars(
            select(KitchenStation).where(
                KitchenStation.restaurant_id == restaurant_id,
                KitchenStation.kitchen_code == kitchen_code,
            )
        )
    ).all()
    return list(all_stations)


async def resolve_station(
    session: AsyncSession,
    *,
    restaurant_id: int,
    dish,
    kitchen_code: str | None = None,
) -> int:
    """dish override -> category default -> auto-created 'Main' fallback.

    Multi-kitchen: when kitchen_code is set and dish has no explicit station,
    prefer a station in that kitchen with matching type/name, else that kitchen's Main.
    """
    if dish.station_id is not None:
        return dish.station_id
    if dish.category:
        default = await session.scalar(
            select(CategoryStationDefault).where(
                CategoryStationDefault.restaurant_id == restaurant_id,
                CategoryStationDefault.category == dish.category,
            )
        )
        if default is not None:
            return default.station_id
    code = kitchen_code or "main"
    main = await get_or_create_main_station(
        session, restaurant_id=restaurant_id, kitchen_code=code
    )
    return main.id


def _format_print_line(item: OrderItem) -> str:
    line = f"{item.qty}x {item.dish_name}"
    if item.variant_name:
        line += f" ({item.variant_name})"
    mods = getattr(item, "selected_modifiers", None) or []
    if mods:
        mod_bits = []
        for m in mods:
            if isinstance(m, dict):
                mod_bits.append(str(m.get("name") or m))
            else:
                mod_bits.append(str(m))
        if mod_bits:
            line += f" +{', '.join(mod_bits)}"
    if item.notes:
        line += f" NOTE:{item.notes}"
    allergens = getattr(item, "allergens_snapshot", None) or []
    if allergens:
        line += f" ALLERGENS:{','.join(str(a) for a in allergens)}"
    return line


async def _resolve_print_station(
    session: AsyncSession, *, restaurant_id: int, station_id: int
) -> tuple[int, bool, int | None]:
    """Return (print_station_id, via_fallback, original_station_id).

    If the primary station's printer is unhealthy and a fallback is configured
    and healthy, route there.
    """
    station = await session.get(KitchenStation, station_id)
    if station is None:
        return station_id, False, None
    statuses = {
        s["station_id"]: s for s in await get_printer_status(session, restaurant_id=restaurant_id)
    }
    primary = statuses.get(station_id)
    if primary is None or primary.get("healthy", True):
        return station_id, False, None
    fb = station.fallback_station_id
    if fb is None:
        return station_id, False, None
    fb_status = statuses.get(fb)
    if fb_status is not None and not fb_status.get("healthy", True):
        return station_id, False, None
    return fb, True, station_id


def build_print_payload(order: Order, station_items: list[OrderItem]) -> str:
    header = f"Order {order.order_number}"
    if getattr(order, "priority", None) and order.priority != "normal":
        header += f" [{order.priority.upper()}]"
    if getattr(order, "customer_allergy_notes", None):
        header += f"\nCUSTOMER ALLERGY: {order.customer_allergy_notes}"
    if getattr(order, "prep_deadline", None):
        header += f"\nETA plate-by: {order.prep_deadline.isoformat()}"
    lines = [_format_print_line(i) for i in station_items]
    return header + "\n" + "\n".join(lines)


async def create_tickets_for_items(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order,
    items: list[OrderItem],
    kitchen_code: str | None = None,
) -> None:
    """Enqueue KDS tickets + print jobs for a specific set of order lines.

    Used both for initial confirm and for course fire (later courses).
    Print payload includes notes, modifiers, allergens. Printer fallback applied.
    """
    if not items:
        return
    now = datetime.now(timezone.utc)
    by_station: dict[int, list[OrderItem]] = defaultdict(list)
    for item in items:
        if getattr(item, "cancelled", False):
            continue
        dish = await session.get(Dish, item.dish_id)
        station_id = await resolve_station(
            session,
            restaurant_id=restaurant_id,
            dish=dish,
            kitchen_code=kitchen_code,
        )
        station = await session.get(KitchenStation, station_id)
        item.kitchen_status = "received"
        item.station_id_snapshot = station_id
        item.kitchen_code_snapshot = (
            station.kitchen_code if station is not None else (kitchen_code or "main")
        )
        item.kitchen_received_at = now
        by_station[station_id].append(item)

    for station_id, station_items in by_station.items():
        payload = build_print_payload(order, station_items)
        print_station_id, via_fb, original = await _resolve_print_station(
            session, restaurant_id=restaurant_id, station_id=station_id
        )
        session.add(
            PrintJob(
                restaurant_id=restaurant_id,
                station_id=print_station_id,
                order_id=order.id,
                payload=payload,
                status="pending",
                via_fallback=via_fb,
                original_station_id=original,
            )
        )


async def create_tickets_for_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order,
    kitchen_code: str | None = None,
) -> None:
    """Create kitchen tickets for all non-held courses on confirm.

    Items with ``course_held=True`` wait for ``fire_course`` (course-wise ordering).
    """
    items = (
        await session.scalars(
            select(OrderItem).where(
                OrderItem.order_id == order.id,
                OrderItem.cancelled.is_(False),
            )
        )
    ).all()
    fireable = [i for i in items if not getattr(i, "course_held", False)]
    await create_tickets_for_items(
        session,
        restaurant_id=restaurant_id,
        order=order,
        items=fireable,
        kitchen_code=kitchen_code,
    )


async def _get_tenant_order_item(
    session: AsyncSession, *, restaurant_id: int, order_item_id: int
) -> OrderItem:
    item = await session.get(OrderItem, order_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    order = await session.get(Order, item.order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="item not found")
    return item


async def mark_packaging_checked(
    session: AsyncSession, *, restaurant_id: int, order_item_id: int
) -> OrderItem:
    item = await _get_tenant_order_item(
        session, restaurant_id=restaurant_id, order_item_id=order_item_id
    )
    item.packaging_checked = True
    await session.flush()
    return item


async def mark_quality_checked(
    session: AsyncSession, *, restaurant_id: int, order_item_id: int
) -> OrderItem:
    item = await _get_tenant_order_item(
        session, restaurant_id=restaurant_id, order_item_id=order_item_id
    )
    item.quality_checked = True
    await session.flush()
    return item


async def mark_missing_item(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_item_id: int,
    note: str | None = None,
) -> OrderItem:
    """Confirm kitchen noticed a missing/short item on the ticket (packing check)."""
    item = await _get_tenant_order_item(
        session, restaurant_id=restaurant_id, order_item_id=order_item_id
    )
    item.missing_item_confirmed = True
    item.missing_item_note = note
    await session.flush()
    return item


async def list_ready_for_pickup(
    session: AsyncSession, *, restaurant_id: int
) -> dict[int, list[OrderItem]]:
    """Ready-but-not-yet-picked-up items, grouped by order id, for the tenant."""
    rows = (
        await session.scalars(
            select(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                OrderItem.kitchen_status == "ready",
                OrderItem.cancelled.is_(False),
                Order.status.notin_(DEAD_ORDER_STATUSES),
            )
            .order_by(OrderItem.order_id, OrderItem.id)
        )
    ).all()
    by_order: dict[int, list[OrderItem]] = defaultdict(list)
    for item in rows:
        by_order[item.order_id].append(item)
    return by_order


def ticket_urgency(age_minutes: float) -> str:
    if age_minutes >= LATE_AFTER_MINUTES:
        return "late"
    if age_minutes >= WARNING_AFTER_MINUTES:
        return "warning"
    return "ok"


def enrich_ticket(
    item: OrderItem,
    order: Order | None,
    *,
    now: datetime | None = None,
    table_labels: dict[int, str] | None = None,
    dish_categories: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Build a KDS ticket dict with timer, ETA, allergens, modifiers, urgency.

    ``table_labels`` maps table_id -> label so a dine-in ticket can show WHERE
    it came from (the kitchen plates by table, not by order number). Callers
    batch-load it to avoid a per-ticket query; when omitted the ticket simply
    carries table_id with a null label rather than inventing one.
    """
    now = now or datetime.now(timezone.utc)
    created = item.kitchen_received_at or item.created_at
    if created is not None and created.tzinfo is None:
        created_aware = created.replace(tzinfo=timezone.utc)
    else:
        created_aware = created
    if created_aware is None:
        age_seconds = 0.0
        age_minutes = 0.0
    else:
        age_seconds = max(0.0, (now - created_aware).total_seconds())
        age_minutes = age_seconds / 60.0
    urgency = ticket_urgency(age_minutes)
    eta = None
    if order is not None:
        if order.prep_deadline is not None:
            eta = order.prep_deadline.isoformat()
        elif order.promised_eta is not None:
            eta = order.promised_eta.isoformat()
    return {
        "id": item.id,
        "order_id": item.order_id,
        "order_number": order.order_number if order else None,
        "order_priority": getattr(order, "priority", None) if order else None,
        "order_type": getattr(order, "order_type", None) if order else None,
        # Paid and closed, yet still on the pass — the guest is already waiting.
        "order_settled": bool(order is not None and order.status == "delivered"),
        "dish_name": item.dish_name,
        "variant_name": item.variant_name,
        "qty": item.qty,
        "kitchen_status": item.kitchen_status,
        "notes": item.notes,
        "created_at": item.created_at,
        "kitchen_received_at": item.kitchen_received_at or item.created_at,
        "allergens": list(item.allergens_snapshot or []),
        "selected_modifiers": list(item.selected_modifiers or []),
        "packaging_checked": bool(item.packaging_checked),
        "quality_checked": bool(item.quality_checked),
        "missing_item_confirmed": bool(getattr(item, "missing_item_confirmed", False)),
        "missing_item_note": getattr(item, "missing_item_note", None),
        "course_number": getattr(item, "course_number", 1) or 1,
        "course_held": bool(getattr(item, "course_held", False)),
        # Parcel line on a dine-in bill — the kitchen must BOX this one.
        "is_takeaway": bool(getattr(item, "is_takeaway", False)),
        "customer_allergy_notes": getattr(order, "customer_allergy_notes", None) if order else None,
        "estimated_ready_at": eta,
        # The 40-min customer SLA clock start (= sla_confirmed_at, same mapping the
        # order API uses), so the board can show the SAME countdown the manager
        # dashboard shows (down from 40:00, then LATE).
        "sla_started_at": (
            order.sla_confirmed_at.isoformat()
            if order is not None and getattr(order, "sla_confirmed_at", None)
            else None
        ),
        "age_seconds": int(age_seconds),
        "age_minutes": round(age_minutes, 1),
        "urgency": urgency,
        "is_delayed": urgency in ("warning", "late"),
        "station_id": item.station_id_snapshot,
        "kitchen_code": getattr(item, "kitchen_code_snapshot", None),
        # The dish's real menu category ("Popcorn", "Paratha Spot"). Stations are
        # generic presets and may not describe this kitchen, so the board shows
        # the category the restaurant actually defined.
        "category": (dish_categories or {}).get(item.dish_id),
        # Source of the ticket: which table the waiter sent it from.
        "table_id": getattr(order, "table_id", None) if order else None,
        "table_label": (
            (table_labels or {}).get(order.table_id)
            if order is not None and order.table_id is not None
            else None
        ),
    }


async def list_station_tickets(
    session: AsyncSession,
    *,
    restaurant_id: int,
    station_id: int,
    include_ready: bool = False,
) -> list[dict[str, Any]]:
    """Active tickets for a station, auto-prioritized oldest-first."""
    statuses = ["received", "preparing"]
    if include_ready:
        statuses.append("ready")
    rows = (
        await session.scalars(
            select(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                OrderItem.station_id_snapshot == station_id,
                OrderItem.kitchen_status.in_(statuses),
                OrderItem.cancelled.is_(False),
                Order.held_at.is_(None),
                # A cancelled/voided order must leave the pass immediately —
                # otherwise the kitchen keeps cooking food nobody will pay for.
                Order.status.notin_(DEAD_ORDER_STATUSES),
            )
            .order_by(
                # Auto-prioritize old orders: oldest kitchen_received_at first.
                OrderItem.kitchen_received_at.asc().nulls_last(),
                OrderItem.created_at.asc(),
            )
        )
    ).all()
    order_ids = {i.order_id for i in rows}
    orders: dict[int, Order] = {}
    if order_ids:
        for o in (
            await session.scalars(select(Order).where(Order.id.in_(order_ids)))
        ).all():
            orders[o.id] = o
    # Batch-load table labels once so dine-in tickets can show their table.
    table_labels: dict[int, str] = {}
    table_ids = {o.table_id for o in orders.values() if o.table_id is not None}
    if table_ids:
        from app.tables.models import DiningTable

        for t in (
            await session.scalars(
                select(DiningTable).where(DiningTable.id.in_(table_ids))
            )
        ).all():
            table_labels[t.id] = t.label

    # Batch-load real menu categories for the board chips.
    dish_categories: dict[int, str] = {}
    dish_ids = {i.dish_id for i in rows if i.dish_id is not None}
    if dish_ids:
        for d in (await session.scalars(select(Dish).where(Dish.id.in_(dish_ids)))).all():
            if d.category:
                dish_categories[d.id] = d.category

    # Priority orders float above normal when equally old-ish: stable secondary sort
    enriched = [
        enrich_ticket(
            i,
            orders.get(i.order_id),
            table_labels=table_labels,
            dish_categories=dish_categories,
        )
        for i in rows
    ]
    enriched.sort(
        key=lambda t: (
            0 if (t.get("order_priority") or "normal") in ("rush", "priority") else 1,
            t.get("age_seconds") is None,
            -(t.get("age_seconds") or 0),  # older first among same priority band → wait, we want oldest first so higher age first
        )
    )
    # Fix: oldest first within priority band (rush first, then by age desc so older higher)
    enriched.sort(
        key=lambda t: (
            0 if (t.get("order_priority") or "normal") in ("rush", "priority") else 1,
            -(t.get("age_seconds") or 0),
        )
    )
    return enriched


async def kitchen_performance_report(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Throughput, bump rates, late tickets, avg prep by station."""
    from datetime import datetime as dt
    from datetime import time, timedelta

    start = dt.combine(start_date, time.min)
    end = dt.combine(end_date + timedelta(days=1), time.min)
    items = (
        await session.scalars(
            select(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                OrderItem.kitchen_received_at.is_not(None),
                OrderItem.kitchen_received_at >= start,
                OrderItem.kitchen_received_at < end,
            )
        )
    ).all()
    total = len(items)
    bumped = [i for i in items if i.bumped_at is not None]
    late = 0
    prep_minutes: list[float] = []
    by_station: dict[int | None, list[float]] = defaultdict(list)
    for item in bumped:
        recv = item.kitchen_received_at or item.created_at
        if recv is None or item.bumped_at is None:
            continue
        if recv.tzinfo is None:
            recv = recv.replace(tzinfo=timezone.utc)
        bumped_at = item.bumped_at
        if bumped_at.tzinfo is None:
            bumped_at = bumped_at.replace(tzinfo=timezone.utc)
        mins = (bumped_at - recv).total_seconds() / 60.0
        prep_minutes.append(mins)
        by_station[item.station_id_snapshot].append(mins)
        if mins >= LATE_AFTER_MINUTES:
            late += 1

    station_ids = {sid for sid in by_station if sid is not None}
    names = {}
    if station_ids:
        for s in (
            await session.scalars(select(KitchenStation).where(KitchenStation.id.in_(station_ids)))
        ).all():
            names[s.id] = s.name

    return {
        "ticket_count": total,
        "bumped_count": len(bumped),
        "late_ticket_count": late,
        "avg_prep_minutes": round(sum(prep_minutes) / len(prep_minutes), 2) if prep_minutes else None,
        "by_station": [
            {
                "station_id": sid,
                "station_name": names.get(sid, "Unassigned") if sid else "Unassigned",
                "avg_prep_minutes": round(sum(mins) / len(mins), 2),
                "ticket_count": len(mins),
            }
            for sid, mins in by_station.items()
        ],
    }


async def set_category_station_default(
    session: AsyncSession,
    *,
    restaurant_id: int,
    category: str,
    station_id: int,
) -> CategoryStationDefault:
    station = await session.get(KitchenStation, station_id)
    if station is None or station.restaurant_id != restaurant_id:
        raise ValueError("station not found")
    row = await session.scalar(
        select(CategoryStationDefault).where(
            CategoryStationDefault.restaurant_id == restaurant_id,
            CategoryStationDefault.category == category,
        )
    )
    if row is None:
        row = CategoryStationDefault(
            restaurant_id=restaurant_id, category=category, station_id=station_id
        )
        session.add(row)
    else:
        row.station_id = station_id
    await session.flush()
    return row


def validate_station_type(station_type: str) -> str:
    value = (station_type or "general").strip().lower()
    if value not in STATION_TYPES:
        raise ValueError(f"invalid station_type {station_type!r}; allowed: {sorted(STATION_TYPES)}")
    return value
