"""Large-quantity anomaly guard: an unusually big line (e.g. "100000 lemon mints")
must NOT auto-add. The bot STAYS ACTIVE (never mutes the chat) and asks for a realistic
quantity, pointing bulk orders to the phone. Threshold is per-restaurant
(settings.max_item_qty, default 10)."""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Message
from app.llm.port import ConversationAgentResult
from app.ordering.models import OrderItem
from app.whatsapp.port import InboundMessage, MessageType


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=12,
        name="Lemon Mint", price_aed=Decimal("12.00"),
        category="Drinks", is_available=True, name_normalized="lemon mint",
    ))
    await db_session.commit()


async def _drive(db_session, restaurant, phone, wamid, text, result):
    inbound = InboundMessage(
        wa_message_id=wamid, from_phone=phone, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone=restaurant.phone, timestamp=1717660000,
    )
    with patch("app.llm.fake.FakeConversationAgent.respond",
               new=AsyncMock(return_value=result)):
        await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()


async def _conv(db_session, restaurant, phone):
    from app.conversation.service import get_or_create_conversation
    return await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )


async def _items(db_session, conv):
    draft = conv.state.get("draft_order_id")
    if not draft:
        return []
    return (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == draft)
    )).all()


async def test_large_add_qty_escalates_and_does_not_add(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)
    phone = "+971500001111"
    result = ConversationAgentResult(
        message="Added!", action="add_item",
        action_data={"dish_query": "lemon mint", "qty": 100000, "special_note": ""},
    )
    await _drive(db_session, restaurant, phone, "wamid.big1", "100000 lemon mints", result)

    conv = await _conv(db_session, restaurant, phone)
    assert conv.manual_takeover is False         # bot stays ACTIVE, never muted
    assert await _items(db_session, conv) == []  # nothing auto-added

    msgs = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id,
                              Message.direction == "outbound")
    )).all()
    bodies = " ".join((m.payload or {}).get("body", "") for m in msgs).lower()
    assert "big order" in bodies                  # asks for a realistic quantity, not silence


async def test_normal_qty_still_adds(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)
    phone = "+971500002222"
    result = ConversationAgentResult(
        message="Added!", action="add_item",
        action_data={"dish_query": "lemon mint", "qty": 2, "special_note": ""},
    )
    await _drive(db_session, restaurant, phone, "wamid.ok1", "2 lemon mints", result)

    conv = await _conv(db_session, restaurant, phone)
    assert conv.manual_takeover is False
    items = await _items(db_session, conv)
    assert len(items) == 1 and items[0].qty == 2


async def test_large_update_qty_escalates_and_keeps_old_qty(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)
    phone = "+971500003333"
    add = ConversationAgentResult(
        message="Added!", action="add_item",
        action_data={"dish_query": "lemon mint", "qty": 1, "special_note": ""},
    )
    await _drive(db_session, restaurant, phone, "wamid.u1", "lemon mint", add)
    upd = ConversationAgentResult(
        message="ok", action="update_qty",
        action_data={"dish_query": "lemon mint", "qty": 100000},
    )
    await _drive(db_session, restaurant, phone, "wamid.u2", "not 1. 100000", upd)

    conv = await _conv(db_session, restaurant, phone)
    assert conv.manual_takeover is False         # bot stays ACTIVE, never muted
    items = await _items(db_session, conv)
    assert items and items[0].qty == 1   # unchanged, not set to 100000
