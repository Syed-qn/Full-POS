"""Live ops map payload — batch polylines and SLA rings (spec §7 Phase 5)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Order

_BATCH_COLORS = ("#0ea5e9", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#6366f1")


def _urgency(minutes_remaining: float) -> str:
    if minutes_remaining <= 5:
        return "critical"
    if minutes_remaining <= 15:
        return "warn"
    return "safe"


async def build_live_ops_map(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
) -> dict:
    """Assemble restaurant origin, active batch routes, and SLA pressure rings."""
    now = datetime.now(timezone.utc)
    origin = {
        "lat": restaurant.lat,
        "lng": restaurant.lng,
        "name": restaurant.name,
    }

    active_statuses = ("planned", "picked_up", "in_progress")
    batches = list(
        (
            await session.scalars(
                select(Batch)
                .where(
                    Batch.restaurant_id == restaurant.id,
                    Batch.status.in_(active_statuses),
                )
                .order_by(Batch.id)
            )
        ).all()
    )

    batch_out: list[dict] = []
    for idx, batch in enumerate(batches):
        bo_rows = list(
            (
                await session.scalars(
                    select(BatchOrder)
                    .where(BatchOrder.batch_id == batch.id)
                    .order_by(BatchOrder.sequence)
                )
            ).all()
        )
        order_ids = [bo.order_id for bo in bo_rows]
        orders = (
            list(
                (
                    await session.scalars(
                        select(Order).where(Order.id.in_(order_ids))
                    )
                ).all()
            )
            if order_ids
            else []
        )
        orders_by_id = {o.id: o for o in orders}
        route = batch.route or {}
        stops_raw = route.get("stops") or []

        stops: list[dict] = []
        polyline: list[list[float]] = [[restaurant.lat, restaurant.lng]]
        for bo in bo_rows:
            o = orders_by_id.get(bo.order_id)
            if o is None:
                continue
            stop = next(
                (s for s in stops_raw if s.get("order_id") == o.id),
                {},
            )
            lat = stop.get("lat")
            lon = stop.get("lon")
            if lat is None or lon is None:
                if o.address_id:
                    from app.ordering.models import CustomerAddress

                    addr = await session.get(CustomerAddress, o.address_id)
                    if addr and addr.latitude is not None:
                        lat, lon = addr.latitude, addr.longitude
            if lat is None or lon is None:
                continue
            stops.append(
                {
                    "order_id": o.id,
                    "order_number": o.order_number,
                    "sequence": bo.sequence,
                    "lat": lat,
                    "lng": lon,
                    "sla_deadline": o.sla_deadline.isoformat()
                    if o.sla_deadline
                    else None,
                }
            )
            polyline.append([lat, lon])

        rider_name = None
        if batch.rider_id:
            rider = await session.get(Rider, batch.rider_id)
            rider_name = rider.name if rider else None

        if len(stops) >= 1:
            batch_out.append(
                {
                    "batch_id": batch.id,
                    "rider_id": batch.rider_id,
                    "rider_name": rider_name,
                    "status": batch.status,
                    "color": _BATCH_COLORS[idx % len(_BATCH_COLORS)],
                    "stops": stops,
                    "polyline": polyline,
                    "total_est_min": batch.total_est_min,
                }
            )

    active_orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant.id,
                    Order.status.in_(
                        ("ready", "assigned", "picked_up", "arriving")
                    ),
                )
            )
        ).all()
    )

    sla_rings: list[dict] = []
    for o in active_orders:
        if o.address_id is None:
            continue
        from app.ordering.models import CustomerAddress

        addr = await session.get(CustomerAddress, o.address_id)
        if (
            addr is None
            or addr.latitude is None
            or addr.longitude is None
        ):
            continue
        deadline = o.sla_deadline
        if deadline is None:
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        minutes_remaining = max(
            0.0, (deadline - now).total_seconds() / 60.0
        )
        sla_rings.append(
            {
                "order_id": o.id,
                "order_number": o.order_number,
                "lat": addr.latitude,
                "lng": addr.longitude,
                "sla_deadline": deadline.isoformat(),
                "minutes_remaining": round(minutes_remaining, 1),
                "urgency": _urgency(minutes_remaining),
                "radius_km": round(
                    min(3.0, max(0.4, minutes_remaining * 0.06)), 2
                ),
            }
        )

    return {
        "origin": origin,
        "batches": batch_out,
        "sla_rings": sla_rings,
    }