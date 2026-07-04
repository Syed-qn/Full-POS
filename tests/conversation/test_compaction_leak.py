"""Compaction summary must stay internal — never leak JSON to WhatsApp."""

import json

import pytest

from app.conversation.engine import _build_history, _is_internal_leak, _render_history_content
from app.conversation.models import Conversation, Message
from app.conversation.service import record_message


def test_render_system_summary_uses_summary_field():
    msg = Message(
        conversation_id=1,
        direction="outbound",
        type="system_summary",
        payload={
            "summary": "[Earlier conversation summary]\nOrder ref: 1",
            "compacted_count": 5,
        },
    )
    assert "Order ref: 1" in _render_history_content(msg)


@pytest.mark.asyncio
async def test_build_history_puts_system_summary_as_system_role(db_session, restaurant):
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="971500000091",
        counterpart="customer",
        state={},
    )
    db_session.add(conv)
    await db_session.flush()

    summary_text = "[Earlier conversation summary]\nOrder ref: 42\nPhase: ordering"
    await record_message(
        db_session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="system_summary",
        payload={"summary": summary_text, "compacted_count": 10},
        ts=1,
    )
    await record_message(
        db_session,
        conversation_id=conv.id,
        direction="inbound",
        wa_message_id="u1",
        msg_type="text",
        payload={"text": "show me the menu"},
        ts=2,
    )
    await db_session.flush()

    hist = await _build_history(db_session, conv, limit=10)
    system_turns = [h for h in hist if h["role"] == "system"]
    assert len(system_turns) == 1
    assert "Order ref: 42" in system_turns[0]["content"]
    assert not any(
        h["role"] == "assistant" and "Order ref: 42" in h["content"] for h in hist
    )


def test_dashboard_display_text_never_shows_raw_summary():
    """Compaction rows must render as a neutral marker in every dashboard/API
    view (chats, partner API, order-detail chat) — never as a giant outbound
    bubble that looks like a message the customer received."""
    from app.conversation.service import message_display_text

    payload = {
        "summary": "[Earlier conversation summary]\nOrder ref: 42\n- customer: hi",
        "compacted_count": 30,
        "preserved_recent": 20,
    }
    text = message_display_text(payload)
    assert text is not None
    assert "[Earlier conversation summary]" not in text
    assert "Order ref" not in text
    assert "summar" in text.lower()  # neutral marker mentions summarization


def test_dashboard_view_payload_keeps_summary_but_neutral_text():
    from app.conversation.service import message_view_payload

    msg = Message(
        conversation_id=1,
        direction="outbound",
        type="system_summary",
        payload={
            "summary": "[Earlier conversation summary]\nOrder ref: 42",
            "compacted_count": 30,
        },
    )
    view = message_view_payload(msg)
    assert "[Earlier conversation summary]" not in (view.get("text") or "")
    # Raw digest stays available for the frontend's expandable system note.
    assert "Order ref: 42" in view["summary"]


def test_is_internal_leak_detects_compaction_json():
    body = json.dumps({"summary": "[Earlier conversation summary]", "compacted_count": 32})
    assert _is_internal_leak(body) is True


def test_is_internal_leak_allows_normal_chat():
    assert _is_internal_leak("Here's our menu! 😊") is False