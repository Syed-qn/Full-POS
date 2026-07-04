"""Kimi (Moonshot AI) as chat provider through the OpenAI-compat layer.

Kimi K2.6 is fully OpenAI-compatible, so the DeepSeek adapter module serves it
with provider-aware base URL / credentials / sampling:
- base https://api.moonshot.ai/v1 (docs: platform.kimi.ai kimi-k2-6-quickstart)
- temperature/top_p are FIXED by the API (0.6 non-thinking / 1.0 thinking);
  sending custom values errors → payloads must OMIT temperature for kimi.
- thinking mode restricts tool_choice to auto/none → live path sends
  {"thinking": {"type": "disabled"}} and never uses *-thinking models for tools.
"""
import pytest

from app.config import get_settings
from app.llm.factory import get_conversation_agent, get_menu_extractor


def _reset():
    get_settings.cache_clear()
    get_menu_extractor.cache_clear()
    from app.llm import deepseek

    deepseek._get_deepseek_settings.cache_clear()
    deepseek._get_chat_provider.cache_clear()


@pytest.fixture
def kimi_env(monkeypatch):
    _reset()
    monkeypatch.setenv("APP_LLM_PROVIDER", "kimi")
    monkeypatch.setenv("APP_KIMI_API_KEY", "sk-kimi-test")
    monkeypatch.setenv("APP_KIMI_MODEL", "kimi-k2.6")
    monkeypatch.setenv("APP_KIMI_FALLBACK_MODEL", "")
    _reset()
    yield
    _reset()


def test_provider_resolution(kimi_env):
    from app.llm.deepseek import _chat_url, _get_chat_provider, _get_deepseek_settings

    assert _get_chat_provider() == "kimi"
    assert _chat_url() == "https://api.moonshot.ai/v1/chat/completions"
    api_key, model = _get_deepseek_settings()
    assert api_key == "sk-kimi-test"
    assert model == "kimi-k2.6"


def test_conversation_agent_uses_kimi_model(kimi_env):
    from app.llm.deepseek import DeepSeekConversationAgent

    agent = get_conversation_agent()
    assert isinstance(agent, DeepSeekConversationAgent)
    assert agent._model == "kimi-k2.6"


def test_safe_tool_model_kimi_rules(kimi_env):
    from app.llm.deepseek import _safe_tool_model

    # Valid Kimi tool-calling chat models pass through.
    for ok in ("kimi-k2.6", "kimi-k2.5", "kimi-k2-turbo-preview", "kimi-k2-0905-preview"):
        assert _safe_tool_model(ok) == ok
    # Thinking models restrict tool_choice to auto/none — never on the forced-tool path.
    assert _safe_tool_model("kimi-k2-thinking") == "kimi-k2.6"
    assert _safe_tool_model("kimi-k2-thinking-turbo") == "kimi-k2.6"
    # Invented / foreign names downgrade to the known-good default.
    assert _safe_tool_model("kimi-v9-mega") == "kimi-k2.6"
    assert _safe_tool_model("deepseek-chat") == "kimi-k2.6"
    assert _safe_tool_model("") == "kimi-k2.6"


def test_sampling_params_kimi_omits_temperature(kimi_env):
    from app.llm.deepseek import _sampling_params

    params = _sampling_params()
    assert "temperature" not in params  # fixed by Kimi API; custom values 400
    assert params.get("thinking") == {"type": "disabled"}


def test_sampling_params_deepseek_keeps_temperature(monkeypatch):
    _reset()
    try:
        monkeypatch.setenv("APP_LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("APP_DEEPSEEK_API_KEY", "ds-test")
        _reset()
        from app.llm.deepseek import _sampling_params

        params = _sampling_params()
        assert params == {"temperature": 0.0}
    finally:
        _reset()


def test_no_tool_call_salvages_content_as_reply():
    """Provider returns plain content instead of the forced tool call → engine
    still gets a usable no_action reply, never a crash into the canned error."""
    from app.llm.deepseek import _parse_tool_response

    data = {
        "choices": [
            {"message": {"content": "We store your phone and orders 😊", "tool_calls": []}}
        ]
    }
    out = _parse_tool_response(data, "take_action")
    assert out["action"] == "no_action"
    assert "phone" in out["reply"]


def test_kimi_fallback_model_wraps_agent(monkeypatch):
    from app.llm.fallback import FallbackConversationAgent

    _reset()
    try:
        monkeypatch.setenv("APP_LLM_PROVIDER", "kimi")
        monkeypatch.setenv("APP_KIMI_API_KEY", "sk-kimi-test")
        monkeypatch.setenv("APP_KIMI_MODEL", "kimi-k2.6")
        monkeypatch.setenv("APP_KIMI_FALLBACK_MODEL", "kimi-k2-turbo-preview")
        _reset()
        agent = get_conversation_agent()
        assert isinstance(agent, FallbackConversationAgent)
        assert agent._primary._model == "kimi-k2.6"
        assert agent._fallback._model == "kimi-k2-turbo-preview"
    finally:
        _reset()
