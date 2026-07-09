"""Upsell / combo-suggestion engine — market-basket co-purchase ranking.

Deterministic, statistics-only recommendation over this restaurant's own order
history: "customers who ordered X also ordered Y". No ML/LLM vendor call — same
style precedent as ``app.predictions`` (statistical demand forecasting with no
external AI dependency).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.models import Dish
from app.menu.service import is_dish_currently_available
from app.ordering.models import Order, OrderItem

# Statuses that count as "a real order happened" — mirrors
# app.predictions.service._DEMAND_STATUSES: excludes cancelled/draft noise.
_REAL_ORDER_STATUSES = ("confirmed", "ready", "assigned", "out_for_delivery", "delivered")


async def _configured_sell_rules(
    session: AsyncSession,
    *,
    restaurant_id: int,
    dish_ids: list[int],
    limit: int,
) -> list[dict]:
    """Manager-configured upsell/cross-sell rules (MenuSellRule), preferred over
    market-basket stats when present."""
    from datetime import date

    from app.menu.models import MenuSellRule

    cart = set(dish_ids)
    rules = (
        await session.scalars(
            select(MenuSellRule)
            .where(
                MenuSellRule.restaurant_id == restaurant_id,
                MenuSellRule.is_active.is_(True),
            )
            .order_by(MenuSellRule.sort_order, MenuSellRule.id)
        )
    ).all()
    if not rules:
        return []
    cart_dishes = (
        await session.scalars(select(Dish).where(Dish.id.in_(dish_ids)))
    ).all() if dish_ids else []
    cart_cats = {d.category for d in cart_dishes if d.category}
    out: list[dict] = []
    seen: set[int] = set()
    today = date.today()
    for rule in rules:
        if rule.suggest_dish_id in cart or rule.suggest_dish_id in seen:
            continue
        fires = False
        if rule.trigger_dish_id is not None and rule.trigger_dish_id in cart:
            fires = True
        if rule.trigger_category and rule.trigger_category in cart_cats:
            fires = True
        if not fires:
            continue
        dish = await session.get(Dish, rule.suggest_dish_id)
        if dish is None or not is_dish_currently_available(dish, today=today):
            continue
        seen.add(dish.id)
        out.append(
            {
                "dish_id": dish.id,
                "dish_name": dish.name,
                "price_aed": str(dish.price_aed) if dish.price_aed is not None else None,
                "co_occurrence_count": None,
                "source": rule.rule_kind,
                "message": rule.message,
            }
        )
        if len(out) >= limit:
            break
    return out


async def compute_co_purchase_scores(
    session: AsyncSession,
    *,
    restaurant_id: int,
    dish_ids: list[int],
    limit: int = 3,
) -> list[dict]:
    """Rank dishes most frequently co-ordered with ``dish_ids`` historically.

    Prefers manager-configured MenuSellRule rows (upsell/cross_sell). Falls back
    to market-basket co-purchase stats. Cold start returns empty list.
    """
    if not dish_ids:
        return []

    configured = await _configured_sell_rules(
        session, restaurant_id=restaurant_id, dish_ids=dish_ids, limit=limit
    )
    if configured:
        return configured

    cart_dish_ids = set(dish_ids)

    # Orders (for this restaurant, "real" statuses) that contained any cart dish.
    seed_orders_subq = (
        select(OrderItem.order_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status.in_(_REAL_ORDER_STATUSES),
            OrderItem.dish_id.in_(dish_ids),
        )
        .distinct()
        .subquery()
    )

    if not (await session.scalars(select(seed_orders_subq.c.order_id).limit(1))).first():
        return []

    count_col = func.count(OrderItem.id).label("co_occurrence_count")
    rows = (
        await session.execute(
            select(OrderItem.dish_id, count_col)
            .join(seed_orders_subq, seed_orders_subq.c.order_id == OrderItem.order_id)
            .where(OrderItem.dish_id.notin_(dish_ids))
            .group_by(OrderItem.dish_id)
            .order_by(count_col.desc())
        )
    ).all()

    if not rows:
        return []

    candidate_ids = [dish_id for dish_id, _ in rows]
    available_dishes = (
        await session.scalars(
            select(Dish).where(
                Dish.id.in_(candidate_ids),
                Dish.restaurant_id == restaurant_id,
                Dish.is_available.is_(True),
            )
        )
    ).all()
    today = datetime.now(timezone.utc).date()
    dish_by_id = {
        d.id: d for d in available_dishes if is_dish_currently_available(d, today=today)
    }

    results: list[dict] = []
    for dish_id, count in rows:
        dish = dish_by_id.get(dish_id)
        if dish is None or dish_id in cart_dish_ids:
            continue
        results.append({
            "dish_id": dish_id,
            "dish_name": dish.name,
            "co_occurrence_count": count,
        })
        if len(results) >= limit:
            break

    return results
