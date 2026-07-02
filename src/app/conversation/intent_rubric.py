"""E-17 ToT-lite rubric for ambiguous router UNKNOWN turns.

Extracted from engine.py to avoid circular imports with thought_evaluator.
"""
from __future__ import annotations

import re

_DONE_PHRASES: frozenset[str] = frozenset({
    "done", "checkout", "check out", "proceed", "proceed to checkout", "finish",
    "finished", "im done", "i am done", "that will be all", "thats all", "that is all",
    "thats it", "that is it", "thats everything", "that is everything", "nothing else",
    "no more", "no more thanks", "complete order", "place order", "im good", "no thats all",
})
_DONE_EDGES: tuple[str, ...] = (
    "thats all", "that is all", "thats it", "that is it", "thats everything",
    "that is everything", "nothing else", "im done", "i am done", "that will be all",
)

# E-07: deterministic completion tokens (mirrors FakeCompletionDetector / modify flow).
_COMPLETION_EXACT = frozenset({
    "done", "that's all", "thats all", "checkout", "proceed",
    "finish", "no more", "nothing else",
    "bas", "khalas", "khalaas", "khallas",
    "no", "na", "nah", "np", "nope",
})
_COMPLETION_SUBPHRASE = frozenset(
    t for t in _COMPLETION_EXACT if " " in t
)


def is_checkout_intent(text: str) -> bool:
    """True when the customer wants to finish ordering (not a dish name)."""
    t = (text or "").strip().lower()
    return t in ("done", "checkout", "that's all", "thats all")


def is_completion_intent(text: str) -> bool:
    """E-07 deterministic completion — replaces LLM completion detector on modify path."""
    if is_done_intent(text) or is_checkout_intent(text):
        return True
    if not text or not str(text).strip():
        return False
    normalised = re.sub(r"[’'`ʼ]", "'", (text or "").lower()).strip()
    if normalised in _COMPLETION_EXACT:
        return True
    for token in _COMPLETION_SUBPHRASE:
        if token in normalised:
            return True
    return False


def is_done_intent(text: str) -> bool:
    """True for a 'that's all / done / nothing else' checkout phrase."""
    t = re.sub(r"[’'`]", "", (text or "").lower())
    t = re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", t)).strip()
    if not t:
        return False
    stripped = t[3:].strip() if t.startswith("no ") else t
    if t in _DONE_PHRASES or stripped in _DONE_PHRASES:
        return True
    return stripped.startswith(_DONE_EDGES) or stripped.endswith(_DONE_EDGES)


def resolve_ambiguous_intent(
    text: str, phase: str, *, cart_nonempty: bool,
) -> str | None:
    """Keyword rubric when the router returns UNKNOWN."""
    if not text or phase not in ("ordering", "awaiting_confirmation"):
        return None
    t = text.lower().strip()
    scores = {"add": 0, "question": 0, "checkout": 0}
    if is_done_intent(text) or is_checkout_intent(text):
        scores["checkout"] += 3
    if "?" in t or any(
        w in t for w in ("what", "how", "why", "do you", "can i", "is there", "tell me")
    ):
        scores["question"] += 2
    from app.ordering.service import parse_qty_and_text

    qty, rest = parse_qty_and_text(t)
    if qty or rest != t:
        scores["add"] += 2
    if any(w in t for w in ("add", "order", "want", "get me", "give me")):
        scores["add"] += 1
    best = max(scores, key=scores.get)
    best_score = scores[best]
    if best_score == 0:
        return None
    if sum(1 for v in scores.values() if v == best_score) > 1:
        return None
    if best == "checkout" and not cart_nonempty:
        return None
    return best