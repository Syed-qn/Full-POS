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
