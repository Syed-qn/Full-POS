"""Order-modify sub-agent (E-10).

Distills a multi-line modify proposal into structured staff/customer handoff JSON.
"""
from __future__ import annotations

import json
import re

_MODIFY_SYSTEM = """\
[ROLE]
You are an order-modification distiller for a restaurant WhatsApp platform.

[TASK]
Summarize proposed order line changes for staff handoff.

[INPUT]
You receive ORDER CONTEXT (authoritative current order), PROPOSED CHANGES (new line items),
and an optional CHAT SNIPPET.

[INSTRUCTIONS]
- Describe what changed in one sentence (Was → Now).
- Count how many line items differ from the current order.
- Route staff to confirm, clarify, or escalate.

[CONSTRAINTS]
# spec: E-10 — order/proposal context authority
- NEVER invent dishes or prices not in ORDER CONTEXT or PROPOSED CHANGES.
- If the proposal is empty or identical to current, use clarify_with_customer.
- If the customer is angry or mentions refund/compensation, use escalate_to_human.

[TONE]
Neutral and professional — internal staff handoff only, not customer-facing chat.
Summarize changes factually; no emoji or conversational filler.

[OUTPUT]
JSON ONLY with exactly three keys:
- "summary": one concise sentence describing what changed.
- "change_count": integer count of line items that differ.
- "suggested_action": one of confirm_modify | clarify_with_customer | escalate_to_human
"""

MODIFY_SYSTEM = _MODIFY_SYSTEM


def build_modify_prompt(order_context: str, proposed_text: str, chat_snippet: str = "") -> str:
    return (
        f"ORDER CONTEXT:\n{order_context or '(none)'}\n\n"
        f"PROPOSED CHANGES:\n{proposed_text or '(none)'}\n\n"
        f"CHAT SNIPPET:\n{chat_snippet or '(none)'}\n\n"
        'Reply with JSON only: {"summary": "...", "change_count": N, '
        '"suggested_action": "..."}'
    )


_ALLOWED_ACTIONS = frozenset(
    {"confirm_modify", "clarify_with_customer", "escalate_to_human"},
)


def parse_modify_response(raw: str) -> dict:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ModifySummarizer returned non-JSON: {exc}") from exc

    summary = (parsed.get("summary") or "").strip()
    action = (parsed.get("suggested_action") or "").strip().lower()
    try:
        change_count = int(parsed.get("change_count", 0))
    except (TypeError, ValueError):
        change_count = 0
    if action not in _ALLOWED_ACTIONS:
        action = "clarify_with_customer"
    if not summary:
        summary = "Customer requested order modifications."
    return {
        "summary": summary,
        "change_count": max(0, change_count),
        "suggested_action": action,
    }


def format_proposed_lines(proposed: list[dict]) -> str:
    lines = [
        f"{p.get('qty', 1)}x {p.get('name', '?')} @ AED {p.get('price_aed', '?')}"
        for p in (proposed or [])
    ]
    return "\n".join(lines) if lines else "(empty)"


class DeepSeekModifySummarizer:
    async def summarize(
        self, order_context: str, proposed_text: str, chat_snippet: str = "",
    ) -> dict:
        from app.llm.deepseek import _async_chat, _get_deepseek_settings

        api_key, model = _get_deepseek_settings()
        prompt = build_modify_prompt(order_context, proposed_text, chat_snippet)
        raw = await _async_chat(
            api_key,
            model,
            [
                {"role": "system", "content": _MODIFY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=256,
            temperature=0.0,
        )
        return parse_modify_response(raw)


class ClaudeModifySummarizer:
    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client

        self._client = _get_anthropic_client()

    async def summarize(
        self, order_context: str, proposed_text: str, chat_snippet: str = "",
    ) -> dict:
        from app.llm.claude import _first_text

        prompt = build_modify_prompt(order_context, proposed_text, chat_snippet)
        msg = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=256,
            temperature=0.0,
            system=_MODIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_modify_response(_first_text(msg))