"""Tests for context engineering enhancements (E-01, E-03, E-05, E-06, E-21, E-22)."""
import time

import pytest

from app.conversation.engine import (
    _build_context,
    _build_history,
    _history_limit_for_phase,
    _maybe_clarify_vague_inbound,
    _render_history_content,
    _set_state,
    _update_agent_notes,
)
from app.conversation.models import Conversation
from app.conversation.service import record_message
from app.whatsapp.port import InboundMessage, MessageType


async def _conv(session, restaurant, phone="971500000090"):
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone=phone,
        counterpart="customer",
        state={},
    )
    session.add(conv)
    await session.flush()
    return conv


@pytest.mark.asyncio
async def test_history_limit_varies_by_phase(monkeypatch):
    """E-01: per-phase limits are wired into _history_limit_for_phase."""
    monkeypatch.setenv("APP_CONVERSATION_HISTORY_LIMIT_ORDERING", "10")
    monkeypatch.setenv("APP_CONVERSATION_HISTORY_LIMIT_POST_ORDER", "5")
    monkeypatch.setenv("APP_CONVERSATION_HISTORY_LIMIT_ADDRESS", "8")
    from app.config import get_settings

    get_settings.cache_clear()

    assert _history_limit_for_phase("ordering") == 10
    assert _history_limit_for_phase("post_order") == 5
    assert _history_limit_for_phase("address_capture") == 8


@pytest.mark.asyncio
async def test_build_history_uses_post_order_window(db_session, restaurant, monkeypatch):
    """E-01: post_order phase fetches only the shorter window."""
    monkeypatch.setenv("APP_CONVERSATION_HISTORY_LIMIT_POST_ORDER", "3")
    from app.config import get_settings

    get_settings.cache_clear()

    conv = await _conv(db_session, restaurant)
    for i in range(6):
        await record_message(
            db_session,
            conversation_id=conv.id,
            direction="inbound" if i % 2 == 0 else "outbound",
            wa_message_id=f"ph{i}",
            msg_type="text",
            payload={"text": f"turn-{i}"},
            ts=100 + i,
        )
    await db_session.flush()

    hist = await _build_history(db_session, conv, dialogue_phase="post_order")
    blob = " ".join(h["content"] for h in hist)
    assert "turn-0" not in blob
    assert "turn-1" not in blob
    assert "turn-2" not in blob
    assert "turn-5" in blob


@pytest.mark.asyncio
async def test_history_source_prefixes_and_cart_dedup(db_session, restaurant):
    """E-06/E-22: metadata prefixes and stale cart echo removal."""
    conv = await _conv(db_session, restaurant, phone="971500000091")
    await record_message(
        db_session, conversation_id=conv.id, direction="inbound",
        wa_message_id="c1", msg_type="text", payload={"text": "add biryani"}, ts=10,
    )
    await record_message(
        db_session, conversation_id=conv.id, direction="outbound",
        wa_message_id=None, msg_type="text",
        payload={"body": "Added 1x Chicken Biryani ✅\n\n🛒 1x Chicken Biryani"}, ts=11,
    )
    await record_message(
        db_session, conversation_id=conv.id, direction="outbound",
        wa_message_id=None, msg_type="cart_observation",
        payload={"text": "[Cart updated] 1x Chicken Biryani"}, ts=12,
    )
    await db_session.flush()

    hist = await _build_history(db_session, conv, limit=10, dialogue_phase="ordering")
    assistant_turns = [h for h in hist if h["role"] == "assistant"]
    assert len(assistant_turns) == 1
    assert assistant_turns[0]["content"].startswith("[assistant]")
    assert "[Cart updated]" in assistant_turns[0]["content"]
    assert "🛒" not in " ".join(h["content"] for h in hist if "Cart updated" not in h["content"])

    user_turns = [h for h in hist if h["role"] == "user"]
    assert user_turns[0]["content"].startswith("[customer]")


