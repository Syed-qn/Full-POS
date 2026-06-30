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

    # Completion action must be taught with its canonical name.
    assert "checkout_proceed" in sys, "checkout_proceed canonical action missing from ordering prompt"
    assert "any language" in low
    # Anti-re-add directive present.
    assert "never re-add" in low or "do not re-add" in low


def test_tool_schema_distinguishes_proceed_from_readd():
    """Behavioral constraints (frustration/re-add) must be in the ordering system prompt.

    After W1 Task 2, the tool schema action description is minimal (no inline doc);
    the full behavioral guidance lives in _ORDERING_BLOCK where it belongs.
    """
    from app.config import get_settings
    get_settings.cache_clear()
    from app.llm.deepseek import DeepSeekConversationAgent, _DS_TOOL
    agent = DeepSeekConversationAgent()
    sys_prompt = agent._build_system(
        "Testaurant", "ordering",
        {"menu_text": "1. Lemon mint", "cart_summary": "1x Lemon mint"},
    ).lower()

    # The tool schema should enumerate canonical actions, not legacy ones.
    action_enum = set(_DS_TOOL["function"]["parameters"]["properties"]["action"]["enum"])
    assert "checkout_proceed" in action_enum, "canonical checkout_proceed must be in tool enum"
    assert "proceed_to_address" not in action_enum, "legacy proceed_to_address must NOT be in tool enum"
    assert "add_item" not in action_enum, "legacy add_item must NOT be in tool enum"

    # Behavioral constraints must appear in the ordering system prompt.
    assert "frustrat" in sys_prompt or "declines" in sys_prompt, (
        "Frustration/decline handling must be in the ordering prompt"
    )
    assert "never re-add" in sys_prompt or "not re-add" in sys_prompt or "do not re-add" in sys_prompt, (
        "Anti-re-add directive must be in the ordering prompt"
    )
