"""Upsell / combo-suggestion engine — market-basket co-purchase ranking.

Deterministic, statistics-only recommendation over this restaurant's own order
history: "customers who ordered X also ordered Y". No ML/LLM vendor call — same
style precedent as ``app.predictions`` (statistical demand forecasting with no
external AI dependency).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.models import Dish
from app.ordering.models import Order, OrderItem

# Statuses that count as "a real order happened" — mirrors
# app.predictions.service._DEMAND_STATUSES: excludes cancelled/draft noise.
_REAL_ORDER_STATUSES = ("confirmed", "ready", "assigned", "out_for_delivery", "delivered")


async def compute_co_purchase_scores(
    session: AsyncSession,
    *,
    restaurant_id: int,
    dish_ids: list[int],
    limit: int = 3,
) -> list[dict]:
    """Rank dishes most frequently co-ordered with ``dish_ids`` historically.

    Finds every real order (for this restaurant) that contained at least one of
    ``dish_ids``, counts how often each OTHER dish appeared alongside it, and
    returns the top ``limit`` ranked descending by co-occurrence count. Dishes
    already in the cart and unavailable dishes are excluded. Cold start (no
    matching order history) returns an empty list — never a fabricated fallback.
    """
    if not dish_ids:
        return []

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
    dish_by_id = {d.id: d for d in available_dishes}

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
