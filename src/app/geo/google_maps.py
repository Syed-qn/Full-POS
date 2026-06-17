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
_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Address-component types, most→least specific, used to build an "Area, City"
# label from a Google reverse-geocode result. "Specific" = the place name a
# human would say; "broader" = the region that gives it context (so a bare
# village name like "Ilanthaikuttam" becomes "Ilanthaikuttam, Tamil Nadu").
_SPECIFIC_TYPES = ("sublocality", "neighborhood", "locality", "route")
_BROADER_TYPES = (
    "locality",
    "administrative_area_level_2",
    "administrative_area_level_1",
)


def _component(components: list[dict], wanted: tuple[str, ...]) -> str | None:
    """Return the first component whose types include any of ``wanted``."""
    for t in wanted:
        for c in components:
            if t in c.get("types", []):
                return c.get("long_name")
    return None


def _strip_plus_code(formatted: str) -> str:
    """Drop a leading Google plus-code token (e.g. 'FV3X+46 Ilanthaikuttam')."""
    head, _, rest = formatted.partition(" ")
    return rest if ("+" in head and rest) else formatted


def _concise_area(result: dict) -> str | None:
    """Build a human "Place, Region" label from a Google geocode result.

    Always pairs the specific place with a broader region when possible, so the
    bot's location answer reads naturally in both dense cities ("Al Karama,
    Dubai") and rural areas ("Ilanthaikuttam, Tamil Nadu"). Falls back to the
    formatted address (sans plus code + country) when components are absent.
    """
    components = result.get("address_components") or []
    specific = _component(components, _SPECIFIC_TYPES)
    # Broader region that differs from the specific name.
    broader: str | None = None
    for t in _BROADER_TYPES:
        val = _component(components, (t,))
        if val and val != specific:
            broader = val
            break

    if specific and broader:
        return f"{specific}, {broader}"
    if specific:
        return specific
    if broader:
        return broader

    formatted = result.get("formatted_address")
    if formatted:
        formatted = _strip_plus_code(formatted)
        # Normalise " - " separators, drop the trailing country segment.
        parts = [p.strip() for p in formatted.replace(" - ", ",").split(",") if p.strip()]
        return ", ".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else None)
    return None


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

    def geocode(self, address: str) -> tuple[float, float] | None:
        """Geocode a free-text address via the Google Geocoding API.

        Biased to the UAE. Returns ``(lat, lng)`` for the top result, or None on
        no match / any API failure (caller then asks for a location pin).
        """
        if not self._api_key or not address:
            return None
        try:
            params = {
                "address": address,
                "key": self._api_key,
                "region": "ae",
                "components": "country:AE",
            }
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(_GEOCODE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or []
            if not results:
                return None
            loc = results[0]["geometry"]["location"]
            return (float(loc["lat"]), float(loc["lng"]))
        except Exception as exc:  # noqa: BLE001 - degrade gracefully on any failure
            logger.warning("Google geocode failed for %r: %s", address, exc)
            return None

    def reverse_geocode(self, lat: float, lng: float) -> str | None:
        """Reverse-geocode coordinates to a concise "Area, City" label via Google.

        Returns e.g. "Al Karama, Dubai" by preferring the sublocality/neighborhood
        + city address components; falls back to the top result's formatted
        address (sans country). Returns None on no match / any API failure.
        """
        if not self._api_key:
            return None
        try:
            params = {"latlng": f"{lat},{lng}", "key": self._api_key, "language": "en"}
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(_GEOCODE_URL, params=params)
            resp.raise_for_status()
            results = resp.json().get("results") or []
            if not results:
                return None
            return _concise_area(results[0])
        except Exception as exc:  # noqa: BLE001 - degrade gracefully on any failure
            logger.warning("Google reverse geocode failed for %s,%s: %s", lat, lng, exc)
            return None

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
