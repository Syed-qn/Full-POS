"""Parametrized coverage for every prompt in docs/prompt-inventory.md quick map."""
from __future__ import annotations

import pytest

from app.llm import action_schema as A
from app.llm import complaint_agent
from app.llm import conversation_prompts as P
from app.llm import modify_agent
from app.llm import prompts_kitchen
from app.llm import prompts_marketing
from app.llm import prompts_menu
from app.llm import prompts_router
from app.llm import thought_evaluator

_MIN_TAGS = ("[ROLE]", "[TASK]", "[CONSTRAINTS]", "[OUTPUT]")


def _assert_tags(prompt_id: str, text: str, required: tuple[str, ...]) -> None:
    assert text and text.strip(), f"{prompt_id} is empty"
    for tag in required:
        assert tag in text, f"{prompt_id} missing section tag {tag}"


# Auxiliary / classifier prompts — all four minimum tags required.
_AUXILIARY_PROMPTS: list[tuple[str, str]] = [
    ("prompts_router.ROUTER_CLASSIFY_TEMPLATE", prompts_router.ROUTER_CLASSIFY_TEMPLATE),
    ("prompts_router.COMPLETION_DETECT_TEMPLATE", prompts_router.COMPLETION_DETECT_TEMPLATE),
    ("prompts_menu.EXTRACT_SYSTEM", prompts_menu.EXTRACT_SYSTEM),
    ("prompts_menu.DESCRIBE_DISH_TEMPLATE", prompts_menu.DESCRIBE_DISH_TEMPLATE),
    ("prompts_menu.ARBITRATE_TEMPLATE", prompts_menu.ARBITRATE_TEMPLATE),
    ("prompts_menu.INTENT_CLASSIFY_TEMPLATE", prompts_menu.INTENT_CLASSIFY_TEMPLATE),
    ("prompts_menu.SEGMENT_COMPILE_TEMPLATE", prompts_menu.SEGMENT_COMPILE_TEMPLATE),
    ("prompts_menu.FORECAST_OVERRIDE_TEMPLATE", prompts_menu.FORECAST_OVERRIDE_TEMPLATE),
    ("prompts_kitchen.TIER2_SYSTEM", prompts_kitchen.TIER2_SYSTEM),
    ("prompts_marketing.COPYWRITER_PROMPT", prompts_marketing.COPYWRITER_PROMPT),
    ("complaint_agent._COMPLAINT_SYSTEM", complaint_agent._COMPLAINT_SYSTEM),
    ("modify_agent._MODIFY_SYSTEM", modify_agent._MODIFY_SYSTEM),
    ("thought_evaluator._TOT_SYSTEM", thought_evaluator._TOT_SYSTEM),
]

# conversation_prompts.py — SSOT constants with phase-appropriate tags.
_CONVERSATION_PROMPTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("conversation_prompts.INTENT_BLOCK", P.INTENT_BLOCK, ("[INTENT]",)),
    ("conversation_prompts.META_LANGUAGE_BLOCK", P.META_LANGUAGE_BLOCK, ("[META_LANGUAGE]",)),
    ("conversation_prompts.REPLY_DISCIPLINE", P.REPLY_DISCIPLINE, ("[REPLY_DISCIPLINE]",)),
    ("conversation_prompts.OKF_GROUNDING_RULE", P.OKF_GROUNDING_RULE, ("[OKF_GROUNDING]",)),
    (
        "conversation_prompts.IDENTITY_TEMPLATE",
        P.IDENTITY_TEMPLATE,
        ("[ROLE]", "[CONTEXT]", "[CONSTRAINTS]", "[TONE]", "[OUTPUT]"),
    ),
    (
        "conversation_prompts.ORDERING_BLOCK_TEMPLATE",
        P.ORDERING_BLOCK_TEMPLATE,
        ("[TASK]", "[INPUT]", "[INSTRUCTIONS]", "[CONSTRAINTS]", "[EXAMPLES]"),
    ),
    (
        "conversation_prompts.ADDRESS_BLOCK_TEMPLATE",
        P.ADDRESS_BLOCK_TEMPLATE,
        ("[TASK]", "[INPUT]", "[INSTRUCTIONS]", "[CONSTRAINTS]"),
    ),
    (
        "conversation_prompts.CONFIRMATION_BLOCK_TEMPLATE",
        P.CONFIRMATION_BLOCK_TEMPLATE,
        ("[TASK]", "[INPUT]", "[INSTRUCTIONS]"),
    ),
    (
        "conversation_prompts.POST_ORDER_BLOCK_TEMPLATE",
        P.POST_ORDER_BLOCK_TEMPLATE,
        ("[TASK]", "[INPUT]", "[INSTRUCTIONS]"),
    ),
    (
        "conversation_prompts.CLAUDE_CONVERSATION_SYSTEM",
        P.CLAUDE_CONVERSATION_SYSTEM,
        ("[ROLE]", "[INTENT]", "[META_LANGUAGE]", "[INPUT]", "[CONSTRAINTS]", "[OUTPUT]"),
    ),
    (
        "conversation_prompts.CLAUDE_POST_ORDER_GUIDANCE",
        P.CLAUDE_POST_ORDER_GUIDANCE,
        ("[TASK]", "[INPUT]", "[INSTRUCTIONS]"),
    ),
]


