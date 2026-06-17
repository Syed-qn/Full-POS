from functools import lru_cache

from app.config import get_settings
from app.whatsapp.mock_provider import MockProvider


@lru_cache
def _get_mock_provider() -> MockProvider:
    """Singleton MockProvider shared across the process — enables simulator access."""
    return MockProvider()


def get_whatsapp_provider():
    """FastAPI dependency. Returns MockProvider (singleton) or CloudAPIProvider."""
    settings = get_settings()
    if settings.whatsapp_provider == "cloud":
        from app.whatsapp.cloud_provider import CloudAPIProvider

        return CloudAPIProvider()
    if settings.whatsapp_provider == "mock":
        return _get_mock_provider()
    raise ValueError(f"Unknown whatsapp_provider: {settings.whatsapp_provider!r}")


def get_mock_provider() -> MockProvider:
    """Direct access to MockProvider singleton — used by simulator router."""
    return _get_mock_provider()
