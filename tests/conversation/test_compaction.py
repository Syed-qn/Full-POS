"""E-09 conversation history compaction."""

import pytest
from sqlalchemy import func, select

from app.conversation.compaction import (
    build_compact_summary,
    maybe_compact_history,
)
from app.conversation.models import Conversation, Message
from app.conversation.service import record_message


async def _conv(session, restaurant, **state):
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="971500000090",
        counterpart="customer",
        state=state,
    )
    session.add(conv)
    await session.flush()
    return conv


async def _seed_messages(session, conv, n: int, *, start_ts: int = 1):
    for i in range(n):
        await record_message(
            session,
            conversation_id=conv.id,
            direction="inbound" if i % 2 == 0 else "outbound",
            wa_message_id=f"m{i}",
            msg_type="text",
            payload={"text": f"message {i}"},
            ts=start_ts + i,
        )
    await session.flush()


@pytest.mark.asyncio
async def test_maybe_compact_noop_below_threshold(db_session, restaurant):
    conv = await _conv(db_session, restaurant)
    await _seed_messages(db_session, conv, 5)
    assert await maybe_compact_history(db_session, conv, threshold=10, keep_recent=2) is False
    count = await db_session.scalar(
        select(func.count(Message.id)).where(Message.conversation_id == conv.id)
    )
    assert count == 5


@pytest.mark.asyncio
async def test_maybe_compact_creates_system_summary(db_session, restaurant):
    conv = await _conv(
        db_session,
        restaurant,
        dialogue_phase="ordering",
        draft_order_id=42,
    )
    await _seed_messages(db_session, conv, 8)
    assert await maybe_compact_history(db_session, conv, threshold=5, keep_recent=3) is True

    rows = (
        await db_session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).all()
    assert len(rows) == 4  # 1 summary + 3 recent
    assert rows[0].type == "system_summary"
    assert rows[0].payload.get("compacted_count") == 5
    assert "Earlier conversation summary" in rows[0].payload.get("summary", "")


@pytest.mark.asyncio
async def test_build_compact_summary_preserves_order_cart_address(db_session, restaurant):
    conv = await _conv(
        db_session,
        restaurant,
        dialogue_phase="address_capture",
        pending_order_id=99,
        pin_lat=25.1,
        pending_room="12B",
        pending_building="Marina Tower",
    )
    msgs = [
        Message(
            conversation_id=conv.id,
            direction="inbound",
            type="text",
            payload={"text": "2 chicken biryani"},
            ts=1,
        ),
        Message(
            conversation_id=conv.id,
            direction="outbound",
            type="product_list",
            payload={"body": "Menu"},
            ts=2,
        ),
    ]
    summary = build_compact_summary(conv, msgs, cart_summary="2x Chicken Biryani")
    assert "Order ref: 99" in summary
    assert "Phase: address_capture" in summary
    assert "Cart (authoritative): 2x Chicken Biryani" in summary
    assert "location pin received" in summary
    assert "apt/room: 12B" in summary
    assert "2 chicken biryani" in summary
    assert "Menu" not in summary


@pytest.mark.asyncio
async def test_maybe_compact_updates_conv_state(db_session, restaurant):
    conv = await _conv(db_session, restaurant, dialogue_phase="ordering")
    await _seed_messages(db_session, conv, 6)
    await maybe_compact_history(db_session, conv, threshold=4, keep_recent=2)
    await db_session.refresh(conv)
    assert conv.state.get("history_compacted_count") == 4
    assert conv.state.get("history_compacted_at")