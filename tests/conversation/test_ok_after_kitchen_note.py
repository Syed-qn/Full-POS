"""Regression: bare 'Ok' after a kitchen-note cart edit must proceed to checkout,
never hit the webhook generic-error apology."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.menu.models import Dish, Menu
from app.ordering.service import add_item, create_draft_order, get_or_create_customer
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str, phone: str = "+971585997894") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


@pytest.mark.asyncio
async def test_ok_after_kitchen_note_proceeds_to_address(db_session, restaurant):
    menu = Menu(
        restaurant_id=restaurant.id, version=1, status="active", source_files=[],
    )
    db_session.add(menu)
    await db_session.flush()
    combo = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=10,
        name="Chicken Biriyani + Lemon Mint",
        price_aed=Decimal("140.00"),
        category="Combo",
        is_available=True,
        name_normalized="chicken biriyani lemon mint",
    )
    db_session.add(combo)
    await db_session.flush()

    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971585997894"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=cust.id
    )
    await add_item(db_session, order=order, dish=combo, qty=1)
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="+971585997894",
        counterpart="customer",
        state={
            "draft_order_id": order.id,
            "dialogue_phase": "ordering",
            "dialogue_state": "collecting_items",
        },
    )
    db_session.add(conv)
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg(
            "Give me chest peice and double masala in biriyani",
            "wamid.mod",
        ),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("Ok", "wamid.ok"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    rows = (
        await db_session.scalars(select(OutboxMessage).order_by(OutboxMessage.id))
    ).all()
    bodies = [r.payload.get("body", "") for r in rows]
    assert not any(
        "something went wrong on our end" in b.lower() for b in bodies
    ), bodies[-3:]
    assert any(
        "delivery location" in b.lower() or "share your" in b.lower()
        for b in bodies
    ), bodies[-2:]