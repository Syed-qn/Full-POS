"""Category 10 extended analytics — channel/waiter/category/voids/refunds/tax/etc."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ordering.models import Order, OrderItem
from app.reports.analytics import _day_window, _EXCLUDED_STATUSES, item_performance


def _money(d: Decimal | float | int) -> Decimal:
    return Decimal(str(d)).quantize(Decimal("0.01"))


def _channel_of(order: Order) -> str:
    if order.source_channel:
        return str(order.source_channel).lower()
    if order.aggregator_source:
        return str(order.aggregator_source).lower()
    ot = (order.order_type or "delivery").lower()
    if ot == "delivery":
        return "whatsapp"
    if ot == "online":
        return "website"
    return ot


async def _period_orders(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date,
    end_date: date,
    include_cancelled: bool = False,
) -> list[Order]:
    day_start, day_end = _day_window(start_date, end_date)
    stmt = select(Order).where(
        Order.restaurant_id == restaurant_id,
        Order.created_at >= day_start,
        Order.created_at <= day_end,
    )
    if not include_cancelled:
        stmt = stmt.where(Order.status.notin_(_EXCLUDED_STATUSES))
        # exclude training
        stmt = stmt.where(Order.is_training.is_(False))
    return list((await session.scalars(stmt)).all())


async def sales_by_category(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    from app.menu.models import Dish

    orders = await _period_orders(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    if not orders:
        return []
    items = list(
        (
            await session.scalars(
                select(OrderItem).where(OrderItem.order_id.in_([o.id for o in orders]))
            )
        ).all()
    )
    dish_ids = {i.dish_id for i in items if i.dish_id}
    dishes = {}
    if dish_ids:
        for d in (
            await session.scalars(select(Dish).where(Dish.id.in_(dish_ids)))
        ).all():
            dishes[d.id] = d

    buckets: dict[str, dict] = defaultdict(
        lambda: {"category": "", "order_count": 0, "qty": 0, "revenue_aed": Decimal("0.00")}
    )
    for item in items:
        dish = dishes.get(item.dish_id)
        cat = (dish.category if dish and dish.category else None) or "Uncategorized"
        b = buckets[cat]
        b["category"] = cat
        b["order_count"] += 1
        b["qty"] += item.qty
        b["revenue_aed"] = _money(b["revenue_aed"] + item.price_aed * item.qty)
    return sorted(buckets.values(), key=lambda r: r["revenue_aed"], reverse=True)


async def sales_by_channel(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    orders = await _period_orders(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    buckets: dict[str, dict] = defaultdict(
        lambda: {
            "channel": "",
            "order_count": 0,
            "revenue_aed": Decimal("0.00"),
            "aov_aed": Decimal("0.00"),
        }
    )
    for o in orders:
        ch = _channel_of(o)
        b = buckets[ch]
        b["channel"] = ch
        b["order_count"] += 1
        b["revenue_aed"] = _money(b["revenue_aed"] + (o.total or Decimal("0")))
    for b in buckets.values():
        if b["order_count"]:
            b["aov_aed"] = _money(b["revenue_aed"] / b["order_count"])
    return sorted(buckets.values(), key=lambda r: r["revenue_aed"], reverse=True)


async def sales_by_waiter(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    from app.staff.models import StaffMember

    orders = await _period_orders(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    buckets: dict[int | None, dict] = defaultdict(
        lambda: {
            "staff_id": None,
            "staff_name": "Unassigned",
            "order_count": 0,
            "revenue_aed": Decimal("0.00"),
        }
    )
    staff_ids = {o.staff_id for o in orders if o.staff_id}
    names: dict[int, str] = {}
    if staff_ids:
        for s in (
            await session.scalars(select(StaffMember).where(StaffMember.id.in_(staff_ids)))
        ).all():
            names[s.id] = s.name
    for o in orders:
        key = o.staff_id
        b = buckets[key]
        b["staff_id"] = key
        b["staff_name"] = names.get(key, "Unassigned") if key else "Unassigned"
        b["order_count"] += 1
        b["revenue_aed"] = _money(b["revenue_aed"] + (o.total or Decimal("0")))
    return sorted(buckets.values(), key=lambda r: r["revenue_aed"], reverse=True)


async def sales_by_payment_method(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    from app.payments.models import PaymentTransaction

    day_start, day_end = _day_window(start_date, end_date)
    rows = (
        await session.execute(
            select(
                PaymentTransaction.tender_type,
                func.count(PaymentTransaction.id),
                func.coalesce(func.sum(PaymentTransaction.amount_aed), Decimal("0")),
                func.coalesce(func.sum(PaymentTransaction.tip_aed), Decimal("0")),
                func.coalesce(func.sum(PaymentTransaction.refunded_amount_aed), Decimal("0")),
            )
            .where(
                PaymentTransaction.restaurant_id == restaurant_id,
                PaymentTransaction.created_at >= day_start,
                PaymentTransaction.created_at <= day_end,
                PaymentTransaction.status.in_(
                    ("succeeded", "refunded", "partially_refunded")
                ),
            )
            .group_by(PaymentTransaction.tender_type)
        )
    ).all()
    return [
        {
            "tender_type": tender or "unknown",
            "txn_count": int(cnt),
            "gross_aed": str(_money(gross)),
            "tips_aed": str(_money(tips)),
            "refunded_aed": str(_money(refunded)),
            "net_aed": str(_money(Decimal(str(gross)) - Decimal(str(refunded)))),
        }
        for tender, cnt, gross, tips, refunded in rows
    ]


async def gross_profit_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    items = await item_performance(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    revenue = sum((r["revenue_aed"] for r in items), Decimal("0.00"))
    food_cost = sum((r["food_cost_aed"] for r in items), Decimal("0.00"))
    profit = _money(revenue - food_cost)
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "gross_revenue_aed": str(_money(revenue)),
        "food_cost_aed": str(_money(food_cost)),
        "gross_profit_aed": str(profit),
        "gross_margin_pct": round(float(profit / revenue * 100), 2) if revenue > 0 else 0.0,
        "item_rows": len(items),
    }


async def food_cost_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    items = await item_performance(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    food_cost = sum((r["food_cost_aed"] for r in items), Decimal("0.00"))
    revenue = sum((r["revenue_aed"] for r in items), Decimal("0.00"))
    by_dish = [
        {
            "dish_name": r["dish_name"],
            "qty": r["order_count"],
            "food_cost_aed": str(r["food_cost_aed"]),
            "revenue_aed": str(r["revenue_aed"]),
            "food_cost_pct": r.get("food_cost_pct", 0.0),
        }
        for r in items
    ]
    return {
        "total_food_cost_aed": str(_money(food_cost)),
        "total_revenue_aed": str(_money(revenue)),
        "food_cost_pct": round(float(food_cost / revenue * 100), 2) if revenue > 0 else 0.0,
        "rows": by_dish,
    }


async def discount_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    orders = await _period_orders(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    manager = sum((o.manager_discount_aed or Decimal("0") for o in orders), Decimal("0"))
    staff = sum((o.staff_discount_aed or Decimal("0") for o in orders), Decimal("0"))
    coupon = sum((o.coupon_discount_aed or Decimal("0") for o in orders), Decimal("0"))
    lines = [
        {
            "order_id": o.id,
            "order_number": o.order_number,
            "manager_discount_aed": str(_money(o.manager_discount_aed or 0)),
            "staff_discount_aed": str(_money(o.staff_discount_aed or 0)),
            "coupon_discount_aed": str(_money(o.coupon_discount_aed or 0)),
            "total_discount_aed": str(
                _money(
                    (o.manager_discount_aed or 0)
                    + (o.staff_discount_aed or 0)
                    + (o.coupon_discount_aed or 0)
                )
            ),
        }
        for o in orders
        if (o.manager_discount_aed or 0) + (o.staff_discount_aed or 0) + (o.coupon_discount_aed or 0)
        > 0
    ]
    return {
        "manager_discount_aed": str(_money(manager)),
        "staff_discount_aed": str(_money(staff)),
        "coupon_discount_aed": str(_money(coupon)),
        "total_discounts_aed": str(_money(manager + staff + coupon)),
        "discounted_order_count": len(lines),
        "rows": lines,
    }


async def void_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    day_start, day_end = _day_window(start_date, end_date)
    orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status == "cancelled",
                    Order.created_at >= day_start,
                    Order.created_at <= day_end,
                )
            )
        ).all()
    )
    total = sum((o.total or Decimal("0") for o in orders), Decimal("0"))
    return {
        "void_count": len(orders),
        "void_value_aed": str(_money(total)),
        "rows": [
            {
                "order_id": o.id,
                "order_number": o.order_number,
                "total_aed": str(_money(o.total or 0)),
                "reason": o.cancellation_reason,
                "staff_id": o.staff_id,
                "cancelled_at": o.cancelled_at.isoformat() if o.cancelled_at else None,
            }
            for o in orders
        ],
    }


async def refund_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    from app.payments.models import PaymentTransaction

    day_start, day_end = _day_window(start_date, end_date)
    txns = list(
        (
            await session.scalars(
                select(PaymentTransaction).where(
                    PaymentTransaction.restaurant_id == restaurant_id,
                    PaymentTransaction.created_at >= day_start,
                    PaymentTransaction.created_at <= day_end,
                    PaymentTransaction.refunded_amount_aed > 0,
                )
            )
        ).all()
    )
    total = sum((t.refunded_amount_aed for t in txns), Decimal("0"))
    return {
        "refund_txn_count": len(txns),
        "refunded_total_aed": str(_money(total)),
        "rows": [
            {
                "txn_id": t.id,
                "order_id": t.order_id,
                "tender_type": t.tender_type,
                "amount_aed": str(_money(t.amount_aed)),
                "refunded_amount_aed": str(_money(t.refunded_amount_aed)),
                "status": t.status,
            }
            for t in txns
        ],
    }


async def wastage_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    from app.inventory.models import Ingredient, WasteLog

    day_start, day_end = _day_window(start_date, end_date)
    logs = list(
        (
            await session.scalars(
                select(WasteLog).where(
                    WasteLog.restaurant_id == restaurant_id,
                    WasteLog.created_at >= day_start,
                    WasteLog.created_at <= day_end,
                )
            )
        ).all()
    )
    ing_ids = {w.ingredient_id for w in logs}
    names = {}
    costs = {}
    if ing_ids:
        for ing in (
            await session.scalars(select(Ingredient).where(Ingredient.id.in_(ing_ids)))
        ).all():
            names[ing.id] = ing.name
            costs[ing.id] = getattr(ing, "cost_per_unit_aed", None) or Decimal("0")

    by_type: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    rows = []
    total_cost = Decimal("0")
    for w in logs:
        unit_cost = costs.get(w.ingredient_id, Decimal("0"))
        cost = _money(Decimal(str(w.quantity)) * Decimal(str(unit_cost)))
        total_cost += cost
        by_type[w.reason_type] += cost
        rows.append(
            {
                "id": w.id,
                "ingredient": names.get(w.ingredient_id, str(w.ingredient_id)),
                "quantity": str(w.quantity),
                "reason_type": w.reason_type,
                "reason": w.reason,
                "estimated_cost_aed": str(cost),
                "recorded_by": w.recorded_by,
            }
        )
    return {
        "event_count": len(logs),
        "estimated_cost_aed": str(_money(total_cost)),
        "by_reason_type": {k: str(_money(v)) for k, v in by_type.items()},
        "rows": rows,
    }


async def top_selling_items(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date,
    end_date: date,
    limit: int = 10,
) -> list[dict]:
    items = await item_performance(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    lim = min(max(limit, 1), 100)
    return [
        {
            "rank": i + 1,
            "dish_name": r["dish_name"],
            "order_count": r["order_count"],
            "revenue_aed": str(r["revenue_aed"]),
        }
        for i, r in enumerate(items[:lim])
    ]


async def slow_moving_items(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date,
    end_date: date,
    max_qty: int = 3,
) -> list[dict]:
    """Items sold at most ``max_qty`` times in the period (but at least once)."""
    items = await item_performance(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    slow = [r for r in items if 0 < r["order_count"] <= max_qty]
    slow.sort(key=lambda r: r["order_count"])
    return [
        {
            "dish_name": r["dish_name"],
            "order_count": r["order_count"],
            "revenue_aed": str(r["revenue_aed"]),
        }
        for r in slow
    ]


async def dead_menu_items(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Active menu dishes with zero sales in the period."""
    from app.menu.models import Dish, Menu

    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
    if menu is None:
        return []
    dishes = list(
        (
            await session.scalars(
                select(Dish).where(
                    Dish.restaurant_id == restaurant_id,
                    Dish.menu_id == menu.id,
                    Dish.is_available.is_(True),
                )
            )
        ).all()
    )
    sold = await item_performance(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    sold_names = {r["dish_name"] for r in sold}
    return [
        {
            "dish_id": d.id,
            "dish_number": d.dish_number,
            "dish_name": d.name,
            "category": d.category,
            "price_aed": str(d.price_aed or Decimal("0")),
        }
        for d in dishes
        if d.name not in sold_names
    ]


async def average_order_value(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    orders = await _period_orders(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    count = len(orders)
    revenue = sum((o.total or Decimal("0") for o in orders), Decimal("0"))
    return {
        "order_count": count,
        "revenue_aed": str(_money(revenue)),
        "aov_aed": str(_money(revenue / count) if count else Decimal("0")),
    }


async def average_delivery_time(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    day_start, day_end = _day_window(start_date, end_date)
    orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status == "delivered",
                    Order.delivered_at.isnot(None),
                    Order.sla_confirmed_at.isnot(None),
                    Order.delivered_at >= day_start,
                    Order.delivered_at <= day_end,
                    Order.is_training.is_(False),
                )
            )
        ).all()
    )
    durations = [
        (o.delivered_at - o.sla_confirmed_at).total_seconds() / 60.0 for o in orders
    ]
    late = sum(1 for o in orders if o.late)
    return {
        "delivery_count": len(orders),
        "avg_delivery_minutes": round(sum(durations) / len(durations), 2)
        if durations
        else None,
        "p50_minutes": round(sorted(durations)[len(durations) // 2], 2)
        if durations
        else None,
        "late_count": late,
        "late_pct": round(late / len(orders) * 100, 2) if orders else 0.0,
    }


async def peak_hour_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    from app.reports.analytics import sales_rollup

    rows = await sales_rollup(
        session,
        restaurant_id=restaurant_id,
        start_date=start_date,
        end_date=end_date,
        granularity="hourly",
    )
    if not rows:
        return {"peak_bucket": None, "peak_order_count": 0, "peak_revenue_aed": "0.00", "hours": []}
    peak = max(rows, key=lambda r: (r["order_count"], r["revenue_aed"]))
    return {
        "peak_bucket": peak["bucket"],
        "peak_order_count": peak["order_count"],
        "peak_revenue_aed": str(_money(peak["revenue_aed"])),
        "hours": [
            {
                "bucket": r["bucket"],
                "order_count": r["order_count"],
                "revenue_aed": str(_money(r["revenue_aed"])),
                "is_peak": r["bucket"] == peak["bucket"],
            }
            for r in rows
        ],
    }


async def tax_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    orders = await _period_orders(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    # Only orders that look invoiced (confirmed+)
    invoiced = [
        o
        for o in orders
        if o.status
        not in ("draft", "pending_confirmation", "cancelled", "undeliverable")
    ]
    vat = sum((o.vat_amount_aed or Decimal("0") for o in invoiced), Decimal("0"))
    net = sum(
        (
            (o.total or Decimal("0")) - (o.vat_amount_aed or Decimal("0"))
            for o in invoiced
        ),
        Decimal("0"),
    )
    by_rate: dict[str, dict] = defaultdict(
        lambda: {"vat_rate": "", "order_count": 0, "vat_aed": Decimal("0"), "net_aed": Decimal("0")}
    )
    for o in invoiced:
        rate = str(o.vat_rate or Decimal("0.05"))
        b = by_rate[rate]
        b["vat_rate"] = rate
        b["order_count"] += 1
        b["vat_aed"] = _money(b["vat_aed"] + (o.vat_amount_aed or 0))
        b["net_aed"] = _money(
            b["net_aed"] + ((o.total or 0) - (o.vat_amount_aed or 0))
        )
    return {
        "order_count": len(invoiced),
        "taxable_net_aed": str(_money(net)),
        "vat_total_aed": str(_money(vat)),
        "gross_incl_vat_aed": str(_money(net + vat)),
        "by_rate": [
            {
                "vat_rate": r["vat_rate"],
                "order_count": r["order_count"],
                "vat_aed": str(r["vat_aed"]),
                "net_aed": str(r["net_aed"]),
            }
            for r in by_rate.values()
        ],
    }


async def retention_cohort_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    """Weekly cohorts: customers first seen in week W, returning in later weeks of range."""
    from app.reports.analytics import retention_report

    base = await retention_report(
        session, restaurant_id=restaurant_id, start_date=start_date, end_date=end_date
    )
    day_start, day_end = _day_window(start_date, end_date)
    orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.created_at >= day_start,
                    Order.created_at <= day_end,
                    Order.status.notin_(_EXCLUDED_STATUSES),
                )
            )
        ).all()
    )
    # first order week per customer in range
    first_week: dict[int, date] = {}
    for o in sorted(orders, key=lambda x: x.created_at):
        cid = o.customer_id
        if cid is None:
            continue
        d = o.created_at.date() if hasattr(o.created_at, "date") else start_date
        week = d - timedelta(days=d.weekday())
        if cid not in first_week:
            first_week[cid] = week

    cohort_sizes: dict[str, int] = defaultdict(int)
    for week in first_week.values():
        cohort_sizes[week.isoformat()] += 1

    # retention_rate = returning / (new+returning) already in base; add period label
    return {
        **base,
        "retention_rate_pct": base.get("repeat_rate_pct", 0.0),
        "cohorts": [
            {"cohort_week": k, "new_customers": v}
            for k, v in sorted(cohort_sizes.items())
        ],
    }


