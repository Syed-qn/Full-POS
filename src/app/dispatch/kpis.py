"""Dispatch KPI aggregation for manager dashboard (spec §2, Phase 5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.models import Assignment, BatchOrder
from app.ordering.models import Order


async def compute_dispatch_kpis(
    session: AsyncSession,
    *,
    restaurant_id: int,
    window_hours: int = 24,
) -> dict:
    """Return batch rate, avg stops, engine fallback %, avg delivery minutes."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)

    # Fleet average delivery time (always computed even with no assignments).
    delivered = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status == "delivered",
                    Order.delivered_at.is_not(None),
                    Order.delivered_at >= since,
                    Order.sla_confirmed_at.is_not(None),
                )
            )
        ).all()
    )
    durations = [
        (o.delivered_at - o.sla_confirmed_at).total_seconds() / 60.0
        for o in delivered
        if o.delivered_at and o.sla_confirmed_at
    ]
    avg_delivery_minutes = (
        round(sum(durations) / len(durations), 2) if durations else None
    )

    assignments = list(
        (
            await session.scalars(
                select(Assignment)
                .join(Order, Assignment.order_id == Order.id)
                .where(
                    Order.restaurant_id == restaurant_id,
                    Assignment.assigned_at >= since,
                )
            )
        ).all()
    )

    if not assignments:
        return {
            "batch_rate_pct": 0.0,
            "avg_stops": 0.0,
            "engine_fallback_pct": 0.0,
            "avg_delivery_minutes": avg_delivery_minutes,
            "delivered_count": len(delivered),
            "window": "today",
        }

    batch_ids = {a.batch_id for a in assignments if a.batch_id}
    batch_sizes: dict[int, int] = {}
    if batch_ids:
        rows = (
            await session.execute(
                select(BatchOrder.batch_id, func.count())
                .where(BatchOrder.batch_id.in_(batch_ids))
                .group_by(BatchOrder.batch_id)
            )
        ).all()
        batch_sizes = {int(bid): int(cnt) for bid, cnt in rows}

    multi_stop_assignments = sum(
        1 for a in assignments if batch_sizes.get(a.batch_id or -1, 1) >= 2
    )
    batch_rate_pct = round((multi_stop_assignments / len(assignments)) * 100.0, 1)

    multi_sizes = [s for s in batch_sizes.values() if s >= 2]
    avg_stops = round(sum(multi_sizes) / len(multi_sizes), 2) if multi_sizes else 0.0

    fallback_count = sum(
        1
        for a in assignments
        if isinstance(a.algorithm_score, dict)
        and a.algorithm_score.get("engine_fallback") is True
    )
    engine_fallback_pct = round((fallback_count / len(assignments)) * 100.0, 1)

    return {
        "batch_rate_pct": batch_rate_pct,
        "avg_stops": avg_stops,
        "engine_fallback_pct": engine_fallback_pct,
        "avg_delivery_minutes": avg_delivery_minutes,
        "delivered_count": len(delivered),
        "window": "today",
    }
