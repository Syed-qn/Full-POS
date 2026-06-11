import logging
from functools import lru_cache

from app.config import get_settings
from app.geo.fake import FakeGeoProvider
from app.geo.port import GeoPort

logger = logging.getLogger(__name__)


@lru_cache
def get_geo_provider() -> GeoPort:
    """FastAPI/Celery dependency. Returns FakeGeoProvider or GoogleMapsGeoProvider.

    Selection: google_maps when geo_provider == "google_maps" AND an API key is
    configured; otherwise the haversine-backed FakeGeoProvider.

    Missing-key fallback: if google_maps is selected but no key is set yet, log a
    warning and fall back to the offline FakeGeoProvider instead of crashing the
    address flow. This lets the provider be flipped to google_maps ahead of the
    key landing — real geocoding activates automatically once the key is added and
    the process restarts, with no broken window in between.
    """
    settings = get_settings()
    if settings.geo_provider == "google_maps":
        if not settings.google_maps_api_key.get_secret_value():
            logger.warning(
                "geo_provider='google_maps' but APP_GOOGLE_MAPS_API_KEY is empty; "
                "falling back to offline FakeGeoProvider. Add the key and restart "
                "to enable real street-level geocoding."
            )
            return FakeGeoProvider()
        from app.geo.google_maps import GoogleMapsGeoProvider

        return GoogleMapsGeoProvider()
    if settings.geo_provider == "fake":
        return FakeGeoProvider()
    raise ValueError(f"Unknown geo_provider: {settings.geo_provider!r}")
