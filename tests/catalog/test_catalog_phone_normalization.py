import pytest
from sqlalchemy import func, select

from app.catalog.service import handle_catalog_order
from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.whatsapp.port import InboundMessage, MessageType


@pytest.mark.asyncio
async def test_basket_and_text_share_one_conversation(db_session, restaurant, seed_biryani_menu):
    # Basket arrives in Meta's raw webhook format: digits only, no leading '+'.
    order_in = InboundMessage(
        wa_message_id="o-1", from_phone="971500000099", type=MessageType.ORDER,
        payload={"product_items": [{"product_retailer_id": "ju9f8jfy90", "quantity": 1}]},
        restaurant_phone=restaurant.phone, timestamp=1_700_000_000)
    await handle_catalog_order(db_session, order_in, restaurant_id=restaurant.id)
    # Follow-up text arrives the same way; handle_inbound normalizes it to '+…'.
    # Unless the catalogue handler normalizes too, this splits into 2 conversations.
    text_in = InboundMessage(
        wa_message_id="t-1", from_phone="971500000099", type=MessageType.TEXT,
        payload={"text": "anything else"}, restaurant_phone=restaurant.phone,
        timestamp=1_700_000_001)
    await handle_inbound(db_session, text_in, restaurant_id=restaurant.id)
    await db_session.flush()

    n = await db_session.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.restaurant_id == restaurant.id,
            Conversation.phone.in_(["971500000099", "+971500000099"]),
        )
    )
    assert n == 1, f"catalogue basket split the conversation thread: {n} rows (F71)"
