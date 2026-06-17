from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.conversation.service import get_or_create_conversation, set_manual_takeover
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _make_inbound(wa_id="wamid.test-engine-1", text="hi") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971509876543",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def _seed_menu(db_session, restaurant_id):
    """Active menu: two available dishes + one unavailable."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
                        name="Chicken Biryani", price_aed=Decimal("22.00"),
                        category="Rice", is_available=True))
    db_session.add(Dish(menu_id=menu.id, restaurant_id=restaurant_id, dish_number=201,
                        name="Mutton Karahi", price_aed=Decimal("35.00"),
                        category="Curries", is_available=True))
    db_session.add(Dish(menu_id=menu.id, restaurant_id=restaurant_id, dish_number=301,
                        name="Falooda", price_aed=Decimal("12.00"),
                        category="Desserts", is_available=False))
    await db_session.commit()
    return menu


async def test_greeting_sends_menu_to_outbox(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _make_inbound(), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) == 1
    body: str = rows[0].payload["body"]
    assert "• Chicken Biryani — AED 22" in body
    assert "• Mutton Karahi — AED 35" in body
    assert "110." not in body  # dish numbers are not shown to customers
    assert "Falooda" not in body  # unavailable


async def test_greeting_advances_state_to_menu_sent(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _make_inbound(), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.phone == "+971509876543")
        )
    ).scalar_one()
    assert conv.state["dialogue_state"] == "menu_sent"


async def test_manual_takeover_short_circuits_bot(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id,
        phone="+971509876543", counterpart="customer",
    )
    await db_session.commit()
    await set_manual_takeover(db_session, conversation_id=conv.id, taken_over_by=99)
    await db_session.commit()

    await handle_inbound(db_session, _make_inbound(), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert rows == []  # bot sent nothing


async def test_second_message_after_menu_sent_does_not_resend_menu(db_session, restaurant):
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _make_inbound(), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(
        db_session, _make_inbound(wa_id="wamid.test-engine-2", text="I want biryani"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    # Just verify there are exactly 2 messages total (greeting + order response)
    assert len(rows) == 2


async def test_live_location_ping_outside_address_capture_is_silently_dropped(db_session, restaurant):
    """Repeated live-location updates after address confirmed produce no outbound message."""
    from app.conversation.service import get_or_create_conversation

    # Put conversation in post_order phase (simulates order already placed)
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971509990099", counterpart="customer"
    )
    conv.state = {"dialogue_phase": "post_order", "dialogue_state": "order_placed"}
    await db_session.commit()

    location_msg = InboundMessage(
        wa_message_id="wamid.live-loc-1",
        from_phone="+971509990099",
        restaurant_phone=restaurant.phone,
        type=MessageType.LOCATION,
        payload={"latitude": 25.2048, "longitude": 55.2708, "is_live": True},
        timestamp=1717661000,
    )
    await handle_inbound(db_session, location_msg, restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971509990099")
    )).scalars().all()
    assert len(rows) == 0  # no reply sent


async def test_location_in_awaiting_confirmation_phase_is_silently_dropped(db_session, restaurant):
    """Location ping during awaiting_confirmation (e.g. live share still active) produces no reply."""
    from app.conversation.service import get_or_create_conversation

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971509990098", counterpart="customer"
    )
    conv.state = {"dialogue_phase": "awaiting_confirmation", "dialogue_state": "awaiting_confirmation"}
    await db_session.commit()

    location_msg = InboundMessage(
        wa_message_id="wamid.live-loc-2",
        from_phone="+971509990098",
        restaurant_phone=restaurant.phone,
        type=MessageType.LOCATION,
        payload={"latitude": 25.2048, "longitude": 55.2708, "is_live": True},
        timestamp=1717661001,
    )
    await handle_inbound(db_session, location_msg, restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971509990098")
    )).scalars().all()
    assert len(rows) == 0


async def test_stop_keyword_records_optout(db_session, restaurant):
    from app.marketing.optout import is_opted_out

    inbound = InboundMessage(
        wa_message_id="stop-test-1",
        from_phone="+971501234999",
        restaurant_phone=restaurant.phone,
        type=MessageType.TEXT,
        payload={"text": "STOP"},
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()
    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501234999")


async def test_natural_language_optout_records_optout(db_session, restaurant):
    """Natural-language phrase triggers opt-out with source='natural_language'."""
    from app.marketing.optout import is_opted_out
    from app.marketing.models import OptOut
    from sqlalchemy import select

    inbound = InboundMessage(
        wa_message_id="nl-optout-1",
        from_phone="+971501234777",
        restaurant_phone=restaurant.phone,
        type=MessageType.TEXT,
        payload={"text": "don't send me any more messages please"},
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()
    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501234777")

    row = (await db_session.execute(
        select(OptOut).where(OptOut.phone == "+971501234777", OptOut.restaurant_id == restaurant.id)
    )).scalar_one()
    assert row.source == "natural_language"


async def test_natural_language_optout_sends_confirmation(db_session, restaurant):
    inbound = InboundMessage(
        wa_message_id="nl-optout-2",
        from_phone="+971501234778",
        restaurant_phone=restaurant.phone,
        type=MessageType.TEXT,
        payload={"text": "don't send me any more messages please"},
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501234778")
    )).scalars().all()
    assert len(rows) == 1
    assert "unsubscribed" in rows[0].payload["body"].lower()


async def test_ordering_message_not_misclassified_as_optout(db_session, restaurant):
    from app.marketing.optout import is_opted_out

    await _seed_menu(db_session, restaurant.id)

    inbound = InboundMessage(
        wa_message_id="not-optout-1",
        from_phone="+971501234779",
        restaurant_phone=restaurant.phone,
        type=MessageType.TEXT,
        payload={"text": "I want to order 2 chicken biryani"},
        timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()
    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501234779")
