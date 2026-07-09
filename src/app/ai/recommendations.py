"""AI upsell, combo, and best-bundle suggestions."""

from __future__ import annotations

from collections import Counter
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiInsight
from app.ai.text_gen import generate_narrative
from app.menu.upsell import compute_co_purchase_scores


async def ai_upsell(
    session: AsyncSession,
    *,
    restaurant_id: int,
    dish_ids: list[int],
    limit: int = 5,
) -> dict:
    """Market-basket upsell + AI narrative per suggestion."""
    base = await compute_co_purchase_scores(
        session, restaurant_id=restaurant_id, dish_ids=dish_ids, limit=limit
    )
    enriched = []
    for row in base:
        facts = {
            "trigger": ",".join(str(d) for d in dish_ids),
            "suggest": row.get("dish_name"),
            "reason": row.get("message")
            or f"co-occurrence {row.get('co_occurrence_count')}",
            "source": row.get("source"),
        }
        narrative = await generate_narrative("upsell", facts)
        enriched.append({**row, "ai_message": narrative})
    return {"dish_ids": dish_ids, "suggestions": enriched}


async def ai_combo_suggestions(
    session: AsyncSession, *, restaurant_id: int, limit: int = 5
) -> dict:
    """Frequent itemsets (pairs) from recent orders + AI copy."""
    from app.ordering.models import Order, OrderItem

    orders = list(
        (
            await session.scalars(
                select(Order)
                .where(
                    Order.restaurant_id == restaurant_id,
                    Order.status.notin_(["draft", "cancelled"]),
                )
                .order_by(Order.id.desc())
                .limit(500)
            )
        ).all()
    )
    pair_counts: Counter[tuple[str, str]] = Counter()
    for o in orders:
        items = list(
            (
                await session.scalars(
                    select(OrderItem).where(
                        OrderItem.order_id == o.id, OrderItem.cancelled.is_(False)
                    )
                )
            ).all()
        )
        names = sorted({it.dish_name for it in items})
        for a, b in combinations(names, 2):
            pair_counts[(a, b)] += 1
    combos = []
    for (a, b), cnt in pair_counts.most_common(limit):
        facts = {
            "bundle": f"{a} + {b}",
            "reason": f"Ordered together {cnt} times recently.",
            "count": cnt,
        }
        narrative = await generate_narrative("combo", facts)
        combos.append(
            {
                "items": [a, b],
                "co_occurrence_count": cnt,
                "ai_message": narrative,
                "source": "co_purchase",
            }
        )
    return {"combos": combos}


async def best_menu_bundles(
    session: AsyncSession, *, restaurant_id: int, limit: int = 5
) -> AiInsight:
    """Persist top multi-item bundles as an AI insight."""
    combos = await ai_combo_suggestions(session, restaurant_id=restaurant_id, limit=limit)
    # Also include configured combos from menu if present
    configured = []
    try:
        from app.menu.combos import Combo

        rows = list(
            (
                await session.scalars(
                    select(Combo).where(Combo.restaurant_id == restaurant_id)
                )
            ).all()
        )
        for c in rows[:limit]:
            configured.append(
                {
                    "name": getattr(c, "name", None) or f"combo-{c.id}",
                    "id": c.id,
                    "source": "menu_combo",
                }
            )
    except Exception:  # noqa: BLE001
        configured = []
    payload = {"statistical": combos["combos"], "configured": configured}
    top = combos["combos"][0]["ai_message"] if combos["combos"] else "No strong bundles yet."
    row = AiInsight(
        restaurant_id=restaurant_id,
        kind="menu_bundle",
        title="Best menu bundles",
        summary=top,
        payload=payload,
    )
    session.add(row)
    await session.flush()
    return row
