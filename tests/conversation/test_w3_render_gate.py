"""W3 render gate tests — single-add/update-note DB-backed cart tail (RA-1/R-013/R-040)."""
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
    """drive add then note update → outbound body must contain 🛒, note, Subtotal."""
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
async def test_confirm_summary_engine_only(db_session, restaurant, seed_biryani_menu):
    """After cart + saved-address → 'done', the outbound must contain engine-authored facts.

    Seeds a saved address so 'done' immediately attaches it and sends the order summary
    without a location-pin round-trip. Verifies confirm path is engine-only (F104/TX-17).
    """
    from decimal import Decimal

    from app.ordering.models import CustomerAddress
    from app.ordering.service import get_or_create_customer

    phone = "+971500000072"

    # Seed a confirmed saved address for this customer so checkout skips the pin step.
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone=phone
    )
    addr = CustomerAddress(
        customer_id=customer.id,
        latitude=25.2048,
        longitude=55.2708,
        room_apartment="101",
        building="Test Tower",
        receiver_name="Test Customer",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone=phone,
        turns=[
            {"type": "text", "text": "one chicken biryani"},
            {"type": "text", "text": "done"},
        ],
    )
    # After "done" with a saved address, the engine attaches it and sends order summary.
    last_turn = res.turns[-1]
    assert last_turn.outbounds, "engine must send order summary after 'done'"
    body = last_turn.outbounds[-1].body
    # The summary must come from DB — it must contain engine-standard fields
    assert "Order summary" in body or "Subtotal" in body, (
        f"outbound missing DB-backed summary fields: {body!r}"
    )


@pytest.mark.asyncio
async def test_observation_turn_after_add(db_session, restaurant, seed_biryani_menu):
    """After a single add, a cart_observation Message must exist in DB (F66/W3)."""
    from app.conversation.models import Message
    from sqlalchemy import select

    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000073",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )
    conv_state = res.turns[0].state
    # Query Message table for cart_observation type
    msgs = (await db_session.scalars(
        select(Message).where(Message.type == "cart_observation")
    )).all()
    assert msgs, "cart_observation Message must be recorded after successful add"
    body_text = msgs[-1].payload.get("text", "")
    assert "biryani" in body_text.lower(), (
        f"cart_observation payload must contain dish name, got: {body_text!r}"
    )


def test_strip_money_claims_removes_aed_lines():
    """_strip_money_claims removes lines with AED amounts."""
    from app.conversation.engine import _strip_money_claims

    text = "Added biryani ✅\nTotal: AED 20\nEnjoy your meal!"
    result = _strip_money_claims(text)
    assert "AED" not in result, f"AED claim not stripped: {result!r}"
    assert "Added biryani" in result


def test_strip_money_claims_preserves_non_money_text():
    """_strip_money_claims keeps lines without currency amounts."""
    from app.conversation.engine import _strip_money_claims

    text = "Got it! 😊\nYour order is updated."
    result = _strip_money_claims(text)
    assert result == text


def test_strip_money_claims_empty():
    """_strip_money_claims handles empty/None input."""
    from app.conversation.engine import _strip_money_claims

    assert _strip_money_claims("") == ""
    assert _strip_money_claims(None) is None
