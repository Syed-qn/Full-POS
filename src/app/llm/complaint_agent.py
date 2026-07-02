"""Post-delivery complaint sub-agent (E-10).

Focused LLM call with order + chat context only; returns structured
``{issue, suggested_action}`` for the lead conversation agent.
"""
from __future__ import annotations

import json
import re

_COMPLAINT_SYSTEM = """\
[ROLE]
You are a post-delivery complaint distiller for a restaurant WhatsApp platform.

[TASK]
Distill the customer's complaint into structured staff handoff JSON.

[INPUT]
You receive ORDER CONTEXT (authoritative order facts) and CHAT SNIPPET (recent customer
messages about the problem, any language).

[INSTRUCTIONS]
- Summarize the core issue in one sentence.
- Classify the best routing action for staff — never compensate yourself.

[CONSTRAINTS]
# spec: E-10 — no compensation promises
- NEVER promise refunds, credits, remakes, or compensation — only classify and route.
# spec: E-10 — order context authority
- NEVER invent order items or prices not present in ORDER CONTEXT.
- If the message is vague, use suggested_action="request_photo_evidence" or
  "acknowledge_and_wait".
- If refund/compensation language appears, use escalate_to_human.

[TONE]
Neutral and professional — internal staff handoff only, not customer-facing chat.
Preserve quoted dish/problem phrases; no emoji or compensation language.

[OUTPUT]
JSON ONLY with exactly two keys:
- "issue": one concise sentence (preserve quoted dish/problem phrases in customer language).
- "suggested_action": one of escalate_to_human | offer_remake | offer_partial_credit |
  request_photo_evidence | acknowledge_and_wait
"""

COMPLAINT_SYSTEM = _COMPLAINT_SYSTEM


def build_complaint_prompt(order_context: str, chat_snippet: str) -> str:
    """User turn for the complaint summarizer."""
    return (
        f"ORDER CONTEXT:\n{order_context or '(none)'}\n\n"
        f"CHAT SNIPPET:\n{chat_snippet or '(none)'}\n\n"
        'Reply with JSON only: {"issue": "...", "suggested_action": "..."}'
    )


_ALLOWED_ACTIONS = frozenset(
    {
        "escalate_to_human",
        "offer_remake",
        "offer_partial_credit",
        "request_photo_evidence",
        "acknowledge_and_wait",
    }
)


async def build_order_context_for_summarizer(session, order) -> str:
    """Compact authoritative order facts for the complaint sub-agent."""
    if order is None:
        return ""
    from sqlalchemy import select

    from app.ordering.models import OrderItem

    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    item_lines = ", ".join(f"{it.qty}x {it.dish_name}" for it in items) or "(no lines)"
    return (
        f"Order #{order.order_number}, status={order.status}, "
        f"total=AED {order.total}, items: {item_lines}"
    )


async def build_chat_snippet_for_summarizer(
    session, conv, *, limit: int = 6,
) -> str:
    """Recent inbound customer messages about the complaint."""
    from sqlalchemy import select

    from app.conversation.models import Message

    rows = (
        await session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.direction == "inbound",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
    ).all()
    parts: list[str] = []
    for msg in reversed(rows):
        body = (msg.payload or {}).get("text") or (msg.payload or {}).get("body") or ""
        body = str(body).strip()
        if body:
            parts.append(body)
    return "\n".join(parts)


def category_from_summary(summary: dict | None) -> str | None:
    """Map sub-agent output to Ticket.category when possible."""
    if not summary:
        return None
    issue = (summary.get("issue") or "").lower()
    action = (summary.get("suggested_action") or "").lower()
    if any(w in issue for w in ("missing", "wrong item", "wrong order")):
        return "missing" if "missing" in issue else "wrong"
    if any(w in issue for w in ("cold", "stale", "raw", "burnt", "spoiled", "quality")):
        return "quality"
    if any(w in issue for w in ("late", "rider", "delivery", "never arrived")):
        return "delivery"
    if "refund" in issue or action == "escalate_to_human":
        return "other"
    return "other"


def parse_complaint_response(raw: str) -> dict:
    """Parse complaint sub-agent JSON into ``{issue, suggested_action}``."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ComplaintSummarizer returned non-JSON: {exc}") from exc

    issue = (parsed.get("issue") or "").strip()
    action = (parsed.get("suggested_action") or "").strip().lower()
    if action not in _ALLOWED_ACTIONS:
        action = "escalate_to_human"
    if not issue:
        issue = "Customer reported a post-delivery problem."
    return {"issue": issue, "suggested_action": action}


class DeepSeekComplaintSummarizer:
    """Production complaint distiller — DeepSeek chat API."""

    async def summarize(self, order_context: str, chat_snippet: str) -> dict:
        from app.llm.deepseek import _async_chat, _get_deepseek_settings

        api_key, model = _get_deepseek_settings()
        prompt = build_complaint_prompt(order_context, chat_snippet)
        raw = await _async_chat(
            api_key,
            model,
            [
                {"role": "system", "content": _COMPLAINT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=256,
            temperature=0.0,
        )
        return parse_complaint_response(raw)


class ClaudeComplaintSummarizer:
    """Production complaint distiller — Claude haiku."""

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client

        self._client = _get_anthropic_client()

    async def summarize(self, order_context: str, chat_snippet: str) -> dict:
        from app.llm.claude import _first_text

        prompt = build_complaint_prompt(order_context, chat_snippet)
        msg = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=256,
            temperature=0.0,
            system=_COMPLAINT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_complaint_response(_first_text(msg))