async def forecasted_sales_aed(
    session: AsyncSession, *, restaurant_id: int, horizon: str = "tomorrow"
) -> dict:
    """Convert order-count forecast into AED using trailing 14-day AOV."""
    today = date.today()
    aov_data = await average_order_value(
        session,
        restaurant_id=restaurant_id,
        start_date=today - timedelta(days=14),
        end_date=today,
    )
    aov = Decimal(aov_data["aov_aed"])

    predicted_orders = 0
    run_id = None
    try:
        from app.predictions.models import PredictionRun

        run = await session.scalar(
            select(PredictionRun)
            .where(
                PredictionRun.restaurant_id == restaurant_id,
                PredictionRun.horizon == horizon,
            )
            .order_by(PredictionRun.created_at.desc())
            .limit(1)
        )
        if run is not None:
            run_id = run.id
            predicted = run.predicted or {}
            if isinstance(predicted, dict):
                if "order_count" in predicted:
                    predicted_orders = int(predicted["order_count"] or 0)
                elif "total_orders" in predicted:
                    predicted_orders = int(predicted["total_orders"] or 0)
    except Exception:
        predicted_orders = 0

    return {
        "horizon": horizon,
        "forecast_run_id": run_id,
        "predicted_order_count": predicted_orders,
        "trailing_aov_aed": str(aov),
        "forecasted_sales_aed": str(_money(aov * Decimal(predicted_orders))),
    }


