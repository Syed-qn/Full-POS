"""Safety gates against silent order dropping.

Each test drives a path where, before these gates, a cart/order could silently
vanish or an empty order could be placed with no error shown to the customer.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.conversation.models import Conversation
from app.conversation.engine import handle_inbound
from app.menu.models import Dish, Menu
from app.ordering.models import Order, OrderItem
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _txt(text, wa_id):
    return InboundMessage(
        wa_message_id=wa_id, from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone="+97141234567", timestamp=1717660800,
    )


async def _seed_menu(db_session, restaurant_id):
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=1, name="Chicken Biryani",
        price_aed=Decimal("20.00"), category="Biryani", is_available=True,
        name_normalized="chicken biryani",
    ))
    await db_session.commit()


async def _bodies(db_session):
    msgs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    return [m.payload.get("body", "") for m in msgs]


async def test_done_with_empty_cart_does_not_proceed(db_session, restaurant):
    """Saying 'done' with no items must NOT advance to address — it tells the customer
    the cart is empty and keeps them collecting items."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _txt("hi", "w1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _txt("done", "w2"), restaurant_id=restaurant.id)
    await db_session.commit()

    assert any("cart is empty" in b.lower() for b in await _bodies(db_session))
    conv = (await db_session.scalars(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).one()
    assert conv.state.get("dialogue_state") != "address_capture"


async def test_done_with_items_proceeds(db_session, restaurant):
    """Control: with a real item, 'done' advances normally (gate doesn't false-trip)."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _txt("hi", "w1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _txt("chicken biryani", "w2"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _txt("done", "w3"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = (await db_session.scalars(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).one()
    assert conv.state.get("dialogue_state") == "address_capture"
    order = (await db_session.scalars(select(Order))).one()
    items = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    assert len(items) == 1


async def test_manual_order_with_no_items_is_rejected(db_session, restaurant):
    """The manager manual-order path refuses an empty item list instead of placing an
    empty order."""
    from app.ordering.service import create_manual_order

    await _seed_menu(db_session, restaurant.id)
    with pytest.raises(ValueError, match="no items"):
        await create_manual_order(
            db_session, restaurant_id=restaurant.id, customer_phone="+971509999999",
            customer_name="X", items=[], apt_room="1", building="B1",
            receiver_name="X", address_notes=None, delivery_fee_aed=Decimal("0.00"),
        )
