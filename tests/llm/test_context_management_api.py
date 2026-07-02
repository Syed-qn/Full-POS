"""E-11 Anthropic platform context management helpers."""

import pytest

from app.llm.context_management import (
    build_context_management_config,
    claude_request_kwargs,
    format_memory_context,
)


def test_build_context_management_config_disabled_returns_none():
    assert build_context_management_config(
        enabled=False, trigger_tokens=80_000, keep_tool_uses=3,
    ) is None


def test_build_context_management_config_enabled_shape():
    cfg = build_context_management_config(
        enabled=True, trigger_tokens=50_000, keep_tool_uses=2, clear_at_least_tokens=10_000,
    )
    assert cfg is not None
    assert "edits" in cfg
    edit = cfg["edits"][0]
    assert edit["type"] == "clear_tool_uses_20250919"
    assert edit["trigger"]["value"] == 50_000
    assert edit["keep"]["value"] == 2
    assert edit["clear_at_least"]["value"] == 10_000


def test_format_memory_context_empty():
    assert format_memory_context(None) == ""
    assert format_memory_context("   ") == ""


def test_format_memory_context_wraps_notes():
    out = format_memory_context("Last order R1-99")
    assert "[MEMORY" in out
    assert "R1-99" in out


@pytest.mark.parametrize(
    "provider,enabled,expect_beta",
    [
        ("fake", False, False),
        ("fake", True, False),
        ("claude", False, False),
        ("claude", True, True),
    ],
)
def test_claude_request_kwargs(monkeypatch, provider, enabled, expect_beta):
    monkeypatch.setenv("APP_LLM_PROVIDER", provider)
    monkeypatch.setenv("APP_CLAUDE_CONTEXT_MANAGEMENT_ENABLED", str(enabled).lower())
    from app.config import get_settings

    get_settings.cache_clear()
    kwargs = claude_request_kwargs()
    if expect_beta:
        assert "betas" in kwargs
        assert "context-management-2025-06-27" in kwargs["betas"]
        assert "context_management" in kwargs
    else:
        assert kwargs == {}