@pytest.mark.parametrize("prompt_id,text", _AUXILIARY_PROMPTS)
def test_auxiliary_prompt_has_minimum_section_tags(prompt_id: str, text: str) -> None:
    _assert_tags(prompt_id, text, _MIN_TAGS)


@pytest.mark.parametrize("prompt_id,text,required_tags", _CONVERSATION_PROMPTS)
def test_conversation_prompt_section_tags(
    prompt_id: str, text: str, required_tags: tuple[str, ...],
) -> None:
    _assert_tags(prompt_id, text, required_tags)


def test_reply_field_description_non_empty_and_wired_to_action_schema() -> None:
    assert P.REPLY_FIELD_DESCRIPTION.strip()
    props = A.build_tool_properties()
    assert props["reply"]["description"] == P.REPLY_FIELD_DESCRIPTION


def test_build_identity_includes_context_blocks() -> None:
    ctx = {
        "max_radius_km": 5,
        "restaurant_location": "Downtown",
        "delivery_info": "2 km: AED 3",
        "hours_info": "Open",
        "restaurant_phone": "+971500000001",
    }
    out = P.build_identity("Test Kitchen", ctx)
    for tag in ("[ROLE]", "[INTENT]", "[META_LANGUAGE]", "[REPLY_DISCIPLINE]", "[OKF_GROUNDING]"):
        assert tag in out


@pytest.mark.parametrize(
    "phase,extra",
    [
        ("ordering", {"menu_text": "1. Biryani", "cart_summary": "empty", "cart_lines": []}),
        ("address_capture", {"saved_address": "", "location_received": False}),
        ("awaiting_confirmation", {"order_summary": "1x Biryani"}),
        ("post_order", {"order_number": "1", "order_status": "preparing", "rider_eta": "20"}),
    ],
)
def test_build_phase_block_non_empty_with_task_tag(phase: str, extra: dict) -> None:
    out = P.build_phase_block(phase, {"max_radius_km": 10, **extra})
    assert "[TASK]" in out


def test_build_claude_system_composes_ssot_blocks() -> None:
    ctx = {
        "max_radius_km": 8,
        "restaurant_location": "Marina",
        "delivery_info": "AED 5",
        "hours_info": "Open",
        "restaurant_phone": "+971500000002",
        "menu_text": "1. Karahi",
        "cart_summary": "empty",
        "cart_lines": [],
        "grounding": "[GROUNDED KNOWLEDGE]\nHalal certified.",
        "session_notes": "Customer prefers mild spice.",
    }
    out = P.build_claude_system("Spice Hub", "address_capture", ctx)
    assert "Spice Hub" in out
    assert "[ROLE]" in out
    assert "[GROUNDED KNOWLEDGE]" in out
    assert "[SESSION_NOTES]" in out
    assert "PHASE: Address capture" in out