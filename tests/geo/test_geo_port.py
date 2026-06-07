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


def test_google_maps_uses_routes_api_and_returns_real_distance(monkeypatch):
    """GoogleMapsGeoProvider calls Routes API and returns traffic-aware distance (is_estimate=False on success)."""
    import os

    from app.config import get_settings

    os.environ["APP_GOOGLE_MAPS_API_KEY"] = "test-key"
    get_settings.cache_clear()  # critical: Settings is lru_cached, env change must invalidate
    from app.geo.google_maps import GoogleMapsGeoProvider

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"routes": [{"distanceMeters": 8500, "duration": "480s"}]}

    def fake_post(self, url, json=None, headers=None, **kw):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return FakeResp()

    # Patch the Client context so no real network
    class FakeClient:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        post = fake_post

    monkeypatch.setattr("httpx.Client", FakeClient)

    provider = GoogleMapsGeoProvider()
    d = provider.distance_km(25.2048, 55.2708, 25.2100, 55.2750)
    assert 8.4 < d < 8.6  # 8500m
    assert provider.is_estimate is False
    assert "routes.googleapis.com" in captured.get("url", "")
    assert captured.get("headers", {}).get("X-Goog-Api-Key") == "test-key"
    assert "routes.distanceMeters" in (captured.get("headers", {}).get("X-Goog-FieldMask") or "")
