from functools import lru_cache

from app.config import get_settings
from app.llm.fake import FakeExtractor
from app.llm.port import MenuExtractor


@lru_cache
def get_menu_extractor() -> MenuExtractor:
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeExtractor

        return ClaudeExtractor()
    elif settings.llm_provider == "fake":
        return FakeExtractor()
    else:
        raise ValueError(f"Unknown llm_provider: {settings.llm_provider!r}")


@lru_cache
def _get_anthropic_client():
    """Cached synchronous Anthropic client for describe/classify/arbitrate ports."""
    from anthropic import Anthropic

    settings = get_settings()
    return Anthropic(api_key=settings.anthropic_api_key.get_secret_value())


def get_describer():
    """FastAPI/test dependency — returns FakeDescriber or ClaudeDescriber."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeDescriber
        return ClaudeDescriber()
    from app.llm.fake import FakeDescriber
    return FakeDescriber()


def get_intent_classifier():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeIntentClassifier
        return ClaudeIntentClassifier()
    from app.llm.fake import FakeIntentClassifier
    return FakeIntentClassifier()


def get_arbiter():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeArbiter
        return ClaudeArbiter()
    from app.llm.fake import FakeArbiter
    return FakeArbiter()


def get_forecast_adjuster():
    """FastAPI/test dependency — returns FakeForecastAdjuster or ClaudeForecastAdjuster."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeForecastAdjuster
        return ClaudeForecastAdjuster()
    from app.llm.fake import FakeForecastAdjuster
    return FakeForecastAdjuster()


def get_segment_compiler():
    """FastAPI/test dependency — returns FakeSegmentCompiler or ClaudeSegmentCompiler."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeSegmentCompiler
        return ClaudeSegmentCompiler()
    from app.llm.fake import FakeSegmentCompiler
    return FakeSegmentCompiler()
