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
    # Minutes added per *additional* stop. Defaults to the global setting; the engine
    # passes a per-restaurant override so managers can trade safety for batching.
    per_order_buffer_min: int = SLA_BUFFER_PER_ORDER_MIN

    @property
    def sla_buffer_min(self) -> int:
        """Buffer for the whole batch = per_order_buffer × (extra stops beyond the first)."""
        extra = max(0, len(self.orders) - 1)
        return extra * self.per_order_buffer_min

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


def _leg_minutes(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    geo_provider: "GeoPort | None" = None,
) -> float:
    """Travel minutes for one leg via geo port (road/traffic when google) or haversine fallback."""
    if geo_provider is not None:
        d = geo_provider.distance_km(lat1, lon1, lat2, lon2)
        return float(geo_provider.eta_minutes(d, buffer_minutes=0))
    return _travel_time_min(lat1, lon1, lat2, lon2)


def _compute_route_time_to_stops(
    orders_in_seq: list[OrderCandidate],
    geo_provider: "GeoPort | None" = None,
    origin: tuple[float, float] | None = None,
) -> list[float]:
    """Cumulative route_time_to_that_stop (mins) for sequenced stops.

    Per spec §4.3.2 the route time TO a stop is measured from where the rider starts —
    the restaurant. ``origin`` (restaurant lat/lon) supplies the depot->first-stop leg so
    the FIRST stop is no longer treated as zero travel (GAP#1). Subsequent stops add the
    sequenced inter-stop legs on top.

    Sequence = input list order (as built by greedy append; spec notes nearest-neighbor later).
    If geo_provider (GeoPort) given: use its .distance_km (road/traffic when google) + .eta_minutes(dist,0).
    Else: haversine + static CITY_SPEED (25kmh per spec graceful + fake).
    origin=None preserves legacy behaviour (first stop = 0.0) for back-compat callers/tests.
    Returns [route_to_first, cum1 for 2nd, ...]
    """
    if not orders_in_seq:
        return []
    if origin is not None:
        first = orders_in_seq[0]
        depot_leg = _leg_minutes(origin[0], origin[1], first.lat, first.lon, geo_provider)
    else:
        depot_leg = 0.0
    times: list[float] = [depot_leg]
    cum = depot_leg
    for i in range(1, len(orders_in_seq)):
        prev = orders_in_seq[i - 1]
        curr = orders_in_seq[i]
        leg = _leg_minutes(prev.lat, prev.lon, curr.lat, curr.lon, geo_provider)
        cum += leg
        times.append(cum)
    return times


def _sequence_stops(
    orders: list[OrderCandidate],
    origin: tuple[float, float],
    geo_provider: "GeoPort | None" = None,
) -> list[OrderCandidate]:
    """Order stops nearest-first from the restaurant (greedy nearest-neighbour), so a
    stop on the way is visited before a farther one. Used only in corridor mode; the
    default proximity path keeps the orders in arrival sequence."""
    if len(orders) <= 1:
        return list(orders)
    remaining = list(orders)
    seq: list[OrderCandidate] = []
    cur = origin
    while remaining:
        nxt = min(
            remaining,
            key=lambda o: _leg_minutes(cur[0], cur[1], o.lat, o.lon, geo_provider),
        )
        seq.append(nxt)
        cur = (nxt.lat, nxt.lon)
        remaining.remove(nxt)
    return seq


def _insertion_detour_km(
    batch_orders: list[OrderCandidate],
    candidate: OrderCandidate,
    origin: tuple[float, float],
) -> float:
    """Extra travel DISTANCE (km, haversine) to fold ``candidate`` into the route,
    minimised over every insertion slot (including before the first stop).

    Near 0 when the candidate sits on the corridor between the restaurant and an
    existing stop (so a 5 km stop on the way to a 10 km stop reads as ~0 detour),
    large when it's off to the side. This is what makes "on-the-way" batching work
    where a flat drop-off-to-drop-off radius would reject it.
    """
    pts = [origin] + [(o.lat, o.lon) for o in batch_orders]
    c = (candidate.lat, candidate.lon)
    best: float | None = None
    for i in range(len(pts)):
        a = pts[i]
        if i + 1 < len(pts):
            b = pts[i + 1]
            extra = (
                distance_km(a[0], a[1], c[0], c[1])
                + distance_km(c[0], c[1], b[0], b[1])
                - distance_km(a[0], a[1], b[0], b[1])
            )
        else:
            extra = distance_km(a[0], a[1], c[0], c[1])  # append at the end
        best = extra if best is None else min(best, extra)
    return max(0.0, best or 0.0)


