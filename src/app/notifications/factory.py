"""Push provider selection. ``APP_PUSH_PROVIDER`` = fake | expo."""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.notifications.fake import FakePushProvider
from app.notifications.port import PushPort


@lru_cache
def _get_fake_provider() -> FakePushProvider:
    """Singleton FakePushProvider so tests can read its ``sent`` list."""
    return FakePushProvider()


def get_push_provider() -> PushPort:
    """FastAPI/Celery dependency. Returns FakePushProvider or ExpoPushProvider."""
    settings = get_settings()
    if settings.push_provider == "expo":
        from app.notifications.expo import ExpoPushProvider

        return ExpoPushProvider()
    if settings.push_provider == "fake":
        return _get_fake_provider()
    raise ValueError(f"Unknown push_provider: {settings.push_provider!r}")


def get_fake_push_provider() -> FakePushProvider:
    """Direct access to the FakePushProvider singleton — used by tests."""
    return _get_fake_provider()
