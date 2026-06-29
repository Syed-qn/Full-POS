"""Turning a dish OFF for the day: the bot says 'sold out today' (+ alternative),
not the misleading 'we don't have that', and an off dish can't be ordered."""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.models import Conversation, Message
from app.identity.models import Restaurant
from app.menu.models import Dish, Menu
from app.ordering.models import Customer
from app.whatsapp.port import InboundMessage, MessageType


async def _resto(db_session):
    r = Restaurant(name="R", phone="+97140000700", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    menu = Menu(restaurant_id=r.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    # Chicken Biryani turned OFF today; Mutton Biryani still available (same category).
    off = Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=1, name="Chicken Biryani",
               price_aed=Decimal("30"), category="Biryani", is_available=False,
               name_normalized="chicken biryani")
    on = Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=2, name="Mutton Biryani",
              price_aed=Decimal("35"), category="Biryani", is_available=True,
              name_normalized="mutton biryani")
    db_session.add_all([off, on])
    await db_session.flush()
    return r


async def test_unavailable_dish_offers_alternative(db_session):
    r = await _resto(db_session)
    conv = Conversation(restaurant_id=r.id, phone="+971500700001", counterpart="customer",
                        state={"dialogue_phase": "ordering"})
    db_session.add(conv)
    c = Customer(restaurant_id=r.id, phone="+971500700001", name="X")
    db_session.add(c)
    await db_session.commit()

    from app.conversation.engine import _execute_ai_add_item
    msg = InboundMessage(wa_message_id="w1", from_phone="+971500700001", type=MessageType.TEXT,
                         payload={"text": "1 chicken biryani"}, restaurant_phone=r.phone, timestamp=1717660800)
    status = await _execute_ai_add_item(db_session, conv, msg, r.id, "chicken biryani", 1)
    await db_session.commit()
    assert status == "unavailable"  # not "no_match"
    bodies = " ".join(str((m.payload or {}).get("body", "")) for m in (await db_session.scalars(
        select(Message).where(Message.direction == "outbound")
    )).all()).lower()
    assert "sold out today" in bodies and "chicken biryani" in bodies
    assert "mutton biryani" in bodies  # available same-category alternative offered


async def test_genuinely_off_menu_still_declines(db_session):
    """A dish that isn't on the menu at all still gets the off-menu decline (no false
    'sold out today')."""
    r = await _resto(db_session)
    conv = Conversation(restaurant_id=r.id, phone="+971500700002", counterpart="customer",
                        state={"dialogue_phase": "ordering"})
    db_session.add(conv)
    await db_session.commit()
    from app.conversation.engine import _execute_ai_add_item
    msg = InboundMessage(wa_message_id="w2", from_phone="+971500700002", type=MessageType.TEXT,
                         payload={"text": "sushi"}, restaurant_phone=r.phone, timestamp=1717660800)
    status = await _execute_ai_add_item(db_session, conv, msg, r.id, "sushi platter", 1)
    assert status == "no_match"
