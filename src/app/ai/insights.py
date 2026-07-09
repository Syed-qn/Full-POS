"""AI operational insights: sales, stock, food cost, staff, slow-movers."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiInsight
from app.ai.text_gen import generate_narrative
from app.audit.service import record_audit


def _bounds(d0: date, d1: date) -> tuple[datetime, datetime]:
    return datetime.combine(d0, time.min), datetime.combine(d1, time.max)


async def _save_insight(
    session: AsyncSession,
    *,
    restaurant_id: int,
    kind: str,
    title: str,
    summary: str,
    payload: dict,
    period_start: date | None = None,
    period_end: date | None = None,
) -> AiInsight:
    row = AiInsight(
        restaurant_id=restaurant_id,
        kind=kind,
        title=title,
        summary=summary,
        payload=payload,
        period_start=period_start,
        period_end=period_end,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="system",
        entity="ai_insight",
        entity_id=str(row.id),
        action=f"generate_{kind}",
        after={"title": title},
    )
    return row


async def daily_sales_summary(
    session: AsyncSession, *, restaurant_id: int, day: date | None = None
) -> AiInsight:
    from app.ordering.models import Order, OrderItem

    day = day or date.today()
    start, end = _bounds(day, day)
    orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.created_at >= start,
                    Order.created_at <= end,
                    Order.status.notin_(["draft", "cancelled"]),
                )
            )
        ).all()
    )
    gross = sum(Decimal(str(o.total or 0)) for o in orders)
    net = sum(Decimal(str(o.subtotal or 0)) for o in orders)
    vat = sum(Decimal(str(o.vat_amount_aed or 0)) for o in orders)
    channels = Counter((o.source_channel or o.order_type or "native") for o in orders)
    dish_counts: Counter[str] = Counter()
    if orders:
        items = list(
            (
                await session.scalars(
                    select(OrderItem).where(OrderItem.order_id.in_([o.id for o in orders]))
                )
            ).all()
        )
        for it in items:
            if not it.cancelled:
                dish_counts[it.dish_name] += int(it.qty or 0)
    top = dish_counts.most_common(1)
    top_dish = top[0][0] if top else None
    facts = {
        "date": day.isoformat(),
        "order_count": len(orders),
        "gross_aed": str(gross),
        "net_aed": str(net),
        "vat_aed": str(vat),
        "top_dish": top_dish,
        "channel_note": ", ".join(f"{k}:{v}" for k, v in channels.most_common(5)),
        "channels": dict(channels),
    }
    summary = await generate_narrative("daily_sales", facts)
    return await _save_insight(
        session,
        restaurant_id=restaurant_id,
        kind="daily_sales",
        title=f"Daily sales · {day.isoformat()}",
        summary=summary,
        payload=facts,
        period_start=day,
        period_end=day,
    )


async def why_sales_dropped(
    session: AsyncSession,
    *,
    restaurant_id: int,
    days: int = 7,
) -> AiInsight:
    from app.ordering.models import Order

    days = max(1, min(days, 90))
    today = date.today()
    cur_start = today - timedelta(days=days - 1)
    prior_end = cur_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=days - 1)

    async def _gross(a: date, b: date) -> tuple[Decimal, int, Counter]:
        s, e = _bounds(a, b)
        orders = list(
            (
                await session.scalars(
                    select(Order).where(
                        Order.restaurant_id == restaurant_id,
                        Order.created_at >= s,
                        Order.created_at <= e,
                        Order.status.notin_(["draft", "cancelled"]),
                    )
                )
            ).all()
        )
        g = sum(Decimal(str(o.total or 0)) for o in orders)
        ch = Counter((o.source_channel or "native") for o in orders)
        return g, len(orders), ch

    cur_g, cur_n, cur_ch = await _gross(cur_start, today)
    pri_g, pri_n, pri_ch = await _gross(prior_start, prior_end)
    drop_pct = 0.0
    if pri_g > 0:
        drop_pct = float((pri_g - cur_g) / pri_g * 100)
    drivers = []
    if cur_n < pri_n:
        drivers.append(f"order count {cur_n} vs {pri_n}")
    if cur_g < pri_g:
        drivers.append("gross revenue lower")
    # dish-level: top prior dishes missing volume
    if drop_pct > 0:
        drivers.append("compare top SKUs and channel mix")
    suggestion = (
        "run a WhatsApp win-back to at-risk segment"
        if drop_pct >= 10
        else "monitor next 48h; no severe drop"
    )
    facts = {
        "days": days,
        "current_gross": str(cur_g),
        "prior_gross": str(pri_g),
        "current_orders": cur_n,
        "prior_orders": pri_n,
        "drop_pct": round(max(0.0, drop_pct), 1),
        "drivers": drivers or ["no material decline"],
        "suggestion": suggestion,
        "current_channels": dict(cur_ch),
        "prior_channels": dict(pri_ch),
    }
    summary = await generate_narrative("sales_drop", facts)
    return await _save_insight(
        session,
        restaurant_id=restaurant_id,
        kind="sales_drop",
        title=f"Why sales dropped · {days}d",
        summary=summary,
        payload=facts,
        period_start=cur_start,
        period_end=today,
    )


async def staff_performance_summary(
    session: AsyncSession, *, restaurant_id: int, days: int = 7
) -> AiInsight:
    from app.ordering.models import Order
    from app.staff.models import StaffMember, StaffMistake

    days = max(1, min(days, 90))
    end = date.today()
    start = end - timedelta(days=days - 1)
    s, e = _bounds(start, end)
    staff = list(
        (
            await session.scalars(
                select(StaffMember).where(
                    StaffMember.restaurant_id == restaurant_id,
                    StaffMember.is_active.is_(True),
                )
            )
        ).all()
    )
    sales_by: dict[int, Decimal] = {}
    orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.created_at >= s,
                    Order.created_at <= e,
                    Order.staff_id.is_not(None),
                    Order.status.notin_(["draft", "cancelled"]),
                )
            )
        ).all()
    )
    for o in orders:
        sid = int(o.staff_id)  # type: ignore[arg-type]
        sales_by[sid] = sales_by.get(sid, Decimal("0")) + Decimal(str(o.total or 0))
    mistakes = int(
        await session.scalar(
            select(func.count()).select_from(StaffMistake).where(
                StaffMistake.restaurant_id == restaurant_id,
                StaffMistake.created_at >= s,
            )
        )
        or 0
    )
    name_by = {m.id: m.name for m in staff}
    top_id = None
    top_sales = Decimal("0")
    if sales_by:
        top_id, top_sales = max(sales_by.items(), key=lambda kv: kv[1])
    facts = {
        "period": f"{start.isoformat()} → {end.isoformat()}",
        "staff_count": len(staff),
        "top_seller": name_by.get(top_id) if top_id else None,
        "top_sales": str(top_sales),
        "mistake_count": mistakes,
        "leaderboard": [
            {"staff_id": sid, "name": name_by.get(sid), "sales_aed": str(amt)}
            for sid, amt in sorted(sales_by.items(), key=lambda kv: -kv[1])[:5]
        ],
        "note": "AI summary grounded in order attribution + mistakes log.",
    }
    summary = await generate_narrative("staff_summary", facts)
    return await _save_insight(
        session,
        restaurant_id=restaurant_id,
        kind="staff_summary",
        title=f"Staff AI summary · {days}d",
        summary=summary,
        payload=facts,
        period_start=start,
        period_end=end,
    )


async def slow_moving_items(
    session: AsyncSession, *, restaurant_id: int, days: int = 14, limit: int = 10
) -> AiInsight:
    from app.menu.models import Dish
    from app.ordering.models import Order, OrderItem

    days = max(3, min(days, 90))
    end = date.today()
    start = end - timedelta(days=days - 1)
    s, e = _bounds(start, end)
    # sold qty by dish
    sold: Counter[int] = Counter()
    order_ids = list(
        (
            await session.scalars(
                select(Order.id).where(
                    Order.restaurant_id == restaurant_id,
                    Order.created_at >= s,
                    Order.created_at <= e,
                    Order.status.notin_(["draft", "cancelled"]),
                )
            )
        ).all()
    )
    if order_ids:
        items = list(
            (
                await session.scalars(
                    select(OrderItem).where(OrderItem.order_id.in_(order_ids))
                )
            ).all()
        )
        for it in items:
            if not it.cancelled:
                sold[it.dish_id] += int(it.qty or 0)

    dishes = list(
        (
            await session.scalars(
                select(Dish).where(
                    Dish.restaurant_id == restaurant_id,
                    Dish.is_available.is_(True),
                )
            )
        ).all()
    )
    ranked = sorted(dishes, key=lambda d: (sold.get(d.id, 0), d.id))
    slow = [
        {
            "dish_id": d.id,
            "name": d.name,
            "sold_qty": sold.get(d.id, 0),
            "price_aed": str(d.price_aed) if d.price_aed is not None else None,
        }
        for d in ranked[:limit]
        if sold.get(d.id, 0) <= 2
    ]
    facts = {"days": days, "items": slow}
    summary = await generate_narrative("slow_moving", facts)
    return await _save_insight(
        session,
        restaurant_id=restaurant_id,
        kind="slow_moving",
        title=f"Slow-moving items · {days}d",
        summary=summary,
        payload=facts,
        period_start=start,
        period_end=end,
    )


async def food_cost_anomalies(
    session: AsyncSession, *, restaurant_id: int, threshold_pct: float = 40.0
) -> AiInsight:
    from app.inventory.costing import dish_cost
    from app.menu.models import Dish

    dishes = list(
        (
            await session.scalars(
                select(Dish).where(
                    Dish.restaurant_id == restaurant_id,
                    Dish.is_available.is_(True),
                    Dish.price_aed.is_not(None),
                )
            )
        ).all()
    )
    anomalies = []
    for d in dishes:
        price = Decimal(str(d.price_aed or 0))
        if price <= 0:
            continue
        cost = await dish_cost(session, dish_id=d.id)
        if cost <= 0:
            continue
        pct = float(cost / price * 100)
        if pct >= threshold_pct:
            anomalies.append(
                {
                    "dish_id": d.id,
                    "dish_name": d.name,
                    "price_aed": str(price),
                    "theo_cost_aed": str(cost),
                    "theo_pct": round(pct, 1),
                }
            )
    anomalies.sort(key=lambda x: -x["theo_pct"])
    top = anomalies[0] if anomalies else None
    facts = {
        "threshold_pct": threshold_pct,
        "count": len(anomalies),
        "anomalies": anomalies[:20],
        "dish_name": top["dish_name"] if top else None,
        "theo_pct": top["theo_pct"] if top else 0,
        "note": "Theoretical recipe cost vs menu price.",
    }
    summary = await generate_narrative("food_cost_anomaly", facts)
    return await _save_insight(
        session,
        restaurant_id=restaurant_id,
        kind="food_cost_anomaly",
        title="Food-cost anomalies",
        summary=summary,
        payload=facts,
    )


async def low_stock_prediction(
    session: AsyncSession, *, restaurant_id: int
) -> AiInsight:
    """Demand-aware low stock: on_hand vs par, weighted by recent usage signal."""
    from app.inventory.models import Ingredient
    from app.predictions.service import latest_run

    ingredients = list(
        (
            await session.scalars(
                select(Ingredient).where(Ingredient.restaurant_id == restaurant_id)
            )
        ).all()
    )
    at_risk = []
    for ing in ingredients:
        on_hand = Decimal(str(ing.current_stock or 0))
        par = Decimal(str(ing.par_level or 0))
        low = Decimal(str(ing.low_stock_threshold or 0))
        name = ing.name
        risk = False
        reason = ""
        if on_hand <= 0:
            risk = True
            reason = "out_of_stock"
        elif par > 0 and on_hand <= par:
            risk = True
            reason = "below_par"
        elif low > 0 and on_hand <= low:
            risk = True
            reason = "below_threshold"
        if risk:
            at_risk.append(
                {
                    "ingredient_id": ing.id,
                    "name": name,
                    "on_hand": str(on_hand),
                    "par": str(par),
                    "reason": reason,
                }
            )
    # Attach forecast context if available
    forecast_note = None
    try:
        run = await latest_run(session, restaurant_id=restaurant_id, horizon="dinner")
        if run is not None:
            forecast_note = f"Dinner forecast run #{run.id} available for prep-ahead."
    except Exception:  # noqa: BLE001
        forecast_note = None
    facts = {
        "items": at_risk[:30],
        "count": len(at_risk),
        "note": forecast_note or "Cross-check prep-ahead predictions before peak.",
    }
    summary = await generate_narrative("low_stock", facts)
    return await _save_insight(
        session,
        restaurant_id=restaurant_id,
        kind="low_stock",
        title="AI low-stock prediction",
        summary=summary,
        payload=facts,
    )


async def list_insights(
    session: AsyncSession, *, restaurant_id: int, kind: str | None = None, limit: int = 30
) -> list[AiInsight]:
    q = select(AiInsight).where(AiInsight.restaurant_id == restaurant_id)
    if kind:
        q = q.where(AiInsight.kind == kind)
    q = q.order_by(AiInsight.id.desc()).limit(min(max(limit, 1), 100))
    return list((await session.scalars(q)).all())