async def build_owner_daily_summary(
    session: AsyncSession, *, restaurant_id: int, target_date: date
) -> dict:
    from app.reports.zreport import build_z_report

    z = await build_z_report(session, restaurant_id=restaurant_id, target_date=target_date)
    aov = await average_order_value(
        session, restaurant_id=restaurant_id, start_date=target_date, end_date=target_date
    )
    delivery = await average_delivery_time(
        session, restaurant_id=restaurant_id, start_date=target_date, end_date=target_date
    )
    channels = await sales_by_channel(
        session, restaurant_id=restaurant_id, start_date=target_date, end_date=target_date
    )
    top = await top_selling_items(
        session,
        restaurant_id=restaurant_id,
        start_date=target_date,
        end_date=target_date,
        limit=3,
    )
    text = (
        f"📊 Daily owner report — {target_date.isoformat()}\n"
        f"Orders: {z['delivered_order_count']} delivered / {z['order_count']} total\n"
        f"Gross sales: AED {z['gross_sales_aed']}\n"
        f"Discounts: AED {z['total_discounts_aed']}\n"
        f"COD collected: AED {z['cod_collected_aed']}\n"
        f"AOV: AED {aov['aov_aed']}\n"
        f"Avg delivery: {delivery['avg_delivery_minutes'] or 'n/a'} min "
        f"(late {delivery['late_pct']}%)\n"
        f"Top items: "
        + (
            ", ".join(f"{t['dish_name']}({t['order_count']})" for t in top)
            if top
            else "—"
        )
        + "\nChannels: "
        + (
            ", ".join(f"{c['channel']}={c['order_count']}" for c in channels[:5])
            if channels
            else "—"
        )
    )
    return {
        "date": target_date.isoformat(),
        "text": text,
        "z_report": {
            "gross_sales_aed": str(z["gross_sales_aed"]),
            "order_count": z["order_count"],
            "delivered_order_count": z["delivered_order_count"],
            "total_discounts_aed": str(z["total_discounts_aed"]),
            "cod_collected_aed": str(z["cod_collected_aed"]),
        },
        "aov_aed": aov["aov_aed"],
        "avg_delivery_minutes": delivery["avg_delivery_minutes"],
        "channels": channels,
        "top_items": top,
    }


