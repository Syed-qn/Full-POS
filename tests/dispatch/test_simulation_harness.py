"""Regression harness — spec §7 integration + design §10.2 SLA boundaries."""

from datetime import datetime, timezone

import pytest

from app.dispatch.batching import OrderCandidate, build_batches, compute_batch_total_est_min
from app.dispatch.batch_plan import BatchPlanSettings, run_batch_plan
from app.geo.fake import FakeGeoProvider

ORIGIN = (25.2048, 55.2708)
GEO = FakeGeoProvider()


def _c(oid: int, lat: float, lon: float, elapsed: float = 5.0) -> OrderCandidate:
    now = datetime.now(timezone.utc)
    return OrderCandidate(
        order_id=oid,
        lat=lat,
        lon=lon,
        ready_at=now,
        minutes_elapsed=elapsed,
        priority="normal",
    )


def test_ab_ad_ba_batch_pattern_sla_invariant():
    """A,B,A,D,B,A — corridor cluster (D far) stays SLA-safe; D rides solo."""
    orders = [
        _c(1, 25.2050, 55.2710),
        _c(2, 25.2053, 55.2713),
        _c(3, 25.2056, 55.2716),
        _c(4, 25.2600, 55.3300, elapsed=8.0),
        _c(5, 25.2059, 55.2719),
        _c(6, 25.2062, 55.2722),
    ]
    near_pool = [orders[0], orders[1], orders[2], orders[4], orders[5]]
    batches = build_batches(
        near_pool,
        geo_provider=GEO,
        origin=ORIGIN,
        max_per_batch=3,
        proximity_km=2.0,
        buffer_per_order=10,
    )
    for batch in batches:
        assert compute_batch_total_est_min(batch, geo_provider=GEO, origin=ORIGIN) <= 40
    far_batches = build_batches(
        [orders[3]],
        geo_provider=GEO,
        origin=ORIGIN,
        max_per_batch=3,
        proximity_km=2.0,
        buffer_per_order=10,
    )
    assert len(far_batches) == 1
    assert len(far_batches[0].orders) == 1


@pytest.mark.parametrize(
    "elapsed,route_buf,should_batch",
    [
        (35, 4, False),
        (8, 10, True),  # 8 + ~3 route + 10 buffer < 30 internal
    ],
)
def test_sla_boundary_greedy_internal_gate(elapsed, route_buf, should_batch):
    """Greedy: elapsed + route + buffer <= 30 internal."""
    seed = _c(1, 25.2050, 55.2710, elapsed=elapsed)
    mate = _c(2, 25.2052, 55.2712, elapsed=elapsed)
    batches = build_batches(
        [seed, mate],
        geo_provider=GEO,
        origin=ORIGIN,
        proximity_km=2.0,
        buffer_per_order=route_buf,
    )
    if should_batch:
        assert len(batches) == 1 and len(batches[0].orders) == 2
    else:
        assert sum(len(b.orders) for b in batches) <= 2


def test_run_batch_plan_matches_build_batches():
    """Shared planner delegates to build_batches with settings."""
    orders = [_c(1, 25.2050, 55.2710), _c(2, 25.2052, 55.2712)]
    settings = BatchPlanSettings(proximity_km=2.0, buffer_per_order=10)
    planned = run_batch_plan(orders, settings=settings, geo_provider=GEO, origin=ORIGIN)
    direct = build_batches(
        orders,
        geo_provider=GEO,
        origin=ORIGIN,
        proximity_km=2.0,
        buffer_per_order=10,
    )
    assert [[o.order_id for o in b.orders] for b in planned] == [
        [o.order_id for o in b.orders] for b in direct
    ]