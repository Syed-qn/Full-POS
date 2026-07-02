"""Auxiliary prompt modules export expected constants and tagged sections."""

import app.llm.complaint_agent as complaint_agent
import app.llm.modify_agent as modify_agent
import app.llm.prompts_kitchen as prompts_kitchen
import app.llm.prompts_marketing as prompts_marketing
import app.llm.prompts_menu as prompts_menu
import app.llm.prompts_router as prompts_router
import app.llm.thought_evaluator as thought_evaluator

_MIN_TAGS = ("[ROLE]", "[TASK]", "[CONSTRAINTS]", "[OUTPUT]")


def test_prompts_menu_exports():
    assert hasattr(prompts_menu, "EXTRACT_SYSTEM")
    assert hasattr(prompts_menu, "DESCRIBE_DISH_TEMPLATE")
    assert hasattr(prompts_menu, "ARBITRATE_TEMPLATE")
    assert hasattr(prompts_menu, "INTENT_CLASSIFY_TEMPLATE")
    assert hasattr(prompts_menu, "SEGMENT_COMPILE_TEMPLATE")
    assert hasattr(prompts_menu, "FORECAST_OVERRIDE_TEMPLATE")
    for name in (
        "EXTRACT_SYSTEM",
        "DESCRIBE_DISH_TEMPLATE",
        "ARBITRATE_TEMPLATE",
        "INTENT_CLASSIFY_TEMPLATE",
        "SEGMENT_COMPILE_TEMPLATE",
        "FORECAST_OVERRIDE_TEMPLATE",
    ):
        text = getattr(prompts_menu, name)
        assert "[ROLE]" in text
        assert "[TASK]" in text
        assert "[CONSTRAINTS]" in text
        assert "[OUTPUT]" in text


def test_prompts_router_exports():
    assert hasattr(prompts_router, "ROUTER_CLASSIFY_TEMPLATE")
    assert hasattr(prompts_router, "COMPLETION_DETECT_TEMPLATE")
    for name in ("ROUTER_CLASSIFY_TEMPLATE", "COMPLETION_DETECT_TEMPLATE"):
        text = getattr(prompts_router, name)
        assert "[ROLE]" in text
        assert "[TASK]" in text
        assert "[CONSTRAINTS]" in text
        assert "[OUTPUT]" in text


def test_prompts_kitchen_exports():
    assert hasattr(prompts_kitchen, "TIER2_SYSTEM")
    assert hasattr(prompts_kitchen, "build_tier2_user_prompt")
    assert "[ROLE]" in prompts_kitchen.TIER2_SYSTEM
    assert "[TASK]" in prompts_kitchen.TIER2_SYSTEM
    assert "[CONSTRAINTS]" in prompts_kitchen.TIER2_SYSTEM
    assert "[OUTPUT]" in prompts_kitchen.TIER2_SYSTEM
    prompt = prompts_kitchen.build_tier2_user_prompt("1x Biryani", ["ring gate"])
    assert "AUTHORITATIVE BLOCK" in prompt
    assert "ring gate" in prompt


def test_prompts_marketing_exports():
    assert hasattr(prompts_marketing, "COPYWRITER_PROMPT")
    assert "[ROLE]" in prompts_marketing.COPYWRITER_PROMPT
    assert "[TASK]" in prompts_marketing.COPYWRITER_PROMPT
    assert "[CONSTRAINTS]" in prompts_marketing.COPYWRITER_PROMPT
    assert "[OUTPUT]" in prompts_marketing.COPYWRITER_PROMPT
    formatted = prompts_marketing.COPYWRITER_PROMPT.format(
        restaurant="Test Bistro",
        describe="20% off biryani",
    )
    assert "{{1}}" in formatted
    assert "Test Bistro" in formatted


def test_sub_agent_system_prompts_have_minimum_section_tags():
    for name, text in (
        ("_COMPLAINT_SYSTEM", complaint_agent._COMPLAINT_SYSTEM),
        ("_MODIFY_SYSTEM", modify_agent._MODIFY_SYSTEM),
        ("_TOT_SYSTEM", thought_evaluator._TOT_SYSTEM),
    ):
        for tag in _MIN_TAGS:
            assert tag in text, f"{name} missing {tag}"


def test_complaint_build_prompt_and_tot_build_prompt_shapes():
    complaint_prompt = complaint_agent.build_complaint_prompt("Order #1", "cold food")
    assert "ORDER CONTEXT" in complaint_prompt
    assert "CHAT SNIPPET" in complaint_prompt

    tot_prompt = thought_evaluator.build_tot_prompt(
        "maybe biryani?", "ordering", "1x Karahi", ["add", "question", "checkout"],
    )
    assert "Candidates:" in tot_prompt
    assert "maybe biryani?" in tot_prompt