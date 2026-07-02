"""Tests for W1 Task 6: clarification gate + derived phase-action table."""
import time

import pytest
from sqlalchemy import select

from app.conversation.models import Message
from app.whatsapp.port import InboundMessage, MessageType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_conv_and_inbound(db_session, restaurant, wa_id="wamid.clarify-test-1"):
    from app.conversation.service import get_or_create_conversation

    phone = "+971509876543"
    conv = await get_or_create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        phone=phone,
        counterpart="customer",
    )
    inbound = InboundMessage(
        wa_message_id=wa_id,
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": "I want something"},
        restaurant_phone=restaurant.phone,
        timestamp=int(time.time()),
    )
    return conv, inbound


# ---------------------------------------------------------------------------
# Clarification gate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_needs_clarification_sends_message_and_no_mutation(
    db_session,
    restaurant,
    seed_biryani_menu,
):
    """A model result flagged needs_clarification must NOT mutate the cart and must
    send exactly one deterministic clarification outbound reply (R-069)."""
    from app.conversation.engine import _dispatch_action
    from app.ordering.models import Order

    conv, inbound = await _make_conv_and_inbound(db_session, restaurant)

    # Simulate the shape that to_engine_result returns for a missing-field violation.
    result = type("R", (), {
        "action": "no_action",
        "action_data": {
            "needs_clarification": True,
            "clarify_action": "cart_set_qty",
            "missing_fields": ["new_total"],
            "dish_query": "",
            "qty": None,
            "special_note": "",
            "items": [],
            "apt_room": "",
            "building": "",
            "receiver_name": "",
        },
        "message": "",
    })()

    await _dispatch_action(
        db_session,
        conv=conv,
        inbound=inbound,
        restaurant_id=restaurant.id,
        result=result,
        phase="ordering",
        restaurant=restaurant,
    )
    await db_session.flush()

    # 1. Exactly one outbound message was written (the clarification).
    outbound_rows = (
        await db_session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.direction == "outbound",
            )
        )
    ).all()
    assert len(outbound_rows) == 1, (
        f"Expected 1 clarification outbound, got {len(outbound_rows)}"
    )

    # 2. The outbound body is the engine-authored clarification string.
    body = outbound_rows[0].payload.get("body", "")
    assert body, "Clarification outbound has an empty body"
    # Must not be blank / must be the engine-authored fallback text.
    assert len(body) > 10

    # 3. No Order/OrderItem rows were created (no cart mutation).
    orders = (
        await db_session.scalars(
            select(Order).where(Order.restaurant_id == restaurant.id)
        )
    ).all()
    assert orders == [], (
        f"Clarification path must not mutate the cart; found {len(orders)} Order(s)"
    )


@pytest.mark.asyncio
async def test_needs_clarification_uses_result_message_when_present(
    db_session,
    restaurant,
    seed_biryani_menu,
):
    """When result.message is set, the clarification reply uses THAT text (not the
    engine fallback), so the interpreter's tone hint reaches the customer."""
    from app.conversation.engine import _dispatch_action

    conv, inbound = await _make_conv_and_inbound(
        db_session, restaurant, wa_id="wamid.clarify-test-2"
    )

    custom_msg = "Which dish did you mean exactly? 🍽️"
    result = type("R", (), {
        "action": "no_action",
        "action_data": {
            "needs_clarification": True,
            "clarify_action": "cart_add",
            "missing_fields": ["dish_query"],
            "dish_query": "",
            "qty": None,
            "special_note": "",
            "items": [],
            "apt_room": "",
            "building": "",
            "receiver_name": "",
        },
        "message": custom_msg,
    })()

    await _dispatch_action(
        db_session,
        conv=conv,
        inbound=inbound,
        restaurant_id=restaurant.id,
        result=result,
        phase="ordering",
        restaurant=restaurant,
    )
    await db_session.flush()

    outbound_rows = (
        await db_session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.direction == "outbound",
            )
        )
    ).all()
    assert len(outbound_rows) == 1
    assert outbound_rows[0].payload.get("body") == custom_msg


# ---------------------------------------------------------------------------
# Derived phase-table coverage test
# ---------------------------------------------------------------------------


def test_derived_phase_table_covers_old_literal():
    """The derived _PHASE_ACTIONS must be a superset of the old hand-written literal
    so no currently-allowed legacy action is silently dropped (regression guard)."""
    from app.conversation.engine import _PHASE_ACTIONS

    old_literal: dict[str, frozenset] = {
        "ordering": frozenset({
            "add_item", "remove_item", "update_qty", "clear_cart", "proceed_to_address",
            "cancel_order", "status_query", "show_menu", "no_action",
        }),
        "address_capture": frozenset({
            "send_location_request", "save_address_text", "use_saved_address",
            "proceed_to_confirmation", "cancel_order", "no_action",
        }),
        "awaiting_confirmation": frozenset({
            "confirm_order", "request_modification", "cancel_order", "no_action",
        }),
        "post_order": frozenset({
            "status_query", "request_modification", "cancel_order", "no_action",
        }),
    }

    for phase, old_actions in old_literal.items():
        derived = _PHASE_ACTIONS.get(phase, frozenset())
        dropped = old_actions - derived
        assert not dropped, (
            f"Phase '{phase}': derived _PHASE_ACTIONS dropped legacy action(s) "
            f"that were previously allowed: {dropped!r}. This is a regression."
        )
