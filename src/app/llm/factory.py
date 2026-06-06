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
