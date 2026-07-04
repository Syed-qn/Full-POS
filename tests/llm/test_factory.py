import pytest

from app.config import get_settings
from app.llm.factory import get_conversation_agent, get_menu_extractor


def _reset():
    get_settings.cache_clear()
    get_menu_extractor.cache_clear()
    # _get_deepseek_settings is lru_cached too — without clearing it, whichever
    # test touched DeepSeek first pins (api_key, model) for the whole session and
    # the fallback-model assertions flake in full-suite order.
    from app.llm.deepseek import _get_deepseek_settings

    _get_deepseek_settings.cache_clear()


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


def test_conversation_wrapped_when_fallback_model_set(monkeypatch):
    """DeepSeek primary model + a distinct fallback model → FallbackConversationAgent
    whose fallback is a second DeepSeek instance on the fallback model. No Claude."""
    from app.llm.fallback import FallbackConversationAgent

    _reset()
    try:
        monkeypatch.setenv("APP_LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("APP_DEEPSEEK_MODEL", "deepseek-v4-flash")
        monkeypatch.setenv("APP_DEEPSEEK_FALLBACK_MODEL", "deepseek-chat")
        monkeypatch.setenv("APP_DEEPSEEK_API_KEY", "ds-test-key")
        _reset()
        agent = get_conversation_agent()
        assert isinstance(agent, FallbackConversationAgent)
        assert agent._primary._model == "deepseek-v4-flash"
        assert agent._fallback._model == "deepseek-chat"
    finally:
        _reset()


def test_conversation_not_wrapped_when_no_fallback_model(monkeypatch):
    """No fallback model → bare DeepSeek agent, no wrapping."""
    from app.llm.deepseek import DeepSeekConversationAgent

    _reset()
    try:
        monkeypatch.setenv("APP_LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("APP_DEEPSEEK_MODEL", "deepseek-v4-flash")
        monkeypatch.setenv("APP_DEEPSEEK_FALLBACK_MODEL", "")
        monkeypatch.setenv("APP_DEEPSEEK_API_KEY", "ds-test-key")
        _reset()
        assert isinstance(get_conversation_agent(), DeepSeekConversationAgent)
    finally:
        _reset()


def test_no_wrap_when_fallback_equals_primary(monkeypatch):
    """A fallback model identical to the primary is a no-op (no pointless wrapper)."""
    from app.llm.deepseek import DeepSeekConversationAgent

    _reset()
    try:
        monkeypatch.setenv("APP_LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("APP_DEEPSEEK_MODEL", "deepseek-v4-flash")
        monkeypatch.setenv("APP_DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-flash")
        monkeypatch.setenv("APP_DEEPSEEK_API_KEY", "ds-test-key")
        _reset()
        assert isinstance(get_conversation_agent(), DeepSeekConversationAgent)
    finally:
        _reset()
