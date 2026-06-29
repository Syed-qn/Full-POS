"""Regression: the address-capture prompt must keep its guardrails so the bot
doesn't over-share the restaurant location or loop on the location request."""
from app.llm import deepseek


def test_address_block_does_not_reveal_restaurant_location():
    assert "NEVER volunteer or repeat the RESTAURANT" in deepseek._ADDRESS_BLOCK


def test_address_block_offers_typed_fallback_not_loop():
    assert "just type your address" in deepseek._ADDRESS_BLOCK


def test_address_block_ignores_offtopic_or_rude():
    assert "off-topic, gibberish, or rude" in deepseek._ADDRESS_BLOCK
