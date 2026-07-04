import pytest

from app.llm.deepseek import DeepSeekConversationAgent


@pytest.fixture(autouse=True)
def _ds_env(monkeypatch):
    monkeypatch.setenv("APP_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("APP_DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("APP_DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setenv("APP_ANTHROPIC_API_KEY", "test-key")
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


_CART_LINES = [
    {"cart_item_id": 5, "dish": "Chicken Biryani", "variant": None,
     "note": None, "qty": 2, "price": "20"},
]


def test_deepseek_ordering_prompt_carries_cart_lines_and_precedence():
    agent = DeepSeekConversationAgent()
    sys = agent._build_system(
        "Testaurant", "ordering",
        {"menu_text": "1. Chicken Biryani", "cart_summary": "2x Chicken Biryani",
         "cart_lines": _CART_LINES},
    )
    assert "Chicken Biryani" in sys
    assert '"cart_item_id": 5' in sys
    assert "CURRENT CART is correct" in sys


def test_claude_ordering_prompt_carries_cart_lines_and_precedence():
    from app.llm.claude import _phase_guidance
    from app.llm.conversation_prompts import build_claude_system

    sys = build_claude_system(
        "Testaurant",
        "ordering",
        {
            "menu_text": "1. Chicken Biryani",
            "cart_summary": "2x Chicken Biryani",
            "cart_lines": _CART_LINES,
            "delivery_info": "AED 5",
        },
    ) + _phase_guidance("ordering")
    assert '"cart_item_id": 5' in sys
    assert "CURRENT CART is correct" in sys
