"""Conversation history compaction for long-horizon returning customers (E-09).

When a conversation exceeds ``threshold`` messages, older turns are distilled into
one ``system_summary`` row. Authoritative state (order #, cart, address progress)
is preserved in the summary; redundant menu/catalog sends are dropped.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.models import Conversation, Message
from app.conversation.service import record_message

DEFAULT_THRESHOLD = 50
KEEP_RECENT = 20

# Message types that add noise without semantic value once summarized.
_DROP_TYPES = frozenset({"product_list", "buttons", "cta_url", "location_request"})


def _phase_label(conv: Conversation) -> str:
    from app.conversation.engine import _resolve_phase

    return _resolve_phase(conv)


def _order_ref(conv: Conversation) -> str | None:
    state = conv.state or {}
    for key in ("last_placed_order_id", "pending_order_id", "modify_order_id", "draft_order_id"):
        val = state.get(key)
        if val is not None:
            return str(val)
    return state.get("order_number")


def _address_progress(conv: Conversation) -> str:
    state = conv.state or {}
    bits: list[str] = []
    if state.get("pin_lat") is not None:
        bits.append("location pin received")
    if state.get("pending_room"):
        bits.append(f"apt/room: {state['pending_room']}")
    if state.get("pending_building"):
        bits.append(f"building: {state['pending_building']}")
    if state.get("pending_receiver"):
        bits.append(f"receiver: {state['pending_receiver']}")
    if state.get("address_offer_made"):
        bits.append("saved-address offer shown")
    return "; ".join(bits) if bits else "not started"


def _should_drop_message(msg: Message) -> bool:
    if msg.type in _DROP_TYPES:
        return True
    if msg.type == "text":
        body = (msg.payload or {}).get("text") or (msg.payload or {}).get("body") or ""
        low = body.lower()
        if "menu" in low and len(low.split()) <= 4:
            return True
    return False


def _render_for_summary(msg: Message) -> str | None:
    from app.conversation.engine import _render_history_content

    if msg.type == "system_summary":
        return None
    if _should_drop_message(msg):
        return None
    content = _render_history_content(msg)
    return content.strip() if content else None


async def _cart_snapshot(session: AsyncSession, conv: Conversation) -> str:
    from app.conversation.engine import _build_cart_summary

    try:
        summary = await _build_cart_summary(session, conv)
    except Exception:  # noqa: BLE001 — summary is best-effort during compaction
        return "(unknown)"
    text = (summary or "").strip()
    return text if text else "empty"


def build_compact_summary(
    conv: Conversation,
    messages: list[Message],
    *,
    cart_summary: str,
) -> str:
    """Deterministic kitchen-style digest of compacted turns."""
    lines: list[str] = ["[Earlier conversation summary]"]

    order_ref = _order_ref(conv)
    if order_ref:
        lines.append(f"Order ref: {order_ref}")

    lines.append(f"Phase: {_phase_label(conv)}")
    lines.append(f"Cart (authoritative): {cart_summary}")
    lines.append(f"Address progress: {_address_progress(conv)}")

    events: list[str] = []
    for msg in messages:
        rendered = _render_for_summary(msg)
        if not rendered:
            continue
        role = "customer" if msg.direction == "inbound" else "assistant"
        events.append(f"- {role}: {rendered}")

    if events:
        lines.append("Key turns:")
        # Cap event bullets so the summary stays bounded.
        lines.extend(events[:30])
        if len(events) > 30:
            lines.append(f"- … ({len(events) - 30} more turns omitted)")
    else:
        lines.append("Key turns: (menu browsing and acknowledgements only)")

    return "\n".join(lines)


async def maybe_compact_history(
    session: AsyncSession,
    conv: Conversation,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    keep_recent: int = KEEP_RECENT,
) -> bool:
    """Compact older messages when count exceeds ``threshold``.

    Returns True when compaction ran (one new ``system_summary`` row created and
    older compactable rows deleted). Recent ``keep_recent`` messages are retained.
    """
    if threshold <= 0 or keep_recent < 0:
        return False

    total = await session.scalar(
        select(func.count(Message.id)).where(Message.conversation_id == conv.id)
    )
    if not total or total <= threshold:
        return False

    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).all()
    if len(rows) <= keep_recent:
        return False

    to_compact = list(rows[:-keep_recent])
    if not to_compact:
        return False

    # Avoid re-compacting if the oldest retained boundary is already a summary.
    if to_compact[-1].type == "system_summary":
        return False

    cart_summary = await _cart_snapshot(session, conv)
    summary_text = build_compact_summary(conv, to_compact, cart_summary=cart_summary)
    retained = list(rows[-keep_recent:])

    summary_msg = await record_message(
        session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="system_summary",
        payload={
            "summary": summary_text,
            "compacted_count": len(to_compact),
            "preserved_recent": keep_recent,
        },
        ts=to_compact[0].ts or (retained[0].ts if retained else 0),
    )
    # Summary must sort before retained rows so _build_history sees it first.
    summary_msg.created_at = retained[0].created_at - timedelta(seconds=1)

    for msg in to_compact:
        await session.delete(msg)

    state = dict(conv.state or {})
    state["history_compacted_at"] = summary_text[:120]
    state["history_compacted_count"] = int(state.get("history_compacted_count", 0)) + len(
        to_compact
    )
    conv.state = state
    await session.flush()
    return True