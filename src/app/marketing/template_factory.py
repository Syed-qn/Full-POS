"""Factory for the TemplatePort — env-driven, ``lru_cache`` like sibling factories.

Returns ``MockTemplateProvider`` when ``marketing_template_provider == "mock"``
OR ``marketing_send_dry_run`` is True; otherwise ``MetaTemplateProvider``.
FastAPI / worker dependency.
"""
from functools import lru_cache

from app.config import get_settings
from app.marketing.template_mock import MockTemplateProvider
from app.marketing.template_port import TemplatePort


@lru_cache
def _get_mock_template_provider() -> MockTemplateProvider:
    """Singleton MockTemplateProvider shared across the process."""
    return MockTemplateProvider()


def get_template_provider() -> TemplatePort:
    settings = get_settings()
    if settings.marketing_send_dry_run or settings.marketing_template_provider == "mock":
        return _get_mock_template_provider()
    if settings.marketing_template_provider == "meta":
        from app.marketing.template_meta import MetaTemplateProvider

        return MetaTemplateProvider()
    raise ValueError(
        f"Unknown marketing_template_provider: {settings.marketing_template_provider!r}"
    )
