"""Manual delivery zones and corridor eligibility for batching."""

from __future__ import annotations

from app.geo.haversine import distance_km


def zone_for_point(lat: float, lon: float, zones: list[dict]) -> str | None:
    """Return the name of the first zone whose radius contains ``(lat, lon)``."""
    for zone in zones:
        center_lat = zone["center_lat"]
        center_lng = zone["center_lng"]
        radius_km = zone["radius_km"]
        if distance_km(lat, lon, center_lat, center_lng) <= radius_km:
            return zone["name"]
    return None


def _insertion_detour_km(
    origin: tuple[float, float],
    stops: list[tuple[float, float]],
    candidate: tuple[float, float],
) -> float:
    """Extra travel km to fold ``candidate`` into a route from ``origin`` through ``stops``."""
    pts = [origin] + stops
    best: float | None = None
    for i, a in enumerate(pts):
        if i + 1 < len(pts):
            b = pts[i + 1]
            extra = (
                distance_km(a[0], a[1], candidate[0], candidate[1])
                + distance_km(candidate[0], candidate[1], b[0], b[1])
                - distance_km(a[0], a[1], b[0], b[1])
            )
        else:
            extra = distance_km(a[0], a[1], candidate[0], candidate[1])
        best = extra if best is None else min(best, extra)
    return max(0.0, best or 0.0)


def same_zone_or_corridor(
    zone_a: str | None,
    zone_b: str | None,
    origin: tuple[float, float],
    pt_a: tuple[float, float],
    pt_b: tuple[float, float],
    max_detour_km: float,
) -> bool:
    """True when both stops share a zone or corridor insertion detour is within the cap."""
    if zone_a is not None and zone_a == zone_b:
        return True
    if max_detour_km <= 0:
        return False
    detour_ab = _insertion_detour_km(origin, [pt_a], pt_b)
    detour_ba = _insertion_detour_km(origin, [pt_b], pt_a)
    return min(detour_ab, detour_ba) <= max_detour_km