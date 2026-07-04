"""Kitchen digest prompt helpers + port wiring."""

import pytest

from app.llm.kitchen_summary import (
    build_tier2_prompt,
    parse_tier2_response,
)
from app.llm.fake import FakeKitchenSummarizer


def test_parse_tier2_none_and_lines():
    assert parse_tier2_response("NONE") == []
    assert parse_tier2_response("") == []
    out = parse_tier2_response("Ring the gate\n• Call before 8pm")
    assert out == ["Ring the gate", "Call before 8pm"]


def test_build_tier2_prompt_includes_authoritative_and_chat():
    prompt = build_tier2_prompt(
        "1x Biryani — double masala",
        ["please call before arriving", "गेट बंद है"],
    )
    assert "AUTHORITATIVE BLOCK" in prompt
    assert "double masala" in prompt
    assert "गेट बंद है" in prompt


@pytest.mark.asyncio
async def test_fake_kitchen_summarizer_returns_no_supplements():
    fake = FakeKitchenSummarizer()
    assert await fake.supplement_from_chat("1x Biryani", ["any chat line"]) == []


@pytest.mark.asyncio
async def test_factory_get_kitchen_summarizer_fake(monkeypatch):
    monkeypatch.setenv("APP_LLM_PROVIDER", "fake")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.llm.factory import get_kitchen_summarizer

    assert type(get_kitchen_summarizer()).__name__ == "FakeKitchenSummarizer"