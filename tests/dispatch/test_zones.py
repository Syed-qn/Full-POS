"""Unit tests for manual delivery zones and corridor detour eligibility."""

from app.dispatch.zones import same_zone_or_corridor, zone_for_point

ZONES = [{"name": "Marina", "center_lat": 25.08, "center_lng": 55.14, "radius_km": 2.5}]

NORTH_ZONE = {
    "name": "North",
    "center_lat": 25.225,
    "center_lng": 55.270,
    "radius_km": 0.5,
}
ON_WAY_ZONE = {
    "name": "MidNorth",
    "center_lat": 25.211,
    "center_lng": 55.270,
    "radius_km": 0.5,
}
SPLIT_ZONES = [NORTH_ZONE, ON_WAY_ZONE]


def test_same_zone_eligible():
    a = zone_for_point(25.081, 55.141, ZONES)
    b = zone_for_point(25.082, 55.142, ZONES)
    assert a == b == "Marina"
    assert same_zone_or_corridor(
        a,
        b,
        (25.08, 55.14),
        (25.081, 55.141),
        (25.082, 55.142),
        max_detour_km=0.8,
    )


def test_zone_for_point_outside_returns_none():
    assert zone_for_point(25.0, 55.0, ZONES) is None


def test_corridor_detour_eligible_different_zones():
    """On-the-way stops batch via corridor even when they fall in different zones."""
    origin = (25.200, 55.270)
    pt_far = (25.225, 55.270)
    pt_on_way = (25.211, 55.270)
    zone_far = zone_for_point(pt_far[0], pt_far[1], SPLIT_ZONES)
    zone_on_way = zone_for_point(pt_on_way[0], pt_on_way[1], SPLIT_ZONES)
    assert zone_far == "North"
    assert zone_on_way == "MidNorth"
    assert zone_far != zone_on_way
    assert same_zone_or_corridor(
        zone_far,
        zone_on_way,
        origin,
        pt_far,
        pt_on_way,
        max_detour_km=0.6,
    )


def test_build_batches_uses_zone_gate_when_zones_configured():
    """Integration: build_batches reads delivery_zones and applies same_zone_or_corridor."""
    from datetime import datetime, timedelta, timezone

    from app.dispatch.batching import OrderCandidate, build_batches

    base = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
    origin = (25.200, 55.270)
    far = OrderCandidate(1, 25.225, 55.270, base, minutes_elapsed=5.0)
    on_way = OrderCandidate(
        2, 25.211, 55.270, base + timedelta(seconds=60), minutes_elapsed=5.0
    )
    batches = build_batches(
        [far, on_way],
        proximity_km=0.5,
        origin=origin,
        max_detour_km=0.6,
        delivery_zones=SPLIT_ZONES,
    )
    assert len(batches) == 1
    assert [o.order_id for o in batches[0].orders] == [2, 1]


def test_corridor_detour_rejected_off_route():
    """A lateral stop fails corridor eligibility when detour exceeds the cap."""
    origin = (25.200, 55.270)
    pt_north = (25.225, 55.270)
    pt_east = (25.205, 55.300)
    assert same_zone_or_corridor(
        None,
        None,
        origin,
        pt_north,
        pt_east,
        max_detour_km=0.6,
    ) is False