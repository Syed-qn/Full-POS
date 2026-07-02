"""E-10 complaint sub-agent prompt helpers + port wiring."""

import pytest

from app.llm.complaint_agent import (
    build_complaint_prompt,
    parse_complaint_response,
)
from app.llm.fake import FakeComplaintSummarizer


def test_build_complaint_prompt_includes_context_and_chat():
    prompt = build_complaint_prompt(
        "Order C-12: 2x Chicken Biryani, status=delivered",
        "my biryani was cold",
    )
    assert "ORDER CONTEXT" in prompt
    assert "Chicken Biryani" in prompt
    assert "cold" in prompt
    assert '"issue"' in prompt


def test_parse_complaint_response_json():
    raw = '{"issue": "Food arrived cold.", "suggested_action": "offer_remake"}'
    out = parse_complaint_response(raw)
    assert out == {"issue": "Food arrived cold.", "suggested_action": "offer_remake"}


def test_parse_complaint_response_invalid_action_defaults():
    raw = '{"issue": "Bad order.", "suggested_action": "refund_now"}'
    out = parse_complaint_response(raw)
    assert out["suggested_action"] == "escalate_to_human"


def test_parse_complaint_response_rejects_non_json():
    with pytest.raises(ValueError, match="non-JSON"):
        parse_complaint_response("not json")


@pytest.mark.asyncio
async def test_fake_complaint_summarizer_refund_escalates():
    fake = FakeComplaintSummarizer()
    out = await fake.summarize("Order C-1", "I want a refund")
    assert out["suggested_action"] == "escalate_to_human"
    assert "refund" in out["issue"].lower()


@pytest.mark.asyncio
async def test_fake_complaint_summarizer_cold_offers_remake():
    fake = FakeComplaintSummarizer()
    out = await fake.summarize("Order C-2", "food was cold")
    assert out["suggested_action"] == "offer_remake"


@pytest.mark.asyncio
async def test_factory_get_complaint_summarizer_fake(monkeypatch):
    monkeypatch.setenv("APP_LLM_PROVIDER", "fake")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.llm.factory import get_complaint_summarizer

    assert type(get_complaint_summarizer()).__name__ == "FakeComplaintSummarizer"