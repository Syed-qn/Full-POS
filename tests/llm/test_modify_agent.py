"""E-10 order-modify sub-agent prompt helpers + parsing."""

import pytest

from app.llm.modify_agent import (
    build_modify_prompt,
    format_proposed_lines,
    parse_modify_response,
)


def test_build_modify_prompt_includes_all_sections():
    prompt = build_modify_prompt(
        "Order #7: 1x Biryani",
        "2x Karahi @ AED 45",
        "please change my order",
    )
    assert "ORDER CONTEXT" in prompt
    assert "PROPOSED CHANGES" in prompt
    assert "CHAT SNIPPET" in prompt
    assert "Biryani" in prompt
    assert "Karahi" in prompt
    assert '"summary"' in prompt


def test_format_proposed_lines():
    proposed = [{"qty": 2, "name": "Karahi", "price_aed": "45"}]
    text = format_proposed_lines(proposed)
    assert "2x Karahi" in text
    assert "AED 45" in text
    assert format_proposed_lines([]) == "(empty)"


def test_parse_modify_response_json():
    raw = (
        '{"summary": "Added karahi.", "change_count": 1, '
        '"suggested_action": "confirm_modify"}'
    )
    out = parse_modify_response(raw)
    assert out == {
        "summary": "Added karahi.",
        "change_count": 1,
        "suggested_action": "confirm_modify",
    }


def test_parse_modify_response_invalid_action_defaults():
    raw = '{"summary": "Unclear.", "change_count": 0, "suggested_action": "refund"}'
    out = parse_modify_response(raw)
    assert out["suggested_action"] == "clarify_with_customer"


def test_parse_modify_response_rejects_non_json():
    with pytest.raises(ValueError, match="non-JSON"):
        parse_modify_response("not json")


def test_parse_modify_response_negative_change_count_clamped():
    raw = '{"summary": "Change.", "change_count": -3, "suggested_action": "confirm_modify"}'
    out = parse_modify_response(raw)
    assert out["change_count"] == 0