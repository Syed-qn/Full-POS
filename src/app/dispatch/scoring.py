"""Rider scoring (spec §4.3.4).

Composite blends distance-to-pickup, current workload, and on-time %.
Lower composite = better candidate. Riders are employees — there is no
accept/reject; the engine assigns the best-scoring available rider.

The ``breakdown`` payload is persisted verbatim to ``assignments.algorithm_score``
for dispatch explainability.
"""

from dataclasses import dataclass, field

# Weights (tunable; lower composite = better candidate).
_W_DISTANCE = 1.0  # per km
_W_WORKLOAD = 2.0  # per active order
_W_ONTIME = 0.10  # per missing on-time percentage point


@dataclass
class RiderCandidate:
    rider_id: int
    distance_km: float  # rider -> restaurant (pickup)
    active_orders: int  # current in-flight orders (workload)
    on_time_pct: float  # rider.performance["on_time_pct"]


@dataclass
class ScoredRider:
    rider_id: int
    composite: float
    breakdown: dict = field(default_factory=dict)


def score_rider(c: RiderCandidate) -> ScoredRider:
    """Composite score — lower is better. Persisted to assignments.algorithm_score."""
    distance_score = _W_DISTANCE * c.distance_km
    workload_score = _W_WORKLOAD * c.active_orders
    # on-time penalty: how far below 100% the rider is
    on_time_penalty = _W_ONTIME * max(0.0, 100.0 - c.on_time_pct)
    composite = distance_score + workload_score + on_time_penalty
    return ScoredRider(
        rider_id=c.rider_id,
        composite=composite,
        breakdown={
            "distance_km": c.distance_km,
            "workload_score": workload_score,
            "on_time_pct": c.on_time_pct,
            "composite": composite,
        },
    )


def rank_riders(candidates: list[RiderCandidate]) -> list[ScoredRider]:
    """Return scored riders sorted best (lowest composite) first."""
    return sorted((score_rider(c) for c in candidates), key=lambda s: s.composite)
