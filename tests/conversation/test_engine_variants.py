"""Bot serving-size variants: plain order = single (base price), named size = variant.

Variants are opt-in bigger portions on top of the base single serve. The bot never
asks "which size?" — ordering a dish plainly adds one single serve at the base price;
a bigger portion is applied only when the customer names it.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import (
    _execute_ai_add_item,
    _execute_ai_update_qty,
    handle_inbound,
)
from app.conversation.models import Conversation
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


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == PHONE)
    )).scalar_one()


_BUNDLE = [{"name": "2 serve", "price_aed": "30.00", "dish_number": None}]


async def test_ordering_qty_2_uses_the_bundle_price(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _BUNDLE)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)

    # Ordering quantity 2 of a dish that has a "2 serve" bundle → one bundle at AED 30.
    status = await _execute_ai_add_item(
        db_session, conv, _msg("2 chicken biryani", "i1"), restaurant.id,
        "chicken biryani", 2, "",
    )
    await db_session.commit()
    assert status == "added"
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "2 serve"
    assert items[0].qty == 1
    assert items[0].price_aed == Decimal("30.00")


async def test_make_it_2_switches_single_to_bundle(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _BUNDLE)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("1 chicken biryani", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)

    outcome, label, is_bundle = await _execute_ai_update_qty(
        db_session, conv, restaurant.id, "chicken biryani", 2
    )
    await db_session.commit()
    assert outcome == "updated" and is_bundle
    assert label == "Chicken Biryani (2 serve)"
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "2 serve"
    assert items[0].qty == 1
    assert items[0].price_aed == Decimal("30.00")


async def test_make_it_3_with_no_bundle_reverts_to_singles(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _BUNDLE)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("1 chicken biryani", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    # Bundle to 2 serve first…
    await _execute_ai_update_qty(db_session, conv, restaurant.id, "chicken biryani", 2)
    await db_session.commit()
    # …then "make it 3" — no 3-serve bundle → 3× single at the base price.
    outcome, _label, is_bundle = await _execute_ai_update_qty(
        db_session, conv, restaurant.id, "chicken biryani", 3
    )
    await db_session.commit()
    assert outcome == "updated" and not is_bundle
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name is None
    assert items[0].qty == 3
    assert items[0].price_aed == Decimal("20.00")


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
