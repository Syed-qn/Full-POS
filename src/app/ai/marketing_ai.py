"""AI marketing copy: reorder, abandoned recovery, segments, festival campaigns."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiInsight
from app.ai.text_gen import generate_narrative
from app.marketing.rfm import RFM_SEGMENTS, _classify, _rows


async def reorder_prompt_copy(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int | None = None,
) -> dict:
    habit_dish = None
    if customer_id:
        try:
            from sqlalchemy import select

            from app.ordering.models import Customer, Order, OrderItem

            # Prefer most-ordered dish for this customer as reorder hook.
            cust = await session.get(Customer, customer_id)
            if cust is not None and cust.restaurant_id == restaurant_id:
                order_ids = list(
                    (
                        await session.scalars(
                            select(Order.id).where(
                                Order.customer_id == customer_id,
                                Order.restaurant_id == restaurant_id,
                                Order.status.notin_(["draft", "cancelled"]),
                            )
                        )
                    ).all()
                )
                if order_ids:
                    from collections import Counter

                    items = list(
                        (
                            await session.scalars(
                                select(OrderItem).where(OrderItem.order_id.in_(order_ids))
                            )
                        ).all()
                    )
                    counts: Counter[str] = Counter()
                    for it in items:
                        if not it.cancelled:
                            counts[it.dish_name] += int(it.qty or 0)
                    if counts:
                        habit_dish = counts.most_common(1)[0][0]
        except Exception:  # noqa: BLE001
            habit_dish = None
    body = await generate_narrative("reorder", {"habit_dish": habit_dish})
    return {
        "kind": "reorder_prompt",
        "body": body,
        "habit_dish": habit_dish,
        "customer_id": customer_id,
    }


async def abandoned_recovery_copy(
    *, cart_summary: str | None = None
) -> dict:
    body = await generate_narrative("abandoned", {"cart": cart_summary or "your items"})
    return {"kind": "abandoned_recovery", "body": body}


async def segment_insights(session: AsyncSession, *, restaurant_id: int) -> AiInsight:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    rows = await _rows(session, restaurant_id)
    counts: dict[str, int] = {k: 0 for k, _ in RFM_SEGMENTS if k != "all"}
    for _cid, total_orders, last_at in rows:
        key = _classify(total_orders=total_orders, last_order_at=last_at, now=now)
        counts[key] = counts.get(key, 0) + 1
    playbooks = {
        "champions": "Exclusive VIP drop + early access to new dishes.",
        "loyal": "Loyalty points double-day.",
        "potential": "Combo upsell to raise frequency.",
        "at_risk": "Win-back coupon within 48h.",
        "lost": "Aggressive reactivation with free delivery.",
        "new": "Welcome offer + guided reorder.",
    }
    segments = []
    for key, label in RFM_SEGMENTS:
        if key == "all":
            continue
        facts = {
            "key": label,
            "count": counts.get(key, 0),
            "playbook": playbooks.get(key),
        }
        narrative = await generate_narrative("segment_label", facts)
        segments.append(
            {
                "key": key,
                "label": label,
                "count": counts.get(key, 0),
                "ai_playbook": narrative,
            }
        )
    summary = "; ".join(f"{s['label']}:{s['count']}" for s in segments)
    row = AiInsight(
        restaurant_id=restaurant_id,
        kind="segmentation",
        title="AI customer segmentation",
        summary=summary,
        payload={"segments": segments},
    )
    session.add(row)
    await session.flush()
    return row


async def festival_campaign(
    session: AsyncSession,
    *,
    restaurant_id: int,
    festival: str,
    offer: str | None = None,
) -> AiInsight:
    festival = (festival or "Festival").strip()
    facts = {
        "festival": festival,
        "offer": offer or f"special {festival} set menu",
        "hook": f"Celebrate {festival} with us!",
    }
    summary = await generate_narrative("festival", facts)
    # Also draft promo template body via marketing copywriter fallback path
    promo_body = await generate_narrative(
        "promotion", {"describe": f"{festival}: {facts['offer']}"}
    )
    row = AiInsight(
        restaurant_id=restaurant_id,
        kind="festival_campaign",
        title=f"Festival campaign · {festival}",
        summary=summary,
        payload={
            "festival": festival,
            "offer": facts["offer"],
            "whatsapp_body": promo_body,
            "channels": ["whatsapp", "dashboard"],
        },
    )
    session.add(row)
    await session.flush()
    return row
