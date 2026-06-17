"""Reverse-geocoding (coords → area label) for grounding the bot's
"where are you located?" answer in the restaurant's real saved coordinates.
"""
import app.geo.cache as cache
from app.geo.fake import FakeGeoProvider
from app.geo.google_maps import _concise_area


# ---- FakeGeoProvider.reverse_geocode (dev/tests) ----

def test_fake_reverse_geocode_nearest_area():
    """A point in Al Karama resolves to the nearest gazetteer area."""
    provider = FakeGeoProvider()
    # ~Al Karama (geocode of "Al Karama, Dubai" earlier returned 25.2489,55.3061)
    assert provider.reverse_geocode(25.2489, 55.3061) == "Karama, Dubai"


def test_fake_reverse_geocode_picks_canonical_alias():
    """Coords shared by an alias return the first (canonical) gazetteer key."""
    provider = FakeGeoProvider()
    # Marina centroid is shared by "dubai marina" (listed first) and "marina".
    assert provider.reverse_geocode(25.0805, 55.1403) == "Dubai Marina, Dubai"


# ---- Google _concise_area parsing ----

def test_concise_area_prefers_sublocality_and_city():
    result = {
        "address_components": [
            {"long_name": "Al Karama", "types": ["sublocality", "political"]},
            {"long_name": "Dubai", "types": ["locality", "political"]},
            {"long_name": "United Arab Emirates", "types": ["country"]},
        ],
        "formatted_address": "Al Karama - Dubai - United Arab Emirates",
    }
    assert _concise_area(result) == "Al Karama, Dubai"


def test_concise_area_falls_back_to_formatted_without_country():
    result = {
        "address_components": [],
        "formatted_address": "Some Street - Dubai - United Arab Emirates",
    }
    # Country segment dropped; first two parts kept.
    assert _concise_area(result) == "Some Street, Dubai"


def test_concise_area_adds_region_for_rural_locality():
    """A bare village (locality, no sublocality) gets its region for context —
    regression: the bot once answered just 'Ilanthaikuttam' with no region."""
    result = {
        "address_components": [
            {"long_name": "FV3X+46", "types": ["plus_code"]},
            {"long_name": "Ilanthaikuttam", "types": ["locality", "political"]},
            {"long_name": "Ramanathapuram", "types": ["administrative_area_level_3"]},
            {"long_name": "Tamil Nadu", "types": ["administrative_area_level_1"]},
            {"long_name": "India", "types": ["country"]},
        ],
        "formatted_address": "FV3X+46 Ilanthaikuttam, Tamil Nadu, India",
    }
    assert _concise_area(result) == "Ilanthaikuttam, Tamil Nadu"


def test_concise_area_strips_plus_code_in_fallback():
    result = {
        "address_components": [],
        "formatted_address": "FV3X+46 Ilanthaikuttam, Tamil Nadu, India",
    }
    assert _concise_area(result) == "Ilanthaikuttam, Tamil Nadu"


# ---- reverse_geocode_cached degrades without Redis ----

class _StubProvider:
    def reverse_geocode(self, lat, lng):
        return "Al Nahda, Dubai"


async def test_reverse_geocode_cached_direct_when_no_redis(monkeypatch):
    """With no Redis client, it calls the provider directly and returns its label."""
    monkeypatch.setattr(cache, "_redis_client", None)
    monkeypatch.setattr(cache, "get_geo_provider", lambda: _StubProvider())

    label = await cache.reverse_geocode_cached(25.30, 55.37)

    assert label == "Al Nahda, Dubai"
