"""Bot serving-size variants: plain order = single (base price), named size = variant.

Variants are opt-in bigger portions on top of the base single serve. The bot never
asks "which size?" — ordering a dish plainly adds one single serve at the base price;
a bigger portion is applied only when the customer names it.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.ordering.models import OrderItem
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

PHONE = "+971501110001"


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=PHONE,
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def _seed_biryani(db_session, restaurant_id, variants):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("20.00"),
        category="Biryani", is_available=True, name_normalized="chicken biryani",
        variants=variants,
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=201,
        name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


async def _last_body(db_session) -> str:
    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    return rows[-1].payload["body"]


_VARIANTS = [
    {"name": "Family", "price_aed": "55.00", "dish_number": None},
]


async def test_plain_order_adds_single_at_base_price_no_question(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _VARIANTS)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()

    # Ordering one without naming a size → single serve at the base price, NO question.
    await handle_inbound(db_session, _msg("one chicken biryani", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    assert "which size" not in (await _last_body(db_session)).lower()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name is None
    assert items[0].price_aed == Decimal("20.00")


async def test_named_size_applies_the_variant(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _VARIANTS)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(db_session, _msg("family biryani", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    assert "which size" not in (await _last_body(db_session)).lower()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "Family"
    assert items[0].price_aed == Decimal("55.00")


async def test_no_variant_dish_adds_directly(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _VARIANTS)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(db_session, _msg("mutton karahi", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name is None
    assert items[0].dish_number == 201