def _within_internal_target(
    batch: PlannedBatch,
    candidate: OrderCandidate,
    geo_provider: "GeoPort | None" = None,
    origin: tuple[float, float] | None = None,
    buffer_per_order: int = SLA_BUFFER_PER_ORDER_MIN,
    sequence: bool = False,
) -> bool:
    """Every order (incl. candidate) must still clear the 30-min internal target.

    Per spec §4.3: for EVERY order: now−sla_confirmed_at + route_time_to_that_stop (geo/haversine inter-stop)
    + 10 min/order buffer ≤ 30 internal. 'if new same-area cannot fit' -> start fresh batch.
    Uses sequenced inter-stop cum travel (not just proximity to seed). Buffer = extra_stops * 10.
    40min customer via overall design (internal 30 + buf).
    """
    temp = batch.orders + [candidate]
    # In corridor mode the route is resequenced nearest-first, so the SLA check scores
    # the order against the optimized visit order (a near stop reached before a far one).
    if sequence and origin is not None:
        temp = _sequence_stops(temp, origin, geo_provider)
    route_times = _compute_route_time_to_stops(temp, geo_provider, origin=origin)
    n = len(temp)
    projected_buffer = max(0, n - 1) * buffer_per_order
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
    origin: tuple[float, float] | None = None,
    buffer_per_order: int = SLA_BUFFER_PER_ORDER_MIN,
    max_detour_km: float = 0.0,
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

    # Corridor ("on-the-way") batching is opt-in: only when a positive max_detour_km is
    # set AND we know the restaurant origin to measure the route from.
    corridor = max_detour_km > 0 and origin is not None

    # Spec §4.3.2: priority orders bypass batching — each gets its own single-order batch.
    priority_orders = [o for o in remaining if o.priority != "normal"]
    normal_orders = [o for o in remaining if o.priority == "normal"]
    # Priority orders each get a dedicated batch; they are sealed — no normal order joins them.
    priority_batches: list[PlannedBatch] = [
        PlannedBatch(orders=[o], per_order_buffer_min=buffer_per_order) for o in priority_orders
    ]
    # Normal orders go through proximity logic into their own set of batches.
    normal_batches: list[PlannedBatch] = []

    for order in normal_orders:
        placed = False
        for batch in normal_batches:
            if len(batch.orders) >= max_per_batch:
                continue
            seed = batch.seed
            # Geometric gate: near the seed (radius) OR a small detour off the route
            # (corridor). Either way the SLA check below still has the final say.
            within_proximity = (
                distance_km(seed.lat, seed.lon, order.lat, order.lon) <= proximity_km
            )
            within_corridor = corridor and (
                _insertion_detour_km(batch.orders, order, origin) <= max_detour_km
            )
            within_window = order.ready_at - seed.ready_at <= timedelta(
                minutes=window_min
            )
            if (
                (within_proximity or within_corridor)
                and within_window
                and _within_internal_target(
                    batch, order, geo_provider=geo_provider, origin=origin,
                    buffer_per_order=buffer_per_order, sequence=corridor,
                )
            ):
                batch.orders.append(order)
                # Keep the persisted stop order = the optimized visit order.
                if corridor:
                    batch.orders = _sequence_stops(batch.orders, origin, geo_provider)
                placed = True
                break
        if not placed:
            normal_batches.append(
                PlannedBatch(orders=[order], per_order_buffer_min=buffer_per_order)
            )

    batches = priority_batches + normal_batches

    return batches


def compute_batch_total_est_min(
    batch: PlannedBatch,
    geo_provider: "GeoPort | None" = None,
    origin: tuple[float, float] | None = None,
) -> int:
    """Compute total_est_min for Batch (max over stops of elapsed + route_to_stop + buffer).

    Called by dispatch service after build (with geo) to set on persisted Batch.
    Uses same inter-stop cum + buf logic as validity (enterprise consistent, no hardcode).
    """
    if not batch.orders:
        return 0
    route_times = _compute_route_time_to_stops(batch.orders, geo_provider, origin=origin)
    buf = batch.sla_buffer_min
    projs = [
        o.minutes_elapsed + route_times[i] + buf for i, o in enumerate(batch.orders)
    ]
    return max(1, int(max(projs) or 0))
