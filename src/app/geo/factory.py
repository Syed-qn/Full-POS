from functools import lru_cache

from app.config import get_settings
from app.geo.fake import FakeGeoProvider
from app.geo.port import GeoPort


@lru_cache
def get_geo_provider() -> GeoPort:
    """FastAPI/Celery dependency. Returns FakeGeoProvider or GoogleMapsGeoProvider.

    Selection: google_maps only when geo_provider == "google_maps" AND an API
    key is configured; otherwise the haversine-backed FakeGeoProvider.
    """
    settings = get_settings()
    if settings.geo_provider == "google_maps":
        if not settings.google_maps_api_key.get_secret_value():
            raise ValueError(
                "geo_provider='google_maps' requires APP_GOOGLE_MAPS_API_KEY"
            )
        from app.geo.google_maps import GoogleMapsGeoProvider

        return GoogleMapsGeoProvider()
    if settings.geo_provider == "fake":
        return FakeGeoProvider()
    raise ValueError(f"Unknown geo_provider: {settings.geo_provider!r}")
