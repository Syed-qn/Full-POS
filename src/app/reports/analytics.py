from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.inventory.costing import dish_cost
from app.inventory.models import DishIngredient
from app.ordering.fsm import OrderStatus
from app.ordering.models import Order, OrderItem

# Orders in these statuses never represent realized sales / customer activity.
_EXCLUDED_STATUSES = ("cancelled", "draft")

_ROLLUP_GRANULARITIES = ("hourly", "daily", "weekly", "monthly")
_GRANULARITY_TO_TRUNC = {
    "hourly": "hour",
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
}


def _day_window(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    return datetime.combine(start_date, time.min), datetime.combine(end_date, time.max)


# Orders in these statuses have had a tax invoice issued (VAT snapshotted at
# confirm time — see app.ordering.tax.apply_vat) and haven't since been voided.
# DRAFT/PENDING_CONFIRMATION never got an invoice number "used" for a real sale,
# and CANCELLED/UNDELIVERABLE/ON_RESALE/RESOLD/WRITTEN_OFF are out of scope here
# (crediting/voiding an issued invoice is a separate concern) — so gaps caused by
# those are expected and must not be flagged by the sequence-gap check below.
_INVOICED_STATUSES = frozenset(
    {
        OrderStatus.CONFIRMED,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.ASSIGNED,
        OrderStatus.PICKED_UP,
        OrderStatus.ARRIVING,
        OrderStatus.DELIVERED,
    }
)


async def item_performance(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
        )
    )).all()
    order_ids = [o.id for o in orders]
    if not order_ids:
        return []
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    )).all()

    by_dish: dict[str, dict] = {}
    for item in items:
        row = by_dish.setdefault(
            item.dish_name,
            {"dish_id": item.dish_id, "dish_name": item.dish_name, "order_count": 0, "revenue_aed": Decimal("0.00")},
        )
        row["order_count"] += item.qty
        row["revenue_aed"] += item.price_aed * item.qty

    for row in by_dish.values():
        unit_cost = await dish_cost(session, dish_id=row["dish_id"])
        cost_total = unit_cost * row["order_count"]
        row["food_cost_aed"] = cost_total.quantize(Decimal("0.01"))
        row["margin_aed"] = (row["revenue_aed"] - cost_total).quantize(Decimal("0.01"))
        row["margin_pct"] = (
            round(float((row["revenue_aed"] - cost_total) / row["revenue_aed"] * 100), 2)
            if row["revenue_aed"] > 0 else 0.0
        )

    return sorted(by_dish.values(), key=lambda r: r["revenue_aed"], reverse=True)


async def inventory_usage(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    from app.inventory.models import Ingredient

    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
        )
    )).all()
    order_ids = [o.id for o in orders]
    if not order_ids:
        return []
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    )).all()
    qty_by_dish: dict[int, int] = defaultdict(int)
    for item in items:
        qty_by_dish[item.dish_id] += item.qty

    recipes = (await session.scalars(
        select(DishIngredient).where(DishIngredient.dish_id.in_(qty_by_dish.keys()))
    )).all()
    used: dict[int, Decimal] = defaultdict(lambda: Decimal("0.000"))
    for recipe in recipes:
        used[recipe.ingredient_id] += recipe.quantity_per_dish * qty_by_dish[recipe.dish_id]

    ingredients = (await session.scalars(
        select(Ingredient).where(Ingredient.id.in_(used.keys()))
    )).all()
    by_id = {ing.id: ing for ing in ingredients}
    return [
        {"ingredient_id": iid, "ingredient_name": by_id[iid].name, "quantity_used": qty}
        for iid, qty in used.items() if iid in by_id
    ]


