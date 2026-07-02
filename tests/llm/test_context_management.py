"""Prompt context blocks and SSOT builder composition (E-04, E-06, E-20)."""

from app.llm import conversation_prompts as P


def test_meta_language_block_documents_cart_and_catalog_prefixes() -> None:
    text = P.META_LANGUAGE_BLOCK.lower()
    assert "[META_LANGUAGE]" in P.META_LANGUAGE_BLOCK
    assert "[cart updated]" in text
    assert "[catalog]" in text
    assert "[tapped:" in text


def test_okf_grounding_rule_requires_citation_and_no_invention() -> None:
    text = P.OKF_GROUNDING_RULE.lower()
    assert "[OKF_GROUNDING]" in P.OKF_GROUNDING_RULE
    assert "grounded knowledge" in text
    assert "never invent" in text
    assert "[okf:" in text


def test_reply_discipline_matches_tool_field_description() -> None:
    discipline = P.REPLY_DISCIPLINE.lower()
    desc = P.REPLY_FIELD_DESCRIPTION.lower()
    assert "tone-only" in discipline
    assert "tone-only" in desc
    assert "never list dishes" in desc


def test_build_identity_appends_runtime_context_blocks() -> None:
    ctx = {
        "max_radius_km": 12,
        "restaurant_location": "JLT",
        "delivery_info": "3 km: AED 4",
        "hours_info": "Open until midnight",
        "restaurant_phone": "+971500000003",
    }
    out = P.build_identity("River Cafe", ctx)
    assert "River Cafe" in out
    assert P.INTENT_BLOCK.strip() in out
    assert P.META_LANGUAGE_BLOCK.strip() in out
    assert P.REPLY_DISCIPLINE.strip() in out
    assert P.OKF_GROUNDING_RULE.strip() in out


def test_build_claude_system_injects_grounding_after_phase_block() -> None:
    ctx = {
        "max_radius_km": 10,
        "menu_text": "1. Parotta",
        "cart_summary": "1x Parotta",
        "cart_lines": [{"cart_item_id": "c1", "dish": "Parotta", "qty": 1}],
        "grounding": "[GROUNDED KNOWLEDGE]\nFree delivery over AED 100.",
    }
    out = P.build_claude_system("River Cafe", "awaiting_confirmation", {
        **ctx,
        "order_summary": "1x Parotta — AED 5",
    })
    assert "PHASE: Order confirmation" in out
    assert "Free delivery over AED 100" in out