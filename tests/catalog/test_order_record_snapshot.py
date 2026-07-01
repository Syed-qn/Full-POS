import pytest
from sqlalchemy import select

from app.catalog.service import handle_catalog_order
from app.conversation.models import Conversation, Message
from app.whatsapp.port import InboundMessage, MessageType


def _order_inbound(phone, restaurant_phone):
    return InboundMessage(
        wa_message_id=f"wamid-{phone}",
        from_phone=phone,
        type=MessageType.ORDER,
        payload={"product_items": [
            {"product_retailer_id": "ju9f8jfy90", "quantity": 2,
             "item_price": 20, "currency": "AED"},
        ]},
        restaurant_phone=restaurant_phone,
        timestamp=1_700_000_000,
    )


@pytest.mark.asyncio
async def test_order_record_has_display_text_and_snapshot(
    db_session, restaurant, seed_biryani_menu
):
    inbound = _order_inbound("+971500000070", restaurant.phone)
    await handle_catalog_order(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.flush()

    conv = await db_session.scalar(
        select(Conversation).where(Conversation.restaurant_id == restaurant.id)
    )
    order_msg = await db_session.scalar(
        select(Message).where(
            Message.conversation_id == conv.id, Message.type == "order"
        )
    )
    assert order_msg is not None
    payload = order_msg.payload
    # original product_items preserved
    assert payload.get("product_items"), "raw product_items must be preserved"
    # human display text resolves the dish name + qty
    assert "display_text" in payload
    assert "biryani" in payload["display_text"].lower()
    assert "2" in payload["display_text"]
    # structured snapshot of the resulting cart
    snap = payload.get("cart_snapshot")
    assert isinstance(snap, list) and snap, "cart_snapshot must be a non-empty list"
    line = snap[0]
    assert {"cart_item_id", "dish", "qty", "price"} <= set(line)
    assert line["qty"] == 2
    assert "biryani" in line["dish"].lower()
