"""Google Maps Routes API provider.

Real implementation calls Routes API with traffic-aware durations.
Falls back to haversine on any network/auth error (spec §5):
Maps API down -> haversine + static speed 25 km/h + widened buffers;
ETAs flagged as estimates (is_estimate=True).
"""

import logging
import math

import httpx

from app.geo.haversine import distance_km as _haversine

logger = logging.getLogger(__name__)
_CITY_SPEED_KMH = 25.0

_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
_FIELD_MASK = "routes.distanceMeters,routes.duration"


class GoogleMapsGeoProvider:
    """Production geo provider — Google Maps Routes API with traffic.

    Graceful degradation: on any API failure returns haversine estimate
    and sets is_estimate=True.
    """

    def __init__(self) -> None:
        from app.config import get_settings

        self._api_key = get_settings().google_maps_api_key.get_secret_value()
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
        """Call Google Maps Routes API (traffic-aware). Raises on any failure for graceful fallback."""
        if not self._api_key:
            raise ValueError("APP_GOOGLE_MAPS_API_KEY not configured")

        headers = {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": _FIELD_MASK,
            "Content-Type": "application/json",
        }
        body = {
            "origin": {
                "location": {"latLng": {"latitude": lat1, "longitude": lon1}}
            },
            "destination": {
                "location": {"latLng": {"latitude": lat2, "longitude": lon2}}
            },
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(_ROUTES_URL, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        routes = data.get("routes") or []
        if not routes:
            raise ValueError("No routes returned by Google Maps")
        route = routes[0]
        meters = float(route.get("distanceMeters", 0))
        if meters <= 0:
            raise ValueError("Invalid distance from Google Maps")
        return meters / 1000.0
