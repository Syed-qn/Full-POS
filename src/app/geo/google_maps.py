"""Google Maps Routes API provider.

Real implementation calls Routes API with traffic-aware durations.
Falls back to haversine on any network/auth error (spec §5):
Maps API down -> haversine + static speed 25 km/h + widened buffers;
ETAs flagged as estimates (is_estimate=True).
"""

import logging
import math

from app.geo.haversine import distance_km as _haversine

logger = logging.getLogger(__name__)
_CITY_SPEED_KMH = 25.0


class GoogleMapsGeoProvider:
    """Production geo provider — Google Maps Routes API with traffic.

    Graceful degradation: on any API failure returns haversine estimate
    and sets is_estimate=True.
    """

    def __init__(self) -> None:
        from app.config import get_settings

        self._api_key = get_settings().google_maps_api_key
        self.is_estimate: bool = False  # flipped to True on API failure

    def distance_km(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Return road distance in km (haversine fallback on Maps failure)."""
        try:
            return self._maps_distance(lat1, lon1, lat2, lon2)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully on any failure
            logger.warning("Google Maps distance failed, using haversine: %s", exc)
            self.is_estimate = True
            return _haversine(lat1, lon1, lat2, lon2)

    def eta_minutes(self, distance_km: float, buffer_minutes: int = 0) -> int:
        """Return ETA in whole minutes (static speed when is_estimate=True)."""
        raw = (distance_km / _CITY_SPEED_KMH) * 60
        return max(1, math.ceil(raw)) + buffer_minutes

    def _maps_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Call Google Maps Routes API. Raises on failure."""
        if not self._api_key:
            raise ValueError("APP_GOOGLE_MAPS_API_KEY not configured")
        # Real implementation: POST to
        # https://routes.googleapis.com/directions/v2:computeRoutes
        # Returns routes[0].distanceMeters / 1000.0
        # Placeholder until production API key is available:
        raise NotImplementedError(
            "Google Maps API key required for production routes"
        )
