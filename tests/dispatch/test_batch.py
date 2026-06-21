from datetime import datetime, timedelta, timezone

from app.dispatch.batching import OrderCandidate, build_batches

MAX_PER_BATCH = 3
BASE = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _order(oid, lat, lon, ready_offset_s=0):
    return OrderCandidate(
        order_id=oid,
        lat=lat,
        lon=lon,
        ready_at=BASE + timedelta(seconds=ready_offset_s),
        minutes_elapsed=5.0,  # since sla_confirmed_at
    )


def test_nearby_orders_batched_together():
    orders = [
        _order(1, 25.2048, 55.2708),
        _order(2, 25.2050, 55.2710),  # ~30 m away
    ]
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0)
    assert len(batches) == 1
    assert {o.order_id for o in batches[0].orders} == {1, 2}


def test_far_orders_split_into_separate_batches():
    orders = [
        _order(1, 25.2048, 55.2708),
        _order(2, 25.3000, 55.4000),  # several km away
    ]
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0)
    assert len(batches) == 2


def test_batch_capped_at_max_per_batch():
    orders = [_order(i, 25.2048 + i * 0.0001, 55.2708) for i in range(1, 6)]  # 5 close orders
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0)
    assert all(len(b.orders) <= MAX_PER_BATCH for b in batches)
    assert sum(len(b.orders) for b in batches) == 5


def test_readiness_window_splits_late_order():
    orders = [
        _order(1, 25.2048, 55.2708, ready_offset_s=0),
        _order(2, 25.2049, 55.2709, ready_offset_s=11 * 60),  # 11 min later > window
    ]
    batches = build_batches(
        orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0, window_min=10
    )
    assert len(batches) == 2


def test_sla_buffer_applied_per_stop():
    orders = [_order(1, 25.2048, 55.2708), _order(2, 25.2050, 55.2710)]
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0)
    # 2 orders -> second stop carries +10 min buffer
    assert batches[0].sla_buffer_min == 10


def test_empty_input_returns_empty():
    assert build_batches([], max_per_batch=MAX_PER_BATCH, proximity_km=1.0) == []


def test_priority_order_gets_own_batch():
    """A priority order must get its own single-order batch even when normal orders are nearby."""
    priority_order = OrderCandidate(
        order_id=10,
        lat=25.2048,
        lon=55.2708,
        ready_at=BASE,
        minutes_elapsed=5.0,
        priority="priority",
    )
    normal_1 = _order(11, 25.2049, 55.2709)  # ~15 m away — would batch with normal
    normal_2 = _order(12, 25.2050, 55.2710)  # ~30 m away — would batch with normal
    batches = build_batches(
        [priority_order, normal_1, normal_2], max_per_batch=MAX_PER_BATCH, proximity_km=1.0
    )
    # priority order -> own batch; 2 normal nearby -> 1 batch = 2 total
    assert len(batches) == 2
    priority_batch = next(b for b in batches if b.orders[0].order_id == 10)
    assert len(priority_batch.orders) == 1
    normal_batch = next(b for b in batches if b.orders[0].order_id != 10)
    assert len(normal_batch.orders) == 2


def test_active_order_count_field_on_order_candidate():
    """OrderCandidate priority field defaults to 'normal' for backward compat."""
    oc = _order(99, 25.0, 55.0)
    assert oc.priority == "normal"

    oc_priority = OrderCandidate(
        order_id=100,
        lat=25.0,
        lon=55.0,
        ready_at=BASE,
        minutes_elapsed=3.0,
        priority="priority",
    )
    assert oc_priority.priority == "priority"


