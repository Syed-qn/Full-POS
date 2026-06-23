"""Drink-style dishes: variants are SIZES the bot asks for (by menu category).

Unlike food (where the base price is the default single serve and a size is only
applied when named), a drink with size variants has no sensible default — so the
bot asks "Large or Small?" and adds the chosen size. A drink with no variants is
added straight away.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import _execute_ai_add_item, handle_inbound
from app.conversation.models import Conversation
from app.ordering.models import OrderItem
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

PHONE = "+971501110002"

_SIZES = [
    {"name": "Large", "price_aed": "12.00", "dish_number": None},
    {"name": "Small", "price_aed": "8.00", "dish_number": None},
]


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=PHONE, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone="+97141234567", timestamp=1717660800,
    )


async def _seed_drinks(db_session, restaurant_id, *, lemon_variants):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=300,
        name="Lemon Mint", price_aed=Decimal("10.00"), category="Drinks",
        is_available=True, name_normalized="lemon mint", variants=lemon_variants,
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=301,
        name="Water Bottle", price_aed=Decimal("2.00"), category="Drinks",
        is_available=True, name_normalized="water bottle", variants=[],
    ))
    await db_session.commit()


async def _last_body(db_session) -> str:
    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    return rows[-1].payload["body"]


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == PHONE)
    )).scalar_one()


async def test_drink_with_sizes_asks_which_size(db_session, restaurant):
    await _seed_drinks(db_session, restaurant.id, lemon_variants=_SIZES)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)

    status = await _execute_ai_add_item(
        db_session, conv, _msg("lemon mint", "i1"), restaurant.id, "lemon mint", 1, "",
    )
    await db_session.commit()
    assert status == "awaiting_size"
    body = (await _last_body(db_session)).lower()
    assert "size" in body and "large" in body and "small" in body
    assert (await db_session.execute(select(OrderItem))).scalars().all() == []
    assert (await _conv(db_session)).state.get("awaiting_size") is not None


async def test_drink_size_reply_adds_that_variant(db_session, restaurant):
    await _seed_drinks(db_session, restaurant.id, lemon_variants=_SIZES)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    await _execute_ai_add_item(
        db_session, conv, _msg("lemon mint", "i1"), restaurant.id, "lemon mint", 1, "",
    )
    await db_session.commit()

    await handle_inbound(db_session, _msg("large", "i2"), restaurant_id=restaurant.id)
    await db_session.commit()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "Large"
    assert items[0].qty == 1
    assert items[0].price_aed == Decimal("12.00")
    assert (await _conv(db_session)).state.get("awaiting_size") is None


async def test_drink_qty_two_asks_size_then_adds_both(db_session, restaurant):
    await _seed_drinks(db_session, restaurant.id, lemon_variants=_SIZES)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    status = await _execute_ai_add_item(
        db_session, conv, _msg("2 lemon mint", "i1"), restaurant.id, "lemon mint", 2, "",
    )
    await db_session.commit()
    assert status == "awaiting_size"

    await handle_inbound(db_session, _msg("small", "i2"), restaurant_id=restaurant.id)
    await db_session.commit()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "Small"
    assert items[0].qty == 2
    assert items[0].price_aed == Decimal("8.00")


async def test_drink_without_variants_adds_directly(db_session, restaurant):
    await _seed_drinks(db_session, restaurant.id, lemon_variants=_SIZES)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(db_session, _msg("water bottle", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    assert "size" not in (await _last_body(db_session)).lower()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name is None
    assert items[0].dish_number == 301


async def test_unmatched_size_reasks_then_defaults_to_first(db_session, restaurant):
    await _seed_drinks(db_session, restaurant.id, lemon_variants=_SIZES)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    await _execute_ai_add_item(
        db_session, conv, _msg("lemon mint", "i1"), restaurant.id, "lemon mint", 1, "",
    )
    await db_session.commit()

    # gibberish → re-ask, nothing added yet
    await handle_inbound(db_session, _msg("huh?", "i2"), restaurant_id=restaurant.id)
    await db_session.commit()
    assert (await db_session.execute(select(OrderItem))).scalars().all() == []
    assert (await _conv(db_session)).state.get("awaiting_size") is not None

    # still gibberish → default to the first size (Large), never loops
    await handle_inbound(db_session, _msg("dunno", "i3"), restaurant_id=restaurant.id)
    await db_session.commit()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "Large"
    assert (await _conv(db_session)).state.get("awaiting_size") is None
