"""Anthropic platform context management (E-11).

Server-side tool-result clearing via the ``context-management-2025-06-27`` beta and
client-side session memory bridged from ``conv.state['agent_notes']`` (E-05).

Reference: https://platform.claude.com/docs/en/build-with-claude/context-editing
"""
from __future__ import annotations

_CONTEXT_BETA = "context-management-2025-06-27"
_CLEAR_STRATEGY = "clear_tool_uses_20250919"


def build_context_management_config(
    *,
    enabled: bool,
    trigger_tokens: int,
    keep_tool_uses: int,
    clear_at_least_tokens: int = 0,
) -> dict | None:
    """Return ``context_management`` payload for Claude beta Messages API."""
    if not enabled:
        return None
    edit: dict = {
        "type": _CLEAR_STRATEGY,
        "trigger": {"type": "input_tokens", "value": max(1000, trigger_tokens)},
        "keep": {"type": "tool_uses", "value": max(1, keep_tool_uses)},
    }
    if clear_at_least_tokens > 0:
        edit["clear_at_least"] = {
            "type": "input_tokens",
            "value": clear_at_least_tokens,
        }
    return {"edits": [edit]}


def format_memory_context(session_notes: str | None) -> str:
    """E-11 memory-tool analogue: inject durable session notes outside history window."""
    notes = (session_notes or "").strip()
    if not notes:
        return ""
    return (
        "[MEMORY — authoritative session notes; prefer over stale chat when they conflict]\n"
        f"{notes}"
    )


def claude_request_kwargs() -> dict:
    """Extra kwargs for ``beta.messages.create`` when context management is enabled."""
    from app.config import get_settings

    settings = get_settings()
    if settings.llm_provider != "claude":
        return {}
    cm = build_context_management_config(
        enabled=settings.claude_context_management_enabled,
        trigger_tokens=settings.claude_context_clear_trigger_tokens,
        keep_tool_uses=settings.claude_context_keep_tool_uses,
        clear_at_least_tokens=settings.claude_context_clear_at_least_tokens,
    )
    if cm is None:
        return {}
    return {"betas": [_CONTEXT_BETA], "context_management": cm}