@pytest.mark.asyncio
async def test_buttons_history_omits_option_lists():
    """E-22: button rows keep body only — no verbose option list."""
    class _Msg:
        type = "buttons"
        direction = "outbound"
        payload = {
            "body": "Confirm your order?",
            "buttons": [
                {"id": "confirm_order", "title": "Confirm"},
                {"id": "cancel_order", "title": "Cancel"},
            ],
        }

    rendered = _render_history_content(_Msg())
    assert rendered == "Confirm your order?"
    assert "options" not in rendered


@pytest.mark.asyncio
async def test_jit_menu_omitted_by_default(db_session, restaurant, seed_biryani_menu):
    """E-03: ordering context uses short menu line unless menu_in_context is set."""
    conv = await _conv(db_session, restaurant, phone="971500000092")
    _set_state(conv, dialogue_phase="ordering")

    ctx = await _build_context(db_session, conv, restaurant.id, "ordering", restaurant)
    assert ctx["menu_dish_count"] == 4
    assert "Menu available on request" in ctx["menu_text"]
    assert "Chicken Biryani" not in ctx["menu_text"]


@pytest.mark.asyncio
async def test_jit_menu_included_when_flag_set(db_session, restaurant, seed_biryani_menu):
    """E-03: full menu_text injected when menu_in_context flag is True (one-shot)."""
    conv = await _conv(db_session, restaurant, phone="971500000093")
    _set_state(conv, dialogue_phase="ordering", menu_in_context=True)

    ctx = await _build_context(db_session, conv, restaurant.id, "ordering", restaurant)
    assert "Chicken Biryani" in ctx["menu_text"]
    assert conv.state.get("menu_in_context") is False


@pytest.mark.asyncio
async def test_session_notes_injected_into_context(db_session, restaurant):
    """E-05: agent_notes render as session_notes in context."""
    conv = await _conv(db_session, restaurant, phone="971500000094")
    _update_agent_notes(conv, last_confirmed_order="R1-0100", modify_intent="active")
    _set_state(conv, dialogue_phase="ordering")

    ctx = await _build_context(db_session, conv, restaurant.id, "ordering", restaurant)
    assert "session_notes" in ctx
    assert "R1-0100" in ctx["session_notes"]
    assert "Modify intent" in ctx["session_notes"]


@pytest.mark.asyncio
async def test_vague_inbound_clarifier(db_session, restaurant, seed_biryani_menu):
    """E-21: short vague message with no dish match gets deterministic clarifier."""
    conv = await _conv(db_session, restaurant, phone="971500000095")
    _set_state(conv, dialogue_phase="ordering")
    inbound = InboundMessage(
        wa_message_id="vague-1",
        from_phone="+97150000095",
        type=MessageType.TEXT,
        payload={"text": "that one"},
        restaurant_phone=restaurant.phone,
        timestamp=int(time.time()),
    )

    from app.llm.port import IntentLabel

    handled = await _maybe_clarify_vague_inbound(
        db_session, conv, inbound, restaurant.id, router_intent=IntentLabel.UNKNOWN,
    )
    assert handled is True

    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    rows = (
        await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.restaurant_id == restaurant.id)
        )
    ).all()
    assert any(
        "dish name and quantity" in (m.payload or {}).get("body", "")
        for m in rows
    )


@pytest.mark.asyncio
async def test_vague_clarifier_skips_when_dish_matches(
    db_session, restaurant, seed_biryani_menu,
):
    """E-21: a short but matchable dish name falls through (no clarifier)."""
    conv = await _conv(db_session, restaurant, phone="971500000096")
    _set_state(conv, dialogue_phase="ordering")
    inbound = InboundMessage(
        wa_message_id="vague-2",
        from_phone="+97150000096",
        type=MessageType.TEXT,
        payload={"text": "biryani"},
        restaurant_phone=restaurant.phone,
        timestamp=int(time.time()),
    )

    handled = await _maybe_clarify_vague_inbound(
        db_session, conv, inbound, restaurant.id,
    )
    assert handled is False


