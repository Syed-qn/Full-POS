"""Regression: a single WhatsApp message naming SEVERAL dishes must add EVERY dish.

Bug (prod order R1-0033): a customer wrote "1 chicken biryani, 1 mutton biryani,
and 2 special biryani, and 1 lemon mint and one test" in one message. The agent
could emit only ONE add_item, so just one dish was saved while the reply narrated a
full cart — the order summary then showed a single line. The fix lets add_item carry
an 'items' list and echoes the REAL cart from the DB.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone="+97141234567", timestamp=1717660800,
    )


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dishes = [
        (110, "Chicken Biryani", "22.00", "chicken biryani"),
        (201, "Mutton Karahi", "35.00", "mutton karahi"),
        (301, "Lemon Mint", "12.00", "lemon mint"),
    ]
    for num, name, price, norm in dishes:
        db_session.add(Dish(
            menu_id=menu.id, restaurant_id=restaurant_id, dish_number=num,
            name=name, price_aed=Decimal(price), category="Misc",
            is_available=True, name_normalized=norm,
        ))
    await db_session.commit()


async def test_multi_dish_message_adds_all_items(db_session, restaurant):
    """Three dishes named in ONE message → three OrderItem rows (not one)."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.mi-greet"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("2 chicken biryani, 1 mutton karahi and 3 lemon mint", "wamid.mi-1"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    from app.ordering.models import OrderItem
    items = (await db_session.execute(
        select(OrderItem).order_by(OrderItem.dish_number)
    )).scalars().all()
    by_num = {it.dish_number: it for it in items}
    assert set(by_num) == {110, 201, 301}, "every named dish must be added"
    assert by_num[110].qty == 2
    assert by_num[201].qty == 1
    assert by_num[301].qty == 3


async def test_multi_dish_reply_reflects_real_cart_not_llm_prose(db_session, restaurant):
    """The confirmation after a multi-add must be DB-backed (the real cart), so it
    can never narrate items that were not actually saved."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.mi-greet2"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("1 chicken biryani and 1 lemon mint", "wamid.mi-2"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    body = rows[-1].payload["body"]
    # The DB-backed cart echo lists both dishes with the real subtotal.
    assert "Chicken Biryani" in body
    assert "Lemon Mint" in body
    assert "Subtotal" in body


async def test_multi_dish_reply_never_redumps_the_menu(db_session, restaurant):
    """If the AI reply gets swapped to the full menu by the anti-hallucination guard,
    the multi-add confirmation must NOT re-dump the menu — just a short lead + cart."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.mi-menu"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("1 chicken biryani and 1 mutton karahi", "wamid.mi-menu2"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    body = rows[-1].payload["body"]
    # The cart is shown, but the welcome/menu block is not re-rendered.
    assert "Subtotal" in body
    assert "Here's our menu" not in body
    assert "Welcome" not in body


async def test_multi_dish_voice_note_adds_all_items(db_session, restaurant):
    """A VOICE note naming several dishes is transcribed then flows through the SAME
    add_item path as text — so both input modes add every dish. (User: "both voice
    and text ... smooth every way".)"""
    from app.whatsapp.factory import get_mock_provider

    await _seed_menu(db_session, restaurant.id)
    # FakeTranscriber decodes UTF-8 audio bytes back to text — this is the spoken order.
    get_mock_provider().set_media("media-multi-1", b"2 chicken biryani and 1 lemon mint")

    await handle_inbound(db_session, _msg("hi", "wamid.mi-vgreet"), restaurant_id=restaurant.id)
    await db_session.commit()

    audio = InboundMessage(
        wa_message_id="wamid.mi-voice", from_phone="+971501110001", type=MessageType.AUDIO,
        payload={"audio_id": "media-multi-1", "mime": "audio/ogg", "voice": True},
        restaurant_phone="+97141234567", timestamp=1717660900,
    )
    await handle_inbound(db_session, audio, restaurant_id=restaurant.id)
    await db_session.commit()

    from app.ordering.models import OrderItem
    items = (await db_session.execute(
        select(OrderItem).order_by(OrderItem.dish_number)
    )).scalars().all()
    by_num = {it.dish_number: it.qty for it in items}
    assert by_num == {110: 2, 301: 1}


async def test_clear_cart_empties_everything(db_session, restaurant):
    """"clear the cart" must empty the WHOLE cart, not remove a single dish."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.cc-greet"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(
        db_session, _msg("2 chicken biryani and 3 lemon mint", "wamid.cc-add"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    from app.ordering.models import OrderItem
    assert (await db_session.execute(select(OrderItem))).scalars().all()  # cart not empty

    await handle_inbound(
        db_session, _msg("please clear the cart, I want to order new", "wamid.cc-1"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert items == [], "the whole cart must be emptied"

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    assert "clear" in rows[-1].payload["body"].lower()


async def test_multi_dish_quantity_update_sets_all(db_session, restaurant):
    """"make it 2 chicken biryani and 2 lemon mint" must update BOTH quantities — a
    single update_qty used to change one dish and silently drop the other."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.uq-greet"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(
        db_session, _msg("1 chicken biryani and 1 lemon mint", "wamid.uq-add"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("make it 2 chicken biryani and 2 lemon mint", "wamid.uq-1"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    from app.ordering.models import OrderItem
    items = (await db_session.execute(
        select(OrderItem).order_by(OrderItem.dish_number)
    )).scalars().all()
    by_num = {it.dish_number: it.qty for it in items}
    assert by_num.get(110) == 2, "chicken biryani must be 2"
    assert by_num.get(301) == 2, "lemon mint must ALSO be 2 (was silently dropped before)"


async def test_multi_dish_unknown_dish_is_reported_not_silently_dropped(db_session, restaurant):
    """A dish that isn't on the menu is surfaced ('couldn't find'), while the known
    dishes are still added — no silent loss."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.mi-greet3"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("1 chicken biryani and 1 unicorn stew", "wamid.mi-3"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    from app.ordering.models import OrderItem
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert {it.dish_number for it in items} == {110}

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    body = rows[-1].payload["body"].lower()
    assert "couldn't find" in body and "unicorn stew" in body
