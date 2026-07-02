"""Regression tests for the chat engine's road-distance helper.

Guards a bug where the engine called a non-existent ``provider.distance(...)``
method, so the ``except`` always fired and the customer-quoted distance/fee
silently fell back to straight-line haversine — making APP_GEO_PROVIDER=google_maps
have zero effect on what customers were charged. The helper must:
  1. call the configured GeoPort's real ``distance_km`` (road distance when google_maps), and
  2. degrade to haversine only when the provider raises.
"""
import app.geo.factory as factory
from app.conversation.engine import _road_distance_km
from app.geo.haversine import distance_km as haversine_km

# Dubai-ish coords ~0.8 km apart by straight line.
A = (25.2048, 55.2708)
B = (25.2100, 55.2750)


class _StubProvider:
    """GeoPort stub returning a sentinel distance unmistakably unlike haversine."""

    SENTINEL = 42.0

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def distance_km(self, lat1, lon1, lat2, lon2) -> float:
        self.calls.append((lat1, lon1, lat2, lon2))
        return self.SENTINEL


class _BrokenProvider:
    def distance_km(self, *args) -> float:
        raise RuntimeError("Routes API down")


async def test_road_distance_uses_geo_provider(monkeypatch):
    """The helper must return the provider's distance (road), not haversine."""
    stub = _StubProvider()
    monkeypatch.setattr(factory, "get_geo_provider", lambda: stub)

    dist, source = await _road_distance_km(A[0], A[1], B[0], B[1])

    assert dist == _StubProvider.SENTINEL  # provider was used, not haversine
    assert source == "road"
    assert stub.calls == [(A[0], A[1], B[0], B[1])]  # exact origin→dest order


async def test_road_distance_falls_back_to_haversine_on_provider_error(monkeypatch):
    """A provider/config failure must never break ordering — degrade to haversine."""
    monkeypatch.setattr(factory, "get_geo_provider", lambda: _BrokenProvider())

    dist, source = await _road_distance_km(A[0], A[1], B[0], B[1])

    assert dist == haversine_km(A[0], A[1], B[0], B[1])
    assert source == "haversine_fallback"
