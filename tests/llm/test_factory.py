import pytest

from app.config import get_settings
from app.llm.factory import get_menu_extractor


def test_unknown_provider_raises(monkeypatch):
    get_settings.cache_clear()
    get_menu_extractor.cache_clear()
    try:
        monkeypatch.setenv("APP_LLM_PROVIDER", "openai")
        get_settings.cache_clear()
        get_menu_extractor.cache_clear()
        with pytest.raises(ValueError, match="Unknown llm_provider"):
            get_menu_extractor()
    finally:
        get_settings.cache_clear()
        get_menu_extractor.cache_clear()
