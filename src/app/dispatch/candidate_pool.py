"""Dispatch candidate pool — ready orders plus prep-near orders (spec §5.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.batching import OrderCandidate
from app.ordering.fsm import OrderStatus
from app.ordering.models import Order


@dataclass
class CandidatePoolResult:
    candidates: list[OrderCandidate]
    orders_by_id: dict[int, Order]
    skipped_no_geo: list[Order]


def _minutes_since_sla(order: Order, now: datetime) -> float:
    if order.sla_confirmed_at is None:
        return 0.0
    sla = order.sla_confirmed_at
    if sla.tzinfo is None:
        sla = sla.replace(tzinfo=timezone.utc)
    return max(0.0, (now - sla).total_seconds() / 60.0)


async def build_order_candidates(
    session: AsyncSession,
    restaurant_id: int,
    *,
    prep_lead_min: int,
    now: datetime,
    dropoff_coords: dict[int, tuple[float, float]],
) -> CandidatePoolResult:
    """Load unassigned dispatch candidates: ``ready`` always; ``preparing`` when
    ``prep_deadline - now <= prep_lead_min`` (default 8 min). Geocoded drop-offs only.
    """
    orders = (
        await session.scalars(
            select(Order)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.rider_id.is_(None),
                Order.status.in_(
                    (str(OrderStatus.READY), str(OrderStatus.PREPARING))
                ),
            )
            .order_by(Order.id)
        )
    ).all()

    candidates: list[OrderCandidate] = []
    orders_by_id: dict[int, Order] = {}
    skipped_no_geo: list[Order] = []

    for o in orders:
        if o.status == str(OrderStatus.PREPARING):
            if o.prep_deadline is None:
                continue
            deadline = o.prep_deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            minutes_to_prep = (deadline - now).total_seconds() / 60.0
            if minutes_to_prep > prep_lead_min:
                continue

        coords = dropoff_coords.get(o.id)
        if coords is None:
            skipped_no_geo.append(o)
            continue

        lat, lon = coords
        ready_at = o.updated_at or now
        if ready_at.tzinfo is None:
            ready_at = ready_at.replace(tzinfo=timezone.utc)
        candidates.append(
            OrderCandidate(
                order_id=o.id,
                lat=lat,
                lon=lon,
                ready_at=ready_at,
                minutes_elapsed=_minutes_since_sla(o, now),
                priority=o.priority or "normal",
            )
        )
        orders_by_id[o.id] = o

    return CandidatePoolResult(
        candidates=candidates,
        orders_by_id=orders_by_id,
        skipped_no_geo=skipped_no_geo,
    )