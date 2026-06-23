"""Dish-info questions ("what's special in X") answer with the stored menu
description verbatim when present, else a short human line — and never hijack a
non-dish question.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import _dish_info_question, handle_inbound
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

PHONE = "+971501117777"
DESC = "Slow-cooked basmati with tender chicken.\nFragrant whole spices.\nServed with raita."


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=PHONE, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone="+97141234567", timestamp=1717660800,
    )


async def _seed(db_session, restaurant_id, *, biryani_desc):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=10,
        name="Chicken Biryani", price_aed=Decimal("28.00"), category="Biryani",
        is_available=True, name_normalized="chicken biryani", description=biryani_desc,
    ))
    await db_session.commit()


async def _last_body(db_session) -> str:
    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    return rows[-1].payload["body"]


def test_dish_info_question_extracts_name():
    assert _dish_info_question("what's special in the chicken biryani?") == "chicken biryani"
    assert _dish_info_question("tell me about Chicken Biryani") == "chicken biryani"
    assert _dish_info_question("what's in biryani") == "biryani"
    assert _dish_info_question("describe the paneer dish") == "paneer"
    assert _dish_info_question("one biryani please") is None
    assert _dish_info_question("") is None


async def test_shows_stored_description_when_present(db_session, restaurant):
    await _seed(db_session, restaurant.id, biryani_desc=DESC)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("what's special in the chicken biryani?", "q1"),
                         restaurant_id=restaurant.id)
    await db_session.commit()
    body = await _last_body(db_session)
    # Verbatim stored description (trimmed to 3 lines), no price added.
    assert "Slow-cooked basmati with tender chicken." in body
    assert "raita" in body
    assert "28" not in body


async def test_no_description_falls_back_to_short_line(db_session, restaurant):
    await _seed(db_session, restaurant.id, biryani_desc=None)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("what's special in chicken biryani?", "q1"),
                         restaurant_id=restaurant.id)
    await db_session.commit()
    body = (await _last_body(db_session)).strip()
    assert body  # said *something* human
    assert len(body.splitlines()) <= 3
    assert "AED" not in body


async def test_unknown_dish_does_not_hijack(db_session, restaurant):
    """A 'what is …' that doesn't resolve to a dish must NOT be answered here — it
    falls through to the normal AI flow (no break)."""
    await _seed(db_session, restaurant.id, biryani_desc=DESC)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    before = len((await db_session.execute(select(OutboxMessage))).scalars().all())
    await handle_inbound(db_session, _msg("what is your location?", "q1"),
                         restaurant_id=restaurant.id)
    await db_session.commit()
    body = await _last_body(db_session)
    # Whatever the AI replies, it must NOT be the biryani description.
    assert "Slow-cooked basmati" not in body
    after = len((await db_session.execute(select(OutboxMessage))).scalars().all())
    assert after > before  # a reply was still produced
