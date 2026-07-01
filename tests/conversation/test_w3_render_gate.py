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
