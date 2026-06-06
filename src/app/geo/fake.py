import math

from app.geo.haversine import distance_km as _haversine

_CITY_SPEED_KMH = 25.0


class FakeGeoProvider:
    """Haversine-backed provider for tests and Maps-API-down fallback.

    Uses static city speed 25 km/h.  is_estimate = True always.
    """

    is_estimate: bool = True

    def distance_km(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        return _haversine(lat1, lon1, lat2, lon2)

    def eta_minutes(self, distance_km: float, buffer_minutes: int = 0) -> int:
        raw = (distance_km / _CITY_SPEED_KMH) * 60
        return max(1, math.ceil(raw)) + buffer_minutes
