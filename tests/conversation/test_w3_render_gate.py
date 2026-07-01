"""W3 render gate tests — DB-backed cart tail + factual validator (RA-1/R-013/R-040)."""
from __future__ import annotations

import pytest

from tests.harness.replay import drive_turns


@pytest.mark.asyncio
async def test_single_add_reply_has_db_cart_tail(db_session, restaurant, seed_biryani_menu):
    """drive 'one chicken biryani' → outbound body must contain 🛒, dish name, Subtotal."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000070",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )
    outbounds = res.turns[0].outbounds
    assert outbounds, "engine must send an outbound reply"
    body = outbounds[-1].body
    assert "🛒" in body, f"cart tail missing 🛒 in: {body!r}"
    assert "biryani" in body.lower(), f"dish name missing in: {body!r}"
    assert "Subtotal" in body, f"Subtotal missing in: {body!r}"


@pytest.mark.asyncio
async def test_updated_note_reply_has_db_cart_tail(db_session, restaurant, seed_biryani_menu):
    """drive add then note update → outbound body must contain 🛒 and Subtotal."""
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000071",
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "add double masala"},
        ],
    )
    outbounds = res.turns[-1].outbounds
    assert outbounds, "engine must send an outbound reply on note update"
    body = outbounds[-1].body
    assert "🛒" in body, f"cart tail missing 🛒 in: {body!r}"
    assert "Subtotal" in body, f"Subtotal missing in: {body!r}"


@pytest.mark.asyncio
async def test_proceed_to_confirmation_is_engine_only(db_session, restaurant, seed_biryani_menu):
    """After cart → 'done', the engine advances the flow with an engine-authored
    message and never leaks an LLM-authored money claim (F104/TX-17).

    With no address on file the engine correctly routes to address capture; that
    prompt is deterministic and must carry NO AED amount (a bare LLM reply at the
    proceed step used to narrate a fabricated total here).
    """
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000072",
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "done"},
        ],
    )
    last_turn = res.turns[-1]
    assert last_turn.outbounds, "engine must send a message after 'done'"
    body = last_turn.outbounds[-1].body
    # Engine-authored next step (no LLM-fabricated total slipped through the
    # proceed_to_confirmation path). Either a DB summary or the address prompt.
    is_db_summary = "Order summary" in body or "Subtotal" in body
    is_addr_prompt = "location" in body.lower() or "pin" in body.lower()
    assert is_db_summary or is_addr_prompt, (
        f"outbound is neither a DB summary nor the engine address prompt: {body!r}"
    )
    if not is_db_summary:
        # The address prompt must not contain any hallucinated money amount.
        assert "AED" not in body, f"address prompt leaked a money claim: {body!r}"


@pytest.mark.asyncio
async def test_confirm_order_number_is_real(db_session, restaurant, seed_biryani_menu):
    """When an order is confirmed, the confirmation carries a DB order_number, never
    a hallucinated one (F104). Confirmation text is engine-authored end to end.

    Reaching confirmation requires an address; we attach a confirmed address to the
    draft order directly, then drive the confirm button.
    """
    from app.conversation.models import Conversation
    from app.ordering.models import CustomerAddress, Order
    from sqlalchemy import select

    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000073",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )
    conv = (await db_session.scalars(
        select(Conversation).where(Conversation.phone == "+971500000073")
    )).first()
    oid = conv.state.get("draft_order_id")
    order = await db_session.get(Order, oid)
    assert order is not None and order.order_number, "draft must have a real order_number"
    # Attach a confirmed delivery address so confirmation is reachable.
    addr = CustomerAddress(
        customer_id=order.customer_id, latitude=25.2, longitude=55.27,
        room_apartment="101", building="Test Tower", receiver_name="Sam", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    order.address_id = addr.id
    await db_session.flush()

    # Confirm via the confirm button.
    res2 = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000073",
        turns=[{"type": "button_reply", "button_id": "confirm_order", "text": "Confirm"}],
    )
    body = res2.turns[-1].outbounds[-1].body if res2.turns[-1].outbounds else ""
    if "Order confirmed" in body:
        # The order_number in the message must be the real DB one.
        assert order.order_number in body, (
            f"confirmation used a fabricated order number; DB={order.order_number!r} "
            f"body={body!r}"
        )
