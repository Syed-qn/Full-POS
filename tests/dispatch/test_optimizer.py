"""Unit tests for the OR-Tools dispatch optimizer (pure, no DB).

Objective (locked with user): SLA-first hard constraint (every served order's
projected completion <= 40-min customer SLA), cost (total drive time) as tiebreak.
Best-effort partial: orders that cannot be served on time are DROPPED (returned as
unassigned) rather than blocking the plan. Priority orders get their own route,
served first. Locked (assigned-not-picked) orders stay with their current rider.
"""

from app.dispatch.optimizer import OptOrder, OptRider, optimize_dispatch

# Restaurant / depot location (Dubai-ish).
DEPOT = (25.2048, 55.2708)


def _order(oid, lat, lon, elapsed=5.0, priority="normal", locked_rider_id=None):
    return OptOrder(
        order_id=oid,
        lat=lat,
        lon=lon,
        minutes_elapsed=elapsed,
        priority=priority,
        locked_rider_id=locked_rider_id,
    )


def _rider(rid, lat=25.2048, lon=55.2708, active_load=0):
    return OptRider(rider_id=rid, lat=lat, lon=lon, active_load=active_load)


def test_empty_orders_returns_empty_plan():
    plan = optimize_dispatch(orders=[], riders=[_rider(1)], origin=DEPOT)
    assert plan.routes == []
    assert plan.unassigned == []


def test_two_near_orders_one_rider_single_route():
    """Two close orders, one rider, low elapsed -> both on ONE route, both within SLA."""
    orders = [
        _order(1, 25.2050, 55.2710, elapsed=5.0),
        _order(2, 25.2055, 55.2715, elapsed=5.0),  # ~70 m apart
    ]
    plan = optimize_dispatch(orders=orders, riders=[_rider(1)], origin=DEPOT)
    assert plan.unassigned == []
    assert len(plan.routes) == 1
    assert set(plan.routes[0].order_ids) == {1, 2}
    # every projected completion stays within the 40-min customer SLA
    assert all(p <= 40 for p in plan.routes[0].projected_minutes.values())


def test_impossible_order_is_dropped_not_blocking():
    """An order already past the SLA (50 min elapsed) cannot be served on time ->
    best-effort: it is dropped to unassigned, the feasible one is still served."""
    orders = [
        _order(1, 25.2050, 55.2710, elapsed=5.0),    # fine
        _order(2, 25.2060, 55.2720, elapsed=50.0),   # already > 40 min -> impossible
    ]
    plan = optimize_dispatch(orders=orders, riders=[_rider(1)], origin=DEPOT)
    served = {oid for r in plan.routes for oid in r.order_ids}
    assert 1 in served
    assert 2 in plan.unassigned
    assert 2 not in served


def test_two_far_orders_one_rider_serves_what_fits_drops_rest():
    """East + west, one rider, both tight -> the single rider cannot reach both within
    SLA, so one is served and the other dropped (the east/west + 1-rider scenario)."""
    # ~4 km due north and due south of the depot (opposite directions). Each is
    # individually reachable within the remaining 12-min budget (~10-min leg), but a
    # single rider doing one then crossing to the other (~19 min) blows the SLA on the
    # second -> serve one, drop the other.
    orders = [
        _order(1, 25.2408, 55.2708, elapsed=28.0),   # north, tight
        _order(2, 25.1688, 55.2708, elapsed=28.0),   # south, opposite way
    ]
    plan = optimize_dispatch(orders=orders, riders=[_rider(1)], origin=DEPOT)
    served = {oid for r in plan.routes for oid in r.order_ids}
    assert len(served) == 1
    assert len(plan.unassigned) == 1
    assert served | set(plan.unassigned) == {1, 2}


def test_priority_order_gets_own_route():
    """Priority order must be served on its own dedicated rider, never batched with
    normal orders that are right next to it."""
    orders = [
        _order(10, 25.2049, 55.2709, priority="priority"),
        _order(11, 25.2050, 55.2710),  # normal, ~15 m from the priority order
        _order(12, 25.2051, 55.2711),  # normal, also adjacent
    ]
    plan = optimize_dispatch(orders=orders, riders=[_rider(1), _rider(2)], origin=DEPOT)
    # find the route carrying the priority order
    prio_route = next(r for r in plan.routes if 10 in r.order_ids)
    assert prio_route.order_ids == [10], "priority order rides alone"
    # the two normals are served by the OTHER rider
    other = {oid for r in plan.routes for oid in r.order_ids if r is not prio_route}
    assert other == {11, 12}


def test_locked_order_stays_with_its_current_rider():
    """An assigned-but-not-picked order pinned to rider 2 must be served by rider 2,
    even if rider 1 is otherwise a fine candidate."""
    orders = [
        _order(1, 25.2050, 55.2710),                       # free
        _order(2, 25.2300, 55.3000, locked_rider_id=2),    # pinned to rider 2
    ]
    plan = optimize_dispatch(
        orders=orders, riders=[_rider(1), _rider(2)], origin=DEPOT
    )
    route_for_2 = next(r for r in plan.routes if 2 in r.order_ids)
    assert route_for_2.rider_id == 2


def test_no_riders_drops_everything():
    """No riders -> nothing can be served, all orders returned as unassigned."""
    orders = [_order(1, 25.2050, 55.2710), _order(2, 25.2055, 55.2715)]
    plan = optimize_dispatch(orders=orders, riders=[], origin=DEPOT)
    assert plan.routes == []
    assert set(plan.unassigned) == {1, 2}
