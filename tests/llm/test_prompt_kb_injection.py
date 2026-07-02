"""Prompt KB block is passed through provider system assembly."""

from app.llm.deepseek import DeepSeekConversationAgent


def test_deepseek_system_includes_prompt_kb_block():
    agent = DeepSeekConversationAgent()
    kb = "[PROMPT_KB]\n### [abc] Ordering rules\nNever invent dishes."
    system = agent._build_system(
        "Spice Garden",
        "ordering",
        {
            "max_radius_km": 10,
            "menu_text": "Chicken Biryani AED 20",
            "cart_summary": "empty",
            "cart_lines": [],
            "prompt_kb": kb,
            "grounding": "[GROUNDED KNOWLEDGE]\nDelivery free under 3km.",
        },
    )
    assert "[PROMPT_KB]" in system
    assert "Never invent dishes" in system
    assert "[GROUNDED KNOWLEDGE]" in system
    assert system.index("[PROMPT_KB]") < system.index("[GROUNDED KNOWLEDGE]")