@pytest.mark.asyncio
async def test_tot_lite_question_branch_answers_dish_info(
    db_session, restaurant, seed_biryani_menu, monkeypatch,
):
    """E-17: question winner routes to dish-info before main agent."""
    from app.conversation.engine import _apply_tot_lite_branch
    from app.llm.fake import FakeThoughtEvaluator

    class _QEval(FakeThoughtEvaluator):
        async def evaluate(self, text, phase, *, cart_nonempty):  # noqa: ARG002
            return "question"

    monkeypatch.setattr(
        "app.llm.factory.get_thought_evaluator", lambda: _QEval(),
    )
    conv = await _conv(db_session, restaurant, phone="971500000097")
    _set_state(conv, dialogue_phase="ordering")
    inbound = InboundMessage(
        wa_message_id="tot-q-1",
        from_phone="+97150000097",
        type=MessageType.TEXT,
        payload={"text": "what is chicken biryani"},
        restaurant_phone=restaurant.phone,
        timestamp=int(time.time()),
    )

    handled = await _apply_tot_lite_branch(
        db_session, conv, inbound, restaurant.id, restaurant,
        text="what is chicken biryani", phase="ordering",
    )
    assert handled is True

    from sqlalchemy import select
    from app.outbox.models import OutboxMessage

    rows = (
        await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.restaurant_id == restaurant.id)
        )
    ).all()
    assert any("chicken biryani" in (m.payload or {}).get("body", "").lower() for m in rows)


@pytest.mark.asyncio
async def test_modify_summarizer_notifies_manager(
    db_session, restaurant, seed_biryani_menu, monkeypatch,
):
    """E-10: modify review stores summary and alerts manager."""
    from decimal import Decimal

    from sqlalchemy import select

    from app.conversation.engine import _advance_modify_to_confirm
    from app.menu.models import Dish
    from app.ordering.models import Customer, Order, OrderItem
    from app.outbox.models import OutboxMessage
    from app.whatsapp.port import InboundMessage, MessageType

    restaurant.phone = "+971509999001"
    biryani = (
        await db_session.scalars(
            select(Dish).where(
                Dish.restaurant_id == restaurant.id,
                Dish.name_normalized == "chicken biryani",
            )
        )
    ).first()
    assert biryani is not None

    cust = Customer(restaurant_id=restaurant.id, phone="+971501112233")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="R1-MOD",
        status="confirmed",
        subtotal=Decimal("28.00"),
        total=Decimal("28.00"),
        delivery_fee_aed=Decimal("0.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=biryani.id,
            dish_number=biryani.dish_number,
            dish_name="Chicken Biryani",
            qty=1,
            price_aed=Decimal("28.00"),
        )
    )
    await db_session.flush()

    conv = await _conv(db_session, restaurant, phone=cust.phone)
    proposed = [{
        "dish_id": biryani.id,
        "name": "Chicken Biryani",
        "qty": 2,
        "price_aed": "28.00",
    }]
    inbound = InboundMessage(
        wa_message_id="mod-sum-1",
        from_phone=cust.phone,
        type=MessageType.TEXT,
        payload={"text": "done"},
        restaurant_phone=restaurant.phone,
        timestamp=int(time.time()),
    )

    await _advance_modify_to_confirm(
        db_session, conv, inbound, restaurant.id, order.id, proposed,
    )
    assert conv.state.get("modify_summary")
    assert conv.state["modify_summary"].get("suggested_action")

    mgr_rows = (
        await db_session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.restaurant_id == restaurant.id,
                OutboxMessage.to_phone == restaurant.phone,
            )
        )
    ).all()
    assert any("modify review" in (m.payload or {}).get("body", "").lower() for m in mgr_rows)