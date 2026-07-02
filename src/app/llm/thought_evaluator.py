"""ToT-lite thought evaluator (E-17).

Scores candidate interpretations for ambiguous customer turns when the router
returns UNKNOWN. Default path is deterministic; production may use a tiny LLM call.
"""
from __future__ import annotations

import json
import re

_TOT_SYSTEM = """\
[ROLE]
You are a thought evaluator for ambiguous restaurant order messages.

[TASK]
Score three candidate interpretations and pick the winner.

[INPUT]
Phase, cart context, customer message, and candidates: add | question | checkout.

[CONSTRAINTS]
- Pick checkout only when the customer clearly means they are finished ordering.
- Pick question when they ask something without ordering.
- Otherwise pick add.

[OUTPUT]
JSON only: {"winner": "add"|"question"|"checkout", "confidence": 0.0-1.0}
"""


def build_tot_prompt(
    text: str, phase: str, cart_context: str, candidates: list[str],
) -> str:
    return (
        f"Phase: {phase}\n"
        f"Cart: {cart_context or '(empty)'}\n"
        f"Message: {text!r}\n"
        f"Candidates: {', '.join(candidates)}\n"
        'Reply JSON: {"winner": "...", "confidence": 0.0}'
    )


def parse_tot_response(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ThoughtEvaluator returned non-JSON: {exc}") from exc
    winner = (parsed.get("winner") or "").strip().lower()
    if winner not in ("add", "question", "checkout"):
        winner = "add"
    try:
        confidence = float(parsed.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return {"winner": winner, "confidence": max(0.0, min(1.0, confidence))}


class DeterministicThoughtEvaluator:
    """Rubric-based evaluator — no LLM, mirrors engine ToT-lite."""

    def evaluate(
        self, text: str, phase: str, *, cart_nonempty: bool,
    ) -> str | None:
        from app.conversation.intent_rubric import resolve_ambiguous_intent

        return resolve_ambiguous_intent(text, phase, cart_nonempty=cart_nonempty)


class DeepSeekThoughtEvaluator:
    async def evaluate(
        self, text: str, phase: str, *, cart_nonempty: bool,
    ) -> str | None:
        from app.llm.deepseek import _async_chat, _get_deepseek_settings

        det = DeterministicThoughtEvaluator()
        quick = det.evaluate(text, phase, cart_nonempty=cart_nonempty)
        if quick is not None:
            return quick

        api_key, model = _get_deepseek_settings()
        prompt = build_tot_prompt(text, phase, "", ["add", "question", "checkout"])
        raw = await _async_chat(
            api_key,
            model,
            [
                {"role": "system", "content": _TOT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=64,
            temperature=0.0,
        )
        return parse_tot_response(raw).get("winner")


class ClaudeThoughtEvaluator:
    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client

        self._client = _get_anthropic_client()

    async def evaluate(
        self, text: str, phase: str, *, cart_nonempty: bool,
    ) -> str | None:
        from app.llm.claude import _first_text

        det = DeterministicThoughtEvaluator()
        quick = det.evaluate(text, phase, cart_nonempty=cart_nonempty)
        if quick is not None:
            return quick

        prompt = build_tot_prompt(text, phase, "", ["add", "question", "checkout"])
        msg = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=64,
            temperature=0.0,
            system=_TOT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_tot_response(_first_text(msg)).get("winner")