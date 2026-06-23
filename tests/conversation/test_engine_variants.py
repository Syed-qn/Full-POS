"""Bot serving-size variant flow: ask once, named-size skips question, default-on-fail."""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
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
        name="Chicken Biryani", price_aed=Decimal("18.00"),
        category="Biryani", is_available=True, name_normalized="chicken biryani",
        variants=variants,
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=201,
        name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == PHONE)
    )).scalar_one()


async def _last_body(db_session) -> str:
    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    return rows[-1].payload["body"]


_SERVE_VARIANTS = [
    {"name": "1 serve", "price_aed": "18.00", "dish_number": None},
    {"name": "4 serve", "price_aed": "60.00", "dish_number": None},
]


async def test_variant_dish_asks_size_then_prices_reply(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _SERVE_VARIANTS)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()

    # Ordering a variant dish without a size → bot asks, nothing added yet.
    await handle_inbound(db_session, _msg("chicken biryani", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    assert "which size" in (await _last_body(db_session)).lower()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert items == []
    conv = await _conv(db_session)
    assert conv.state.get("awaiting_variant") is not None

    # Reply with the size → priced and added at the variant price.
    await handle_inbound(db_session, _msg("4 serve", "i2"), restaurant_id=restaurant.id)
    await db_session.commit()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "4 serve"
    assert items[0].price_aed == Decimal("60.00")
    conv = await _conv(db_session)
    assert conv.state.get("awaiting_variant") is None


async def test_named_size_skips_the_question(db_session, restaurant):
    variants = [
        {"name": "Regular", "price_aed": "18.00", "dish_number": None},
        {"name": "Family", "price_aed": "55.00", "dish_number": None},
    ]
    await _seed_biryani(db_session, restaurant.id, variants)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(db_session, _msg("family biryani", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    assert "which size" not in (await _last_body(db_session)).lower()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "Family"
    assert items[0].price_aed == Decimal("55.00")


async def test_unmatched_reply_reasks_then_defaults(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _SERVE_VARIANTS)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("chicken biryani", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()

    # First unmatched reply → re-ask, still nothing added.
    await handle_inbound(db_session, _msg("zzz", "i2"), restaurant_id=restaurant.id)
    await db_session.commit()
    assert (await db_session.execute(select(OrderItem))).scalars().all() == []

    # Second unmatched reply → default to first (cheapest) variant, item added.
    await handle_inbound(db_session, _msg("zzz", "i3"), restaurant_id=restaurant.id)
    await db_session.commit()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name == "1 serve"
    assert items[0].price_aed == Decimal("18.00")


async def test_no_variant_dish_adds_directly(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _SERVE_VARIANTS)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(db_session, _msg("mutton karahi", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    assert "which size" not in (await _last_body(db_session)).lower()
    items = (await db_session.execute(select(OrderItem))).scalars().all()
    assert len(items) == 1
    assert items[0].variant_name is None
    assert items[0].dish_number == 201


async def test_greeting_clears_pending_variant(db_session, restaurant):
    await _seed_biryani(db_session, restaurant.id, _SERVE_VARIANTS)
    await handle_inbound(db_session, _msg("hi", "g1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("chicken biryani", "i1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    assert conv.state.get("awaiting_variant") is not None

    # "hi" mid-question resets cleanly — no pending variant lingers.
    await handle_inbound(db_session, _msg("hi", "g2"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    assert conv.state.get("awaiting_variant") is None