async def table_turn_time(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    day_start, day_end = _day_window(start_date, end_date)
    rows = (await session.scalars(
        select(AuditLog).where(
            AuditLog.restaurant_id == restaurant_id, AuditLog.entity == "table",
            AuditLog.created_at >= day_start, AuditLog.created_at <= day_end,
        ).order_by(AuditLog.created_at)
    )).all()

    by_table: dict[str, list[AuditLog]] = defaultdict(list)
    for row in rows:
        by_table[row.entity_id].append(row)

    results = []
    for table_id, events in by_table.items():
        seated_at: datetime | None = None
        for event in events:
            after_status = (event.after or {}).get("status")
            if after_status == "seated":
                seated_at = event.created_at
            elif after_status == "available" and seated_at is not None:
                minutes = (event.created_at - seated_at).total_seconds() / 60.0
                results.append({"table_id": int(table_id), "turn_minutes": round(minutes, 2)})
                seated_at = None
    return results


def _prep_minutes(item: OrderItem) -> float:
    """OrderItem.created_at is stored naive UTC (TimestampMixin); bumped_at is
    stored tz-aware UTC (DateTime(timezone=True)). Normalize both to aware UTC
    before subtracting — project convention, see e.g. app.sla.monitor."""
    created_at = item.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    bumped_at = item.bumped_at
    if bumped_at.tzinfo is None:
        bumped_at = bumped_at.replace(tzinfo=timezone.utc)
    return (bumped_at - created_at).total_seconds() / 60.0


async def _prep_time_rows(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[OrderItem]:
    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
        )
    )).all()
    order_ids = [o.id for o in orders]
    if not order_ids:
        return []
    items = (await session.scalars(
        select(OrderItem).where(
            OrderItem.order_id.in_(order_ids),
            OrderItem.bumped_at.is_not(None),
        )
    )).all()
    return list(items)


async def avg_prep_time_by_item(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Prep time = OrderItem.created_at (ticket fired) -> OrderItem.bumped_at
    (marked ready in KDS), grouped by dish name."""
    items = await _prep_time_rows(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    by_dish: dict[str, list[float]] = defaultdict(list)
    for item in items:
        by_dish[item.dish_name].append(_prep_minutes(item))

    return [
        {
            "key": key,
            "avg_prep_minutes": round(sum(minutes) / len(minutes), 2),
            "ticket_count": len(minutes),
        }
        for key, minutes in by_dish.items()
    ]


async def avg_prep_time_by_staff(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Grouped by whichever kitchen station handled the ticket — there is no
    per-staff bump attribution on OrderItem today, so the station that owned
    the ticket (OrderItem.station_id_snapshot) is used as the "staff" key."""
    from app.kds.models import KitchenStation

    items = await _prep_time_rows(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    station_ids = {item.station_id_snapshot for item in items if item.station_id_snapshot is not None}
    stations = (await session.scalars(
        select(KitchenStation).where(KitchenStation.id.in_(station_ids))
    )).all() if station_ids else []
    station_names = {s.id: s.name for s in stations}

    by_station: dict[str, list[float]] = defaultdict(list)
    for item in items:
        key = station_names.get(item.station_id_snapshot, "Unassigned")
        by_station[key].append(_prep_minutes(item))

    return [
        {
            "key": key,
            "avg_prep_minutes": round(sum(minutes) / len(minutes), 2),
            "ticket_count": len(minutes),
        }
        for key, minutes in by_station.items()
    ]


async def labor_hours(session: AsyncSession, *, restaurant_id: int, target_date: date) -> list[dict]:
    from app.staff.models import StaffMember
    from app.staff.service import compute_hours

    staff_rows = (await session.scalars(
        select(StaffMember).where(StaffMember.restaurant_id == restaurant_id)
    )).all()
    results = []
    for staff in staff_rows:
        hours = await compute_hours(
            session, staff_id=staff.id, restaurant_id=restaurant_id, target_date=target_date
        )
        if hours > 0:
            results.append({"staff_id": staff.id, "name": staff.name, "hours": round(hours, 2)})
    return results


async def sales_rollup(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date, granularity: str
) -> list[dict]:
    if granularity not in _ROLLUP_GRANULARITIES:
        raise ValueError(
            f"Invalid granularity {granularity!r}; must be one of {_ROLLUP_GRANULARITIES}"
        )
    day_start, day_end = _day_window(start_date, end_date)
    trunc_unit = _GRANULARITY_TO_TRUNC[granularity]
    bucket = func.date_trunc(trunc_unit, Order.created_at).label("bucket")

    rows = (await session.execute(
        select(
            bucket,
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total), Decimal("0.00")).label("revenue_aed"),
        ).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
            Order.status.notin_(_EXCLUDED_STATUSES),
        ).group_by(bucket).order_by(bucket)
    )).all()

    return [
        {
            "bucket": row.bucket.isoformat(),
            "order_count": row.order_count,
            "revenue_aed": row.revenue_aed,
        }
        for row in rows
    ]


