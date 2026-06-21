import pytest

from app.config import get_settings
from app.llm.factory import get_menu_extractor


def _reset():
    get_settings.cache_clear()
    get_menu_extractor.cache_clear()


def test_unknown_extractor_provider_raises(monkeypatch):
    _reset()
    try:
        monkeypatch.setenv("APP_MENU_EXTRACTOR_PROVIDER", "openai")
        _reset()
        with pytest.raises(ValueError, match="Unknown menu extractor provider"):
            get_menu_extractor()
    finally:
        _reset()


def test_auto_prefers_claude_when_anthropic_key_present(monkeypatch):
    """Menus are PDFs/images — auto routes to the multimodal Claude extractor when
    an Anthropic key is set, even if the chat provider is DeepSeek."""
    from app.llm.claude import ClaudeExtractor

    _reset()
    try:
        monkeypatch.setenv("APP_MENU_EXTRACTOR_PROVIDER", "auto")
        monkeypatch.setenv("APP_ANTHROPIC_API_KEY", "sk-test-key")
        monkeypatch.setenv("APP_LLM_PROVIDER", "deepseek")
        _reset()
        assert isinstance(get_menu_extractor(), ClaudeExtractor)
    finally:
        _reset()


def test_auto_falls_back_to_chat_provider_without_key(monkeypatch):
    from app.llm.fake import FakeExtractor

    _reset()
    try:
        monkeypatch.setenv("APP_MENU_EXTRACTOR_PROVIDER", "auto")
        monkeypatch.setenv("APP_ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("APP_LLM_PROVIDER", "fake")
        _reset()
        assert isinstance(get_menu_extractor(), FakeExtractor)
    finally:
        _reset()
