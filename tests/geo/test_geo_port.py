from app.geo.fake import FakeGeoProvider
from app.geo.port import GeoPort


def test_fake_distance_matches_haversine():
    """FakeGeoProvider.distance_km delegates to haversine."""
    provider = FakeGeoProvider()
    d = provider.distance_km(25.2048, 55.2708, 25.2100, 55.2750)
    assert 0.5 < d < 1.5  # ~0.8 km


def test_fake_eta_minutes_uses_static_speed():
    """ETA = distance / 25 km/h in minutes, rounded up, minimum 1."""
    provider = FakeGeoProvider()
    # 5 km at 25 km/h = 12 min
    eta = provider.eta_minutes(5.0)
    assert eta == 12


def test_fake_eta_minimum_1_minute():
    provider = FakeGeoProvider()
    eta = provider.eta_minutes(0.1)
    assert eta >= 1


def test_fake_provider_satisfies_protocol():
    """FakeGeoProvider structurally satisfies GeoPort."""
    p: GeoPort = FakeGeoProvider()
    assert callable(p.distance_km)
    assert callable(p.eta_minutes)
    assert hasattr(p, "is_estimate")
    assert p.is_estimate is True


def test_google_maps_provider_instantiates_without_network():
    """GoogleMapsGeoProvider can be constructed without making network calls."""
    import os

    os.environ.setdefault("APP_GOOGLE_MAPS_API_KEY", "")
    from app.geo.google_maps import GoogleMapsGeoProvider

    provider = GoogleMapsGeoProvider()
    assert provider is not None