async def retention_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
            Order.status.notin_(_EXCLUDED_STATUSES),
        )
    )).all()
    customer_ids = {o.customer_id for o in orders}
    if not customer_ids:
        return {"new_customers": 0, "returning_customers": 0, "repeat_rate_pct": 0.0}

    prior_customer_ids = set((await session.scalars(
        select(Order.customer_id).where(
            Order.restaurant_id == restaurant_id,
            Order.customer_id.in_(customer_ids),
            Order.created_at < day_start,
            Order.status.notin_(_EXCLUDED_STATUSES),
        ).distinct()
    )).all())

    returning_customers = len(customer_ids & prior_customer_ids)
    new_customers = len(customer_ids) - returning_customers
    total = len(customer_ids)
    repeat_rate_pct = round((returning_customers / total) * 100, 2) if total else 0.0

    return {
        "new_customers": new_customers,
        "returning_customers": returning_customers,
        "repeat_rate_pct": repeat_rate_pct,
    }


async def invoice_sequence_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    """FTA audit artifact: confirm the tax-invoice number sequence has no gaps.

    ``Order.order_number`` (format ``R{restaurant_id}-{seq:04d}``) is already
    allocated gap-free/collision-free for concurrently-created orders by the
    advisory-lock allocator in ``create_draft_order`` (see service.py) — the FTA
    requirement this satisfies is that once a tax invoice IS issued (order reaches
    ``confirmed`` or later, see ``_INVOICED_STATUSES``), its number must be part of
    an unbroken numeric run with no skipped/reused invoice numbers. This walks the
    already-allocated numbers for invoiced orders in the given date range and
    surfaces any missing suffixes an FTA auditor would flag.

    Draft orders that never got invoiced (deleted, abandoned) legitimately "use up"
    a number without becoming an invoice — that is NOT a gap for this check.
    """
    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
            Order.status.in_([s.value for s in _INVOICED_STATUSES]),
        )
    )).all()

    parsed: list[tuple[int, str, str, int]] = []  # (seq, prefix, order_number, suffix_width)
    for order in orders:
        number = str(order.order_number)
        if "-" not in number:
            continue
        prefix, suffix = number.rsplit("-", 1)
        if not suffix.isdigit():
            continue
        parsed.append((int(suffix), prefix, number, len(suffix)))

    if not parsed:
        return {
            "first_invoice": None,
            "last_invoice": None,
            "expected_count": 0,
            "actual_count": 0,
            "gaps_detected": [],
        }

    parsed.sort(key=lambda row: row[0])
    first_seq, prefix, first_invoice, suffix_width = parsed[0]
    last_seq, _, last_invoice, _ = parsed[-1]
    actual_seqs = {row[0] for row in parsed}
    expected_count = last_seq - first_seq + 1
    gaps_detected = [
        f"{prefix}-{seq:0{suffix_width}d}"
        for seq in range(first_seq, last_seq + 1)
        if seq not in actual_seqs
    ]

    return {
        "first_invoice": first_invoice,
        "last_invoice": last_invoice,
        "expected_count": expected_count,
        "actual_count": len(parsed),
        "gaps_detected": gaps_detected,
    }