def test_inter_stop_travel_time_affects_internal_target_and_forces_fresh_batch():
    """GAP_LIST #4 (spec §4.3): build_batches must incorporate sequenced inter-stop travel time (haversine+static or geo port) in _within_internal_target.

    Orders close enough for prox+window (seed), elapsed=19 each; inter ~1.9min for 2nd stop.
    w/o route: 19 + (1*10 buf) =29 <=30 -> would batch.
    w/ route_to_2nd: 19 +1.9 +10 >30 internal -> must not place, start fresh (2 batches).
    Also covers priority single already (existing test) + 40min cust (30+10 design).
    total_est_min asserted via engine; here drive the source calc change.
    """
    # delta ~0.0075 lat ~0.83km inter leg -> ~2min @25kmh
    o1 = OrderCandidate(
        order_id=1, lat=25.2048, lon=55.2708, ready_at=BASE, minutes_elapsed=19.0
    )
    o2 = OrderCandidate(
        order_id=2,
        lat=25.2048 + 0.0075,
        lon=55.2708 + 0.0005,
        ready_at=BASE,
        minutes_elapsed=19.0,
    )
    batches = build_batches(
        [o1, o2], max_per_batch=MAX_PER_BATCH, proximity_km=1.0, window_min=10
    )
    assert len(batches) == 2, "inter-stop route_time must cause 'cannot fit' -> dispatch current, start fresh"
    assert all(len(b.orders) == 1 for b in batches)


def test_origin_depot_leg_counts_toward_internal_target():
    """GAP#1 (spec §4.3.2): route_time_to_that_stop must include the restaurant->first-stop
    (depot) leg for EVERY order, not just inter-stop legs.

    Two orders ~70 m apart (proximity+window OK) but ~14 km from the restaurant origin.
    Without origin: proj(seed) = 2 elapsed + 0 depot + 10 buf = 12 <= 30 -> 1 batch.
    With origin: depot leg ~33 min pushes proj(seed) = 2 + 33 + 10 > 30 -> cannot fit -> 2 batches.
    """
    o1 = OrderCandidate(1, 25.3000, 55.4000, BASE, minutes_elapsed=2.0)
    o2 = OrderCandidate(2, 25.3005, 55.4005, BASE, minutes_elapsed=2.0)  # ~70 m from o1
    restaurant_origin = (25.2048, 55.2708)  # ~14 km away

    no_origin = build_batches([o1, o2], max_per_batch=3, proximity_km=1.0, window_min=10)
    assert len(no_origin) == 1, "without depot leg the two would batch (legacy back-compat)"

    with_origin = build_batches(
        [o1, o2], max_per_batch=3, proximity_km=1.0, window_min=10, origin=restaurant_origin
    )
    assert len(with_origin) == 2, "depot leg (restaurant->first stop) must count -> cannot fit"


def test_compute_total_est_includes_depot_leg():
    """GAP#1: total_est_min for a batch must include the restaurant->first-stop drive time."""
    from app.dispatch.batching import PlannedBatch, compute_batch_total_est_min

    far_stop = OrderCandidate(1, 25.3000, 55.4000, BASE, minutes_elapsed=0.0)
    batch = PlannedBatch(orders=[far_stop])
    origin = (25.2048, 55.2708)  # ~14 km
    est_no_origin = compute_batch_total_est_min(batch)
    est_with_origin = compute_batch_total_est_min(batch, origin=origin)
    assert est_with_origin > est_no_origin
    assert est_with_origin >= 25, "14 km depot leg must add a meaningful drive estimate"


def test_planned_batch_and_compute_respects_geo_port_equiv_for_inter_stop():
    """Unit drive: when geo passed (future), inter calc uses its distance/eta; haversine fallback when None.
    (In practice engine passes get_geo_provider() which for tests is Fake equiv to haversine 25kmh.)
    """
    o1 = OrderCandidate(1, 25.2048, 55.2708, BASE, minutes_elapsed=5.0)
    o2 = OrderCandidate(2, 25.2055, 55.2715, BASE, minutes_elapsed=5.0)  # farther but <1km
    # call w/ no geo (default haversine path)
    batches = build_batches([o1, o2], max_per_batch=3, proximity_km=1.0, window_min=10)
    # with low elapsed=5 + buf10 + small route <30 -> 1 batch
    assert len(batches) == 1
    # (full geo threading + compute_batch_total_est_min verified in engine test + service)
