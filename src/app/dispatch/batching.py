"""Greedy proximity order batching (spec §4.3.2 + CLAUDE.md).

Rules (non-negotiable):
  * max 3 orders per batch;
  * orders grouped within a 10-minute readiness window;
  * clustered by destination proximity (haversine here, PostGIS later);
  * each *additional* batched stop adds a +10 min SLA buffer;
  * a candidate batch is valid only while every order's projected delivery stays
    within the 30-min internal target — exceeding it forces a new batch.

Pure function: takes already-loaded ``OrderCandidate`` rows, returns planned
batches. The dispatch engine (Task 8) materialises these into Batch/BatchOrder.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.geo.haversine import distance_km

SLA_BUFFER_PER_ORDER_MIN = 10
INTERNAL_TARGET_MIN = 30
DEFAULT_WINDOW_MIN = 10
DEFAULT_PROXIMITY_KM = 1.0
DEFAULT_MAX_PER_BATCH = 3


@dataclass
class OrderCandidate:
    order_id: int
    lat: float
    lon: float
    ready_at: datetime
    minutes_elapsed: float  # since sla_confirmed_at


@dataclass
class PlannedBatch:
    orders: list[OrderCandidate] = field(default_factory=list)

    @property
    def sla_buffer_min(self) -> int:
        """+10 min per *additional* batched stop beyond the first."""
        extra = max(0, len(self.orders) - 1)
        return extra * SLA_BUFFER_PER_ORDER_MIN

    @property
    def seed(self) -> OrderCandidate:
        return self.orders[0]


def _within_internal_target(batch: PlannedBatch, candidate: OrderCandidate) -> bool:
    """Every order (incl. candidate) must still clear the 30-min internal target.

    Adding a stop raises the projected SLA buffer for all stops; the order with
    the most elapsed time is the binding constraint.
    """
    projected_buffer = max(0, len(batch.orders)) * SLA_BUFFER_PER_ORDER_MIN
    worst_elapsed = max(
        [o.minutes_elapsed for o in batch.orders] + [candidate.minutes_elapsed]
    )
    return worst_elapsed + projected_buffer <= INTERNAL_TARGET_MIN


def build_batches(
    orders: list[OrderCandidate],
    *,
    max_per_batch: int = DEFAULT_MAX_PER_BATCH,
    proximity_km: float = DEFAULT_PROXIMITY_KM,
    window_min: int = DEFAULT_WINDOW_MIN,
) -> list[PlannedBatch]:
    """Greedy proximity batching.

    Orders are seeded oldest-first; each subsequent order joins the first open
    batch whose seed is within ``proximity_km`` AND within the ``window_min``
    readiness window AND below ``max_per_batch`` AND still inside the 30-min
    internal target. Otherwise it seeds a new batch.
    """
    if not orders:
        return []

    remaining = sorted(orders, key=lambda o: o.ready_at)
    batches: list[PlannedBatch] = []

    for order in remaining:
        placed = False
        for batch in batches:
            if len(batch.orders) >= max_per_batch:
                continue
            seed = batch.seed
            within_proximity = (
                distance_km(seed.lat, seed.lon, order.lat, order.lon) <= proximity_km
            )
            within_window = order.ready_at - seed.ready_at <= timedelta(
                minutes=window_min
            )
            if (
                within_proximity
                and within_window
                and _within_internal_target(batch, order)
            ):
                batch.orders.append(order)
                placed = True
                break
        if not placed:
            batches.append(PlannedBatch(orders=[order]))

    return batches
