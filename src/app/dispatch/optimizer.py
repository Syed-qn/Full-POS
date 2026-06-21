"""OR-Tools dispatch optimizer (spec §4.3, enterprise-grade upgrade over greedy).

Objective (locked with product): **SLA-first hard constraint, cost tiebreak.**
Every order that gets routed must have its projected completion within the 40-min
customer SLA; among all SLA-feasible plans the solver minimizes total rider drive
time. Orders that cannot be served on time are *dropped* (best-effort partial) and
returned in ``unassigned`` so the caller can warn the manager — they never block the
rest of the plan.

Design:
  * Priority orders are pulled out FIRST and each gets its own dedicated nearest
    rider (spec §4.3.3 "single-rider dispatch" / user decision "own route, served
    first"). They are removed from the VRP pool so they are never batched.
  * The remaining normal + locked orders are solved as a capacitated VRP with a time
    dimension. Depot = restaurant. Each delivery node carries an upper bound on the
    cumulative drive time of ``customer_sla_min - minutes_elapsed`` → the hard SLA.
  * Each normal node has a drop ``AddDisjunction`` penalty (>> any travel cost) so the
    solver serves as many orders as possible first, then minimizes drive.
  * Locked orders (assigned-but-not-picked) are pinned to their current rider via
    ``VehicleVar == v`` and are mandatory (no drop).

Rider→restaurant pickup leg is intentionally NOT in the time model — per spec §4.3.4
that is handled by rider scoring, and the SLA promise is measured from order confirm,
not from rider position. All vehicles therefore start at the depot with cumul 0.

Pure module: no DB, no I/O. The dispatch service builds these dataclasses from rows,
calls :func:`optimize_dispatch`, and materialises the returned plan into Batch /
Assignment rows (reusing the existing persistence path).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.config import get_settings
from app.dispatch.batching import _leg_minutes

if TYPE_CHECKING:
    from app.geo.port import GeoPort

logger = logging.getLogger(__name__)

# Travel minutes are scaled to integers for OR-Tools (which is integer-only).
# 100 units = 1 minute → ~0.6 s resolution, plenty for city dispatch.
_SCALE = 100
# Dropping an order must always cost more than any conceivable route, so the solver
# only drops when an order genuinely cannot be served within the SLA.
_DROP_PENALTY = 10_000_000


@dataclass
class OptOrder:
    order_id: int
    lat: float
    lon: float
    minutes_elapsed: float  # since sla_confirmed_at
    priority: str = "normal"  # "normal" | "priority"
    locked_rider_id: int | None = None  # set for assigned-but-not-picked orders


@dataclass
class OptRider:
    rider_id: int
    lat: float
    lon: float
    active_load: int = 0  # current in-flight orders (tiebreak for priority pick)


@dataclass
class OptRoute:
    rider_id: int
    order_ids: list[int] = field(default_factory=list)
    projected_minutes: dict[int, float] = field(default_factory=dict)


@dataclass
class OptPlan:
    routes: list[OptRoute] = field(default_factory=list)
    unassigned: list[int] = field(default_factory=list)


def _budget_units(order: OptOrder, customer_sla_min: int) -> int:
    """Remaining drive-time budget (scaled) before this order breaches the SLA."""
    remaining = customer_sla_min - order.minutes_elapsed
    if remaining <= 0:
        return 0
    return int(remaining * _SCALE)


def _assign_priority(
    priority_orders: list[OptOrder],
    riders: list[OptRider],
    origin: tuple[float, float],
    customer_sla_min: int,
    geo_provider: "GeoPort | None",
) -> tuple[list[OptRoute], list[int], set[int]]:
    """Give each priority order its own nearest free rider (own route, served first).

    Returns (routes, dropped_order_ids, used_rider_ids). A priority order with no rider
    left, or one that already can't make the SLA, is dropped to unassigned.
    """
    routes: list[OptRoute] = []
    dropped: list[int] = []
    used: set[int] = set()
    # Serve the tightest (most elapsed) priority orders first.
    for order in sorted(priority_orders, key=lambda o: o.minutes_elapsed, reverse=True):
        free = [r for r in riders if r.rider_id not in used]
        if not free:
            dropped.append(order.order_id)
            continue
        leg = _leg_minutes(origin[0], origin[1], order.lat, order.lon, geo_provider)
        if order.minutes_elapsed + leg > customer_sla_min:
            dropped.append(order.order_id)
            continue
        # nearest available rider to the restaurant pickup, lightest load as tiebreak
        best = min(
            free,
            key=lambda r: (
                _leg_minutes(r.lat, r.lon, origin[0], origin[1], geo_provider),
                r.active_load,
            ),
        )
        used.add(best.rider_id)
        routes.append(
            OptRoute(
                rider_id=best.rider_id,
                order_ids=[order.order_id],
                projected_minutes={order.order_id: order.minutes_elapsed + leg},
            )
        )
    return routes, dropped, used


def optimize_dispatch(
    *,
    orders: list[OptOrder],
    riders: list[OptRider],
    origin: tuple[float, float],
    customer_sla_min: int | None = None,
    geo_provider: "GeoPort | None" = None,
    time_limit_seconds: int = 3,
) -> OptPlan:
    """Plan rider routes for ``orders`` minimizing drive under a hard SLA constraint.

    See module docstring. Returns an :class:`OptPlan`. Never raises on an infeasible
    instance — unservable orders come back in ``unassigned``.
    """
    if customer_sla_min is None:
        customer_sla_min = get_settings().sla_customer_minutes

    if not orders:
        return OptPlan()

    # 1) Priority orders: dedicated rider each, removed from the VRP pool.
    priority = [o for o in orders if o.priority != "normal"]
    normal = [o for o in orders if o.priority == "normal"]
    prio_routes, prio_dropped, used = _assign_priority(
        priority, riders, origin, customer_sla_min, geo_provider
    )

    vrp_riders = [r for r in riders if r.rider_id not in used]
    plan = OptPlan(routes=list(prio_routes), unassigned=list(prio_dropped))

    if not normal:
        return plan
    if not vrp_riders:
        # No riders left for normal orders → all drop to unassigned.
        plan.unassigned.extend(o.order_id for o in normal)
        return plan

    # 2) VRP over the remaining normal (+ locked) orders.
    # Node 0 = depot (restaurant); nodes 1..N = orders.
    node_orders = normal
    n_nodes = len(node_orders) + 1
    points: list[tuple[float, float]] = [origin] + [
        (o.lat, o.lon) for o in node_orders
    ]

    # Integer travel-time matrix (scaled minutes).
    matrix = [[0] * n_nodes for _ in range(n_nodes)]
    for i in range(n_nodes):
        for j in range(n_nodes):
            if i == j:
                continue
            mins = _leg_minutes(
                points[i][0], points[i][1], points[j][0], points[j][1], geo_provider
            )
            matrix[i][j] = int(round(mins * _SCALE))

    n_vehicles = len(vrp_riders)
    manager = pywrapcp.RoutingIndexManager(n_nodes, n_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def _transit(from_index: int, to_index: int) -> int:
        return matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_idx = routing.RegisterTransitCallback(_transit)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # Time dimension: cumulative drive time from the depot along each route.
    horizon = customer_sla_min * _SCALE
    routing.AddDimension(
        transit_idx,
        0,  # no slack/waiting
        horizon,
        True,  # start cumul at zero (all vehicles begin at the depot, now)
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    rider_index = {r.rider_id: v for v, r in enumerate(vrp_riders)}

    # Per-node SLA upper bound + drop disjunction / lock constraints.
    for node, order in enumerate(node_orders, start=1):
        index = manager.NodeToIndex(node)
        time_dim.CumulVar(index).SetMax(_budget_units(order, customer_sla_min))
        if order.locked_rider_id is not None and order.locked_rider_id in rider_index:
            # Pinned to its current rider; mandatory (no drop).
            routing.VehicleVar(index).SetValue(rider_index[order.locked_rider_id])
        else:
            # Droppable at high penalty → serve as many as possible, then min drive.
            routing.AddDisjunction([index], _DROP_PENALTY)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(time_limit_seconds)

    solution = routing.SolveWithParameters(params)
    if solution is None:
        # Solver could not produce any plan (e.g. an infeasible lock). Stay best-effort:
        # leave priority routes, drop all normal orders to unassigned.
        logger.warning("optimizer: no solution; dropping %d normal orders", len(normal))
        plan.unassigned.extend(o.order_id for o in normal)
        return plan

    served: set[int] = set()
    for v, rider in enumerate(vrp_riders):
        index = routing.Start(v)
        route = OptRoute(rider_id=rider.rider_id)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:  # skip depot
                order = node_orders[node - 1]
                cumul = solution.Value(time_dim.CumulVar(index)) / _SCALE
                route.order_ids.append(order.order_id)
                route.projected_minutes[order.order_id] = (
                    order.minutes_elapsed + cumul
                )
                served.add(order.order_id)
            index = solution.Value(routing.NextVar(index))
        if route.order_ids:
            plan.routes.append(route)

    plan.unassigned.extend(o.order_id for o in normal if o.order_id not in served)
    return plan
