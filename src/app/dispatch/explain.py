"""Build rich ``assignments.algorithm_score`` explainability payloads (spec §5.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.dispatch.batching import (
    OrderCandidate,
    PlannedBatch,
    _compute_route_time_to_stops,
    compute_batch_total_est_min,
)
from app.dispatch.zones import zone_for_point

if TYPE_CHECKING:
    from app.geo.port import GeoPort


def _infer_batch_reason(
    seq_orders: list[OrderCandidate],
    *,
    corridor: bool,
    delivery_zones: list[dict] | None = None,
) -> str:
    if len(seq_orders) <= 1:
        return "solo"
    if delivery_zones:
        zones = {
            zone_for_point(o.lat, o.lon, delivery_zones) for o in seq_orders
        }
        zones.discard(None)
        if len(zones) == 1:
            return "same_zone_corridor_ok" if corridor else "same_zone"
    if corridor:
        return "corridor_ok"
    return "proximity"


def _zone_label(
    seq_orders: list[OrderCandidate],
    delivery_zones: list[dict] | None,
) -> str | None:
    if not delivery_zones or not seq_orders:
        return None
    zones = [zone_for_point(o.lat, o.lon, delivery_zones) for o in seq_orders]
    named = [z for z in zones if z]
    if not named:
        return None
    if len(set(named)) == 1:
        return named[0]
    return named[0]


def build_route_algorithm_score(
    *,
    engine: str,
    engine_fallback: bool = False,
    seq_orders: list[OrderCandidate],
    per_order_buffer_min: int,
    geo_provider: "GeoPort | None" = None,
    origin: tuple[float, float] | None = None,
    rider_breakdown: dict | None = None,
    rejections: list[dict] | None = None,
    batch_reason: str | None = None,
    total_est_min: int | None = None,
    projected_by_order: dict[int, float] | None = None,
    corridor: bool = False,
    delivery_zones: list[dict] | None = None,
) -> dict:
    """Compose the explainability dict persisted on every Assignment in a route."""
    route_sequence = [o.order_id for o in seq_orders]
    route_times = _compute_route_time_to_stops(seq_orders, geo_provider, origin=origin)
    per_stop: list[dict] = []
    for i, o in enumerate(seq_orders):
        buffer_min = per_order_buffer_min * i
        route_min = round(route_times[i], 1)
        if projected_by_order is not None and o.order_id in projected_by_order:
            projected = round(projected_by_order[o.order_id], 1)
        else:
            projected = round(o.minutes_elapsed + route_times[i] + buffer_min, 1)
        per_stop.append(
            {
                "order_id": o.order_id,
                "projected_min": projected,
                "route_min": route_min,
                "buffer_min": buffer_min,
            }
        )
    if total_est_min is None:
        batch = PlannedBatch(
            orders=seq_orders, per_order_buffer_min=per_order_buffer_min
        )
        total_est_min = compute_batch_total_est_min(
            batch, geo_provider=geo_provider, origin=origin
        )
    score: dict = {
        "engine": engine,
        "engine_fallback": engine_fallback,
        "route_sequence": route_sequence,
        "total_est_min": float(total_est_min),
        "per_stop": per_stop,
        "rejections": list(rejections or []),
        "batch_reason": batch_reason
        or _infer_batch_reason(
            seq_orders,
            corridor=corridor,
            delivery_zones=delivery_zones,
        ),
    }
    zone = _zone_label(seq_orders, delivery_zones)
    if zone:
        score["zone"] = zone
    if rider_breakdown:
        score.update(rider_breakdown)
    return score


def build_rejections_for_dropped(
    order_ids: list[int],
    *,
    candidates_by_id: dict[int, OrderCandidate],
    origin: tuple[float, float],
    geo_provider: "GeoPort | None",
    reason: str = "sla_risk",
) -> list[dict]:
    """Estimate projected minutes for orders the solver left unassigned."""
    from app.dispatch.batching import _leg_minutes

    rejections: list[dict] = []
    for oid in order_ids:
        c = candidates_by_id.get(oid)
        if c is None:
            continue
        leg = _leg_minutes(origin[0], origin[1], c.lat, c.lon, geo_provider)
        rejections.append(
            {
                "order_id": oid,
                "reason": reason,
                "projected_min": round(c.minutes_elapsed + leg, 1),
            }
        )
    return rejections