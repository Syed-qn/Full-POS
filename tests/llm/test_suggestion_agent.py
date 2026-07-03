"""Suggestion sub-agent prompt helpers + port wiring."""

import pytest

from app.llm.fake import FakeSuggestionAgent
from app.llm.suggestion_agent import (
    build_suggestion_prompt,
    parse_suggestion_response,
)


def test_build_suggestion_prompt_includes_candidates_and_customer_text():
    prompt = build_suggestion_prompt(
        [
            {"name": "Chicken Biryani", "category": "Rice", "description": "Spiced rice"},
            {"name": "Mutton Karahi", "category": "Curries"},
        ],
        "suggest me something light",
        browse_filter="chicken",
    )
    assert "MENU CANDIDATES" in prompt
    assert "Chicken Biryani" in prompt
    assert "suggest me something light" in prompt
    assert "chicken" in prompt
    assert '"intro"' in prompt


def test_parse_suggestion_response_json():
    raw = (
        '{"intro": "Try these!", "picks": '
        '[{"dish_name": "Chicken Biryani", "reason": "A classic favourite"}]}'
    )
    out = parse_suggestion_response(raw)
    assert out["intro"] == "Try these!"
    assert len(out["picks"]) == 1
    assert out["picks"][0]["dish_name"] == "Chicken Biryani"
    assert out["picks"][0]["reason"] == "A classic favourite"


def test_parse_suggestion_response_caps_at_three_picks():
    raw = (
        '{"intro": "Lots!", "picks": ['
        '{"dish_name": "A", "reason": "1"},'
        '{"dish_name": "B", "reason": "2"},'
        '{"dish_name": "C", "reason": "3"},'
        '{"dish_name": "D", "reason": "4"}'
        "]}"
    )
    out = parse_suggestion_response(raw)
    assert len(out["picks"]) == 3


def test_parse_suggestion_response_rejects_non_json():
    with pytest.raises(ValueError, match="non-JSON"):
        parse_suggestion_response("not json")


@pytest.mark.asyncio
async def test_fake_suggestion_agent_returns_first_two_candidates():
    fake = FakeSuggestionAgent()
    candidates = [
        {"name": "Chicken Biryani", "category": "Rice"},
        {"name": "Mutton Karahi", "category": "Curries"},
        {"name": "Paneer Tikka", "category": "Starters"},
    ]
    out = await fake.suggest(candidates, "surprise me")
    assert out["intro"]
    assert len(out["picks"]) == 2
    assert out["picks"][0]["dish_name"] == "Chicken Biryani"
    assert out["picks"][1]["dish_name"] == "Mutton Karahi"


@pytest.mark.asyncio
async def test_factory_get_suggestion_agent_fake(monkeypatch):
    monkeypatch.setenv("APP_LLM_PROVIDER", "fake")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.llm.factory import get_suggestion_agent

    assert type(get_suggestion_agent()).__name__ == "FakeSuggestionAgent"