async def send_owner_whatsapp_report(
    session: AsyncSession,
    *,
    restaurant,
    target_date: date | None = None,
    to_phone: str | None = None,
) -> dict:
    """Compose daily summary and send via WhatsApp port (mock or cloud)."""
    from app.reports.models import OwnerReportDelivery
    from app.whatsapp.factory import get_whatsapp_provider
    from app.whatsapp.port import OutboundMessage, OutboundMessageType

    day = target_date or date.today()
    summary = await build_owner_daily_summary(
        session, restaurant_id=restaurant.id, target_date=day
    )
    phone = (
        to_phone
        or (restaurant.settings or {}).get("owner_whatsapp")
        or (restaurant.settings or {}).get("owner_phone")
        or restaurant.phone
    )
    if not phone:
        raise ValueError("no owner phone configured (settings.owner_whatsapp or restaurant.phone)")

    provider = get_whatsapp_provider()
    try:
        msg = OutboundMessage(
            to_phone=str(phone),
            type=OutboundMessageType.TEXT,
            payload={"body": summary["text"]},
            idempotency_key=f"owner-report-{restaurant.id}-{day.isoformat()}",
        )
        await provider.send(msg)
        status = "sent"
        error = None
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error = str(exc)

    row = OwnerReportDelivery(
        restaurant_id=restaurant.id,
        target_date=day,
        to_phone=str(phone),
        status=status,
        body_preview=summary["text"][:500],
        error=error,
    )
    session.add(row)
    await session.flush()
    return {
        "id": row.id,
        "status": status,
        "to_phone": str(phone),
        "error": error,
        "preview": summary["text"],
        "date": day.isoformat(),
    }
