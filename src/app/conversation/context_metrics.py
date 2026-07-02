"""Context token estimation for observability (E-22)."""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# Rough chars-per-token heuristic for mixed English/emoji WhatsApp prose.
_CHARS_PER_TOKEN = 4


def estimate_chars(*parts: str | None) -> int:
    """Sum character lengths of prompt parts (system, history, grounding)."""
    return sum(len((p or "").strip()) for p in parts if p)


def estimate_tokens(char_count: int) -> int:
    """Approximate token count from character count."""
    if char_count <= 0:
        return 0
    return max(1, char_count // _CHARS_PER_TOKEN)


def build_context_snapshot(
    *,
    system: str,
    history: list[dict],
    grounding: str | None,
    phase: str,
) -> dict:
    """Structured context budget snapshot for logging / ops."""
    history_blob = "\n".join(
        f"{m.get('role', '?')}: {m.get('content', '')}" for m in (history or [])
    )
    chars = estimate_chars(system, history_blob, grounding)
    return {
        "phase": phase,
        "history_turns": len(history or []),
        "chars_system": len((system or "").strip()),
        "chars_history": len(history_blob.strip()),
        "chars_grounding": len((grounding or "").strip()),
        "chars_total": chars,
        "tokens_estimated": estimate_tokens(chars),
    }


def log_context_snapshot(
    *,
    restaurant_id: int,
    conv_id: int,
    phase: str,
    system: str,
    history: list[dict],
    grounding: str | None,
) -> dict:
    """Log estimated context size; return snapshot dict for tests."""
    snap = build_context_snapshot(
        system=system, history=history, grounding=grounding, phase=phase,
    )
    _logger.info(
        "context_budget restaurant=%s conv=%s phase=%s turns=%s tokens_est=%s chars=%s",
        restaurant_id,
        conv_id,
        snap["phase"],
        snap["history_turns"],
        snap["tokens_estimated"],
        snap["chars_total"],
    )
    return snap