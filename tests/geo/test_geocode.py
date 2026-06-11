"""Unit tests for the FakeGeoProvider gazetteer geocoder + Redis cache."""
import json

from app.geo.fake import FakeGeoProvider

geo = FakeGeoProvider()


class _FakeRedis:
    """Minimal async Redis stub for the read-through cache test."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


def test_known_area_resolves():
    assert geo.geocode("Karama, building 7") == (25.2450, 55.3050)
    assert geo.geocode("deliver to Jebel Ali please") == (25.0107, 55.1326)


def test_longest_match_wins():
    # "mall of the emirates" must beat any shorter substring match.
    assert geo.geocode("near Mall of the Emirates") == (25.1180, 55.2000)


def test_case_insensitive():
    assert geo.geocode("DOWNTOWN") == geo.geocode("downtown")


def test_unknown_returns_none():
    assert geo.geocode("al salam street 2nd street door number 6") is None
    assert geo.geocode("") is None


def test_fuzzy_typo_resolves():
    # "Jabel ali" (misspelled Jebel Ali) still resolves.
    assert geo.geocode("45 Jabel ali dubai") == (25.0107, 55.1326)
    assert geo.geocode("kerama building 3") == (25.2450, 55.3050)  # Karama typo


async def test_geocode_cache_read_through():
    from app.geo import cache

    fake = _FakeRedis()
    cache.set_geocode_redis(fake)
    try:
        # MISS → provider geocodes and the result is written to the cache.
        assert await cache.geocode_cached("Karama") == (25.2450, 55.3050)
        assert fake.store, "positive result should be cached"

        # HIT → returns the cached value WITHOUT calling the provider (proved by
        # overwriting the cache with a sentinel the provider would never return).
        fake.store[cache._key("Karama")] = json.dumps([1.0, 2.0])
        assert await cache.geocode_cached("karama  ") == (1.0, 2.0)  # normalized key
    finally:
        cache.set_geocode_redis(None)   # never leak the stub into other tests


def test_factory_falls_back_when_google_key_missing():
    """Flipping the provider to google_maps before the key lands must NOT crash —
    it degrades to the offline FakeGeoProvider until the key is added + restarted."""
    from unittest.mock import patch

    import app.geo.factory as factory

    class _Settings:
        geo_provider = "google_maps"

        class google_maps_api_key:
            @staticmethod
            def get_secret_value() -> str:
                return ""  # no key configured yet

    factory.get_geo_provider.cache_clear()
    try:
        with patch.object(factory, "get_settings", lambda: _Settings):
            provider = factory.get_geo_provider()
        assert isinstance(provider, FakeGeoProvider)
    finally:
        factory.get_geo_provider.cache_clear()


def test_factory_uses_google_when_key_present():
    from unittest.mock import patch

    import app.geo.factory as factory

    class _Settings:
        geo_provider = "google_maps"

        class google_maps_api_key:
            @staticmethod
            def get_secret_value() -> str:
                return "test-key-not-called"

    factory.get_geo_provider.cache_clear()
    try:
        with patch.object(factory, "get_settings", lambda: _Settings):
            provider = factory.get_geo_provider()
        # Real provider selected (constructor reads the key, makes no network call).
        assert type(provider).__name__ == "GoogleMapsGeoProvider"
    finally:
        factory.get_geo_provider.cache_clear()


async def test_geocode_cache_degrades_without_redis():
    from app.geo import cache

    cache.set_geocode_redis(None)
    # No Redis → calls the provider directly, still works.
    assert await cache.geocode_cached("Karama") == (25.2450, 55.3050)
    assert await cache.geocode_cached("nowhere-ville") is None
