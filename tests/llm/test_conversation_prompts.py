"""Tests for conversation_prompts SSOT (E-02, E-12, E-23, E-04)."""
from __future__ import annotations

import pytest

from app.llm import action_schema as A
from app.llm import conversation_prompts as P

_REQUIRED_SECTION_TAGS = (
    "[ROLE]",
    "[CONTEXT]",
    "[INTENT]",
    "[TASK]",
    "[INPUT]",
    "[INSTRUCTIONS]",
    "[CONSTRAINTS]",
    "[TONE]",
    "[OUTPUT]",
    "[EXAMPLES]",
    "[META_LANGUAGE]",
)


def _all_template_text() -> str:
    return "\n".join(
        (
            P.IDENTITY_TEMPLATE,
            P.INTENT_BLOCK,
            P.META_LANGUAGE_BLOCK,
            P.ORDERING_BLOCK_TEMPLATE,
            P.ADDRESS_BLOCK_TEMPLATE,
            P.CONFIRMATION_BLOCK_TEMPLATE,
            P.POST_ORDER_BLOCK_TEMPLATE,
            P.CLAUDE_CONVERSATION_SYSTEM,
            P.CLAUDE_POST_ORDER_GUIDANCE,
        )
    )


def test_master_prompt_section_tags_present():
    blob = _all_template_text()
    for tag in _REQUIRED_SECTION_TAGS:
        assert tag in blob, f"missing section tag {tag}"


def test_intent_block_present_and_has_e23_goals():
    assert "[INTENT]" in P.INTENT_BLOCK
    low = P.INTENT_BLOCK.lower()
    assert "primary" in low
    assert "secondary" in low
    assert "never optimize" in low
    assert "escalate" in low
    assert "40-minute" in low or "40 minute" in low


def test_build_identity_formats_without_key_error():
    ctx = {
        "max_radius_km": 8,
        "restaurant_location": "Burj Khalifa, Dubai",
        "delivery_info": "3 km: AED 5",
        "hours_info": "Open now",
        "restaurant_phone": "+971500000000",
    }
    out = P.build_identity("Spice Garden", ctx)
    assert "Spice Garden" in out
    assert "[INTENT]" in out
    assert "[META_LANGUAGE]" in out
    assert "8" in out


@pytest.mark.parametrize(
    "phase,extra",
    [
        (
            "ordering",
            {
                "menu_text": "1. Biryani AED 28",
                "cart_summary": "1x Biryani",
                "cart_lines": [{"cart_item_id": "c1", "dish": "Biryani", "qty": 1}],
            },
        ),
        (
            "address_capture",
            {
                "saved_address": "Tower A, 101",
                "location_received": True,
                "apt_room": "101",
                "building": "Tower A",
                "receiver_name": "Ali",
            },
        ),
        ("awaiting_confirmation", {"order_summary": "1x Biryani — AED 28"}),
        (
            "post_order",
            {
                "order_number": "42",
                "order_status": "preparing",
                "rider_eta": "25",
            },
        ),
    ],
)
def test_build_phase_block_formats_without_key_error(phase: str, extra: dict):
    ctx = {"max_radius_km": 10, "restaurant_name": "Spice Garden", **extra}
    out = P.build_phase_block(phase, ctx)
    assert out
    assert "[TASK]" in out
    if phase != "ordering":
        assert "[ROLE]" in out


def test_reply_field_description_strengthened_e04():
    desc = A.build_tool_properties()["reply"]["description"].lower()
    assert "tone-only" in desc
    assert "max 1 short sentence" in desc
    assert "never list dishes" in desc
    assert "engine renders authoritative" in desc