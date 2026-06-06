from typing import Protocol


class GeoPort(Protocol):
    """Distance + ETA provider port.

    Implementations: FakeGeoProvider (haversine + static speed, tests/fallback)
    and GoogleMapsGeoProvider (production, traffic-aware with haversine fallback).
    """

    is_estimate: bool  # True = using haversine fallback (not road/traffic data)

    def distance_km(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Return distance between two points in km."""
        ...

    def eta_minutes(self, distance_km: float, buffer_minutes: int = 0) -> int:
        """Return ETA in whole minutes. buffer_minutes added after calculation."""
        ...
