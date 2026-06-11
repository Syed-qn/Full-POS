"""Abandoned-cart sweep task test.

The sweep filters by ``Conversation.updated_at < cutoff``. We can't backdate
updated_at (a BEFORE UPDATE trigger resets it), so we patch ABANDONED_AFTER_MIN
to a negative value — making the cutoff a future timestamp so a just-created
conversation qualifies as "stale".
"""
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.menu.models import Dish, Menu
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _make_session_factory(session):
    @asynccontextmanager
    async def _factory():
        yield session
    return _factory


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone="+97141234567", timestamp=1717660800,
    )


async def _seed_menu(db_session, restaurant_id):
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=1,
        name="Chicken Biryani", price_aed=Decimal("28.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()


async def _build_abandoned_cart(db_session, restaurant_id):
    await _seed_menu(db_session, restaurant_id)
    await handle_inbound(db_session, _msg("hi", "wamid.a1"), restaurant_id=restaurant_id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("chicken biryani", "wamid.a2"), restaurant_id=restaurant_id)
    await db_session.commit()


async def test_abandoned_cart_nudges_once(db_session, restaurant):
    from app.conversation import worker as cart_worker

    await _build_abandoned_cart(db_session, restaurant.id)

    with patch.object(cart_worker, "async_session_factory", _make_session_factory(db_session)), \
         patch.object(cart_worker, "ABANDONED_AFTER_MIN", -1000):
        first = await cart_worker._run_sweep()
        second = await cart_worker._run_sweep()  # once-only

    assert first == 1
    assert second == 0

    nudges = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    bodies = [n.payload["body"] for n in nudges]
    assert any("still have items in your cart" in b for b in bodies)

    conv = (await db_session.scalars(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).one()
    assert conv.state.get("abandoned_nudged") is True


async def test_no_nudge_without_cart(db_session, restaurant):
    """A conversation with no draft order is not nudged."""
    from app.conversation import worker as cart_worker

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.n1"), restaurant_id=restaurant.id)
    await db_session.commit()

    with patch.object(cart_worker, "async_session_factory", _make_session_factory(db_session)), \
         patch.object(cart_worker, "ABANDONED_AFTER_MIN", -1000):
        count = await cart_worker._run_sweep()

    assert count == 0
