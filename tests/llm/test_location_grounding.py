"""The conversation system prompt must ground the restaurant's location in the
real saved value and forbid the LLM from inventing an area (regression: the bot
once replied "We're in Al Nahda, Dubai" with zero location data — pure guess).
"""
from app.llm.deepseek import DeepSeekConversationAgent


def _build(context: dict) -> str:
    # Bypass __init__ (which needs the DeepSeek API env) — we only test the
    # pure prompt-building method.
    agent = DeepSeekConversationAgent.__new__(DeepSeekConversationAgent)
    return agent._build_system("Biryani House", "ordering", context)


def test_system_prompt_includes_real_location_and_no_invent_rule():
    system = _build(
        {
            "restaurant_location": "Al Karama, Dubai",
            "menu_text": "1. Biryani — AED 20",
            "cart_summary": "",
        }
    )
    assert "Al Karama, Dubai" in system  # the real, grounded location
    assert "NEVER invent" in system  # the anti-hallucination guard


def test_system_prompt_handles_unknown_location():
    system = _build(
        {"restaurant_location": "unknown", "menu_text": "x", "cart_summary": ""}
    )
    # When unknown, the bot is told to offer the pin rather than name an area.
    assert "unknown" in system
    assert "location pin" in system
