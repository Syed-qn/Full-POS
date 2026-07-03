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


def test_is_internal_leak_detects_compaction_json():
    body = json.dumps({"summary": "[Earlier conversation summary]", "compacted_count": 32})
    assert _is_internal_leak(body) is True


def test_is_internal_leak_allows_normal_chat():
    assert _is_internal_leak("Here's our menu! 😊") is False