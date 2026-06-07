"""Greedy proximity order batching (spec §4.3.2 + CLAUDE.md).

Rules (non-negotiable per spec §4.3):
  "now − sla_confirmed_at + route_time_to_that_stop (traffic-aware) + 10 min/order buffer ≤ 30 min internal target"
  "if new same-area cannot fit <40 customer then dispatch current start fresh"
  * max 3 orders per batch (or from settings);
  * orders grouped within a 10-minute readiness window;
  * clustered by destination proximity (haversine for cluster; geo port for inter-stop travel);
  * inter-stop travel (sequenced sum between ordered stops using geo/haversine) included in projected;
  * each *additional* batched stop adds a +10 min SLA buffer;
  * a candidate batch is valid only while EVERY order's (elapsed + route_to_its_stop + buf) stays
    within the 30-min internal target — exceeding it forces a new batch (start fresh).
  total_est_min computed/set on Batch from max projected (incl inter-stop).

Pure function (with optional geo_provider for port/haversine traffic/road): takes already-loaded
``OrderCandidate`` rows, returns planned batches. The dispatch engine materialises these into
Batch/BatchOrder (sets total_est_min). Consts from settings (no hardcode).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.config import get_settings
from app.geo.haversine import distance_km

if TYPE_CHECKING:
    from app.geo.port import GeoPort

_s = get_settings()
SLA_BUFFER_PER_ORDER_MIN = _s.sla_buffer_per_order_minutes
INTERNAL_TARGET_MIN = _s.sla_internal_target_minutes
CUSTOMER_SLA_MIN = _s.sla_customer_minutes  # 40; used for design/docs (internal 30 + buf targets customer)
CITY_SPEED_KMH = _s.geo_city_speed_kmh
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
    priority: str = "normal"  # "normal" | "priority"


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


def _travel_time_min(
    lat1: float, lon1: float, lat2: float, lon2: float, speed_kmh: float | None = None
) -> float:
    """Leg travel minutes using haversine dist + static city speed (fallback or tests)."""
    if speed_kmh is None:
        speed_kmh = CITY_SPEED_KMH
    d = distance_km(lat1, lon1, lat2, lon2)
    if d <= 0:
        return 0.0
    return (d / speed_kmh) * 60.0


def _compute_route_time_to_stops(
    orders_in_seq: list[OrderCandidate], geo_provider: "GeoPort | None" = None
) -> list[float]:
    """Cumulative route_time_to_that_stop (mins) for sequenced stops (inter-stop travel sum).

    Sequence = input list order (as built by greedy append; spec notes nearest-neighbor later).
    If geo_provider (GeoPort) given: use its .distance_km (road/traffic when google) + .eta_minutes(dist,0).
    Else: haversine + static CITY_SPEED (25kmh per spec graceful + fake).
    Returns [0.0 for first, cum1 for 2nd, ...]
    """
    if not orders_in_seq:
        return []
    times: list[float] = [0.0]
    cum = 0.0
    for i in range(1, len(orders_in_seq)):
        prev = orders_in_seq[i - 1]
        curr = orders_in_seq[i]
        if geo_provider is not None:
            d = geo_provider.distance_km(prev.lat, prev.lon, curr.lat, curr.lon)
            leg = float(geo_provider.eta_minutes(d, buffer_minutes=0))
        else:
            leg = _travel_time_min(prev.lat, prev.lon, curr.lat, curr.lon)
        cum += leg
        times.append(cum)
    return times


def _within_internal_target(
    batch: PlannedBatch, candidate: OrderCandidate, geo_provider: "GeoPort | None" = None
) -> bool:
    """Every order (incl. candidate) must still clear the 30-min internal target.

    Per spec §4.3: for EVERY order: now−sla_confirmed_at + route_time_to_that_stop (geo/haversine inter-stop)
    + 10 min/order buffer ≤ 30 internal. 'if new same-area cannot fit' -> start fresh batch.
    Uses sequenced inter-stop cum travel (not just proximity to seed). Buffer = extra_stops * 10.
    40min customer via overall design (internal 30 + buf).
    """
    temp = batch.orders + [candidate]
    route_times = _compute_route_time_to_stops(temp, geo_provider)
    n = len(temp)
    projected_buffer = max(0, n - 1) * SLA_BUFFER_PER_ORDER_MIN
    for i, o in enumerate(temp):
        proj = o.minutes_elapsed + route_times[i] + projected_buffer
        if proj > INTERNAL_TARGET_MIN:
            return False
    return True


def build_batches(
    orders: list[OrderCandidate],
    *,
    max_per_batch: int = DEFAULT_MAX_PER_BATCH,
    proximity_km: float = DEFAULT_PROXIMITY_KM,
    window_min: int = DEFAULT_WINDOW_MIN,
    geo_provider: "GeoPort | None" = None,
) -> list[PlannedBatch]:
    """Greedy proximity batching (with inter-stop travel gap fix per GAP#4/spec §4.3).

    Orders are seeded oldest-first; each subsequent order joins the first open
    batch whose seed is within ``proximity_km`` AND within the ``window_min``
    readiness window AND below ``max_per_batch`` AND still inside the 30-min
    internal target (NOW including sequenced inter-stop route_time via geo/haversine).
    Otherwise it seeds a new batch ("if new same-area cannot fit <40 customer then dispatch current start fresh").

    geo_provider (GeoPort): if provided (from factory in engine), inter-stop uses its distance/eta
    (traffic-aware when google_maps, else haversine fallback). Unit tests use None -> pure haversine.
    Priority orders always single (sealed), even if threatens (protected).
    """
    if not orders:
        return []

    remaining = sorted(orders, key=lambda o: o.ready_at)

    # Spec §4.3.2: priority orders bypass batching — each gets its own single-order batch.
    priority_orders = [o for o in remaining if o.priority != "normal"]
    normal_orders = [o for o in remaining if o.priority == "normal"]
    # Priority orders each get a dedicated batch; they are sealed — no normal order joins them.
    priority_batches: list[PlannedBatch] = [PlannedBatch(orders=[o]) for o in priority_orders]
    # Normal orders go through proximity logic into their own set of batches.
    normal_batches: list[PlannedBatch] = []

    for order in normal_orders:
        placed = False
        for batch in normal_batches:
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
                and _within_internal_target(batch, order, geo_provider=geo_provider)
            ):
                batch.orders.append(order)
                placed = True
                break
        if not placed:
            normal_batches.append(PlannedBatch(orders=[order]))

    batches = priority_batches + normal_batches

    return batches


def compute_batch_total_est_min(
    batch: PlannedBatch, geo_provider: "GeoPort | None" = None
) -> int:
    """Compute total_est_min for Batch (max over stops of elapsed + route_to_stop + buffer).

    Called by dispatch service after build (with geo) to set on persisted Batch.
    Uses same inter-stop cum + buf logic as validity (enterprise consistent, no hardcode).
    """
    if not batch.orders:
        return 0
    route_times = _compute_route_time_to_stops(batch.orders, geo_provider)
    buf = batch.sla_buffer_min
    projs = [
        o.minutes_elapsed + route_times[i] + buf for i, o in enumerate(batch.orders)
    ]
    return max(1, int(max(projs) or 0))
