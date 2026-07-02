"""W4 Task 5 — global read-only intents work inside a modify sub-flow.

F103/TX-28/TX-39: while the customer is in a modify_items/modify_confirm loop,
'show menu' and 'what's in my cart' must still be answered (not misread as a dish
to add/remove), and the modify FSM state must survive so the edit resumes.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

_PHONE = "+971501119099"
_REST_PHONE = "+97141234567"


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=_PHONE, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone=_REST_PHONE, timestamp=1717660800,
    )


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == _PHONE)
    )).scalar_one()


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("20.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()
    return menu


async def _enter_modify(db_session, restaurant):
    from app.menu.models import Dish
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.mgi0"), restaurant_id=restaurant.id)
    await db_session.commit()

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone=_PHONE
    )
    dish = await db_session.scalar(select(Dish).where(Dish.menu_id == menu.id))
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.flush()

    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_phase": "ordering",
                  "dialogue_state": "modify_items", "modify_order_id": order.id,
                  "pending_order_id": order.id, "draft_order_id": order.id,
                  "modify_proposed": []}
    await db_session.commit()
    return order


async def _latest_body(db_session) -> str:
    row = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id.desc())
    )).scalars().first()
    return row.payload.get("body", "") if row else ""


async def test_cart_query_during_modify_shows_cart_and_stays(db_session, restaurant):
    order = await _enter_modify(db_session, restaurant)

    await handle_inbound(
        db_session, _msg("what's in my cart", "wamid.mgi1"), restaurant_id=restaurant.id
    )
    await db_session.commit()

    body = await _latest_body(db_session)
    assert "cart" in body.lower()
    assert "biryani" in body.lower()
    # Modify FSM state must survive so the customer resumes their edit.
    conv = await _conv(db_session)
    assert conv.state.get("dialogue_state") == "modify_items"
    assert conv.state.get("modify_order_id") == order.id
    # Order still a draft — the read-only query never mutated / advanced it.
    await db_session.refresh(order)
    assert str(order.status) == "draft"


async def test_menu_request_during_modify_answers_and_stays(db_session, restaurant):
    order = await _enter_modify(db_session, restaurant)

    await handle_inbound(
        db_session, _msg("show menu", "wamid.mgi2"), restaurant_id=restaurant.id
    )
    await db_session.commit()

    body = await _latest_body(db_session)
    assert "biryani" in body.lower()
    conv = await _conv(db_session)
    assert conv.state.get("dialogue_state") == "modify_items"
    assert conv.state.get("modify_order_id") == order.id
