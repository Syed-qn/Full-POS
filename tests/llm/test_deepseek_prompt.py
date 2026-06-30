import pytest


@pytest.fixture(autouse=True)
def _ds_env(monkeypatch):
    monkeypatch.setenv("APP_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("APP_DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("APP_DEEPSEEK_MODEL", "deepseek-chat")


def test_ordering_prompt_has_completion_first_decision():
    from app.config import get_settings
    get_settings.cache_clear()
    from app.llm.deepseek import DeepSeekConversationAgent
    agent = DeepSeekConversationAgent()
    sys = agent._build_system("Testaurant", "ordering",
                              {"menu_text": "1. Lemon mint", "cart_summary": "1x Lemon mint"})
    low = sys.lower()

    # NEW: verify the DECISION ORDER block exists and is structurally ordered correctly.
    completion_pos = sys.find("DECISION ORDER")
    menu_pos = sys.find("MENU / BROWSING")
    assert completion_pos != -1, "DECISION ORDER block missing from ordering prompt"
    assert menu_pos != -1, "MENU / BROWSING section missing from ordering prompt"
    assert completion_pos < menu_pos, "DECISION ORDER must precede MENU / BROWSING"
    assert "STEP 1, COMPLETION" in sys, "STEP 1, COMPLETION marker missing from DECISION ORDER block"

    # Completion decision is evaluated first, language-agnostic.
    assert "proceed_to_address" in sys
    assert "any language" in low
    # Anti-re-add directive present.
    assert "never re-add" in low or "do not re-add" in low


def test_tool_schema_distinguishes_proceed_from_readd():
    from app.config import get_settings
    get_settings.cache_clear()
    from app.llm.deepseek import _DS_TOOL
    action_desc = _DS_TOOL["function"]["parameters"]["properties"]["action"]["description"].lower()
    assert "frustrat" in action_desc or "declines" in action_desc
    assert "never re-add" in action_desc or "not re-add" in action_desc
