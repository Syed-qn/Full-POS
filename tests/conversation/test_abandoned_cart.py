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
from app.ordering.models import OrderItem
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


async def _set_cart_settings(db_session, restaurant, *, recovery, expiry, reminder):
    restaurant.settings = {
        **restaurant.settings,
        "cart_recovery_minutes": recovery,
        "cart_expiry_minutes": expiry,
        "cart_reminder_enabled": reminder,
    }
    await db_session.commit()


async def test_abandoned_cart_nudges_once(db_session, restaurant):
    from app.conversation import worker as cart_worker

    await _build_abandoned_cart(db_session, restaurant.id)
    # recovery=0 → a just-quiet cart qualifies; expiry high so it isn't cleared.
    await _set_cart_settings(db_session, restaurant, recovery=0, expiry=9999, reminder=True)

    with patch.object(cart_worker, "async_session_factory", _make_session_factory(db_session)):
        first = await cart_worker._run_sweep()
        second = await cart_worker._run_sweep()  # once-only

    assert first == 1
    assert second == 0

    nudges = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    bodies = [n.payload["body"] for n in nudges]
    assert any("still have items in your cart" in b for b in bodies)
    # The nudge shows the actual cart + a concrete next step (not a dead-end yes/no),
    # so a returning customer has something to act on.
    assert any("Chicken Biryani" in b for b in bodies)
    assert any("done" in b.lower() for b in bodies)

    conv = (await db_session.scalars(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).one()
    assert conv.state.get("abandoned_nudged") is True


async def test_active_customer_is_not_nudged(db_session, restaurant):
    """Re-engagement guard: a freshly-touched conversation (customer just messaged)
    is never nudged, even if the bulk query thinks it crossed the threshold."""
    from app.conversation import worker as cart_worker

    await _build_abandoned_cart(db_session, restaurant.id)
    # recovery far in the future relative to a just-built cart → fresh quiet < recovery.
    await _set_cart_settings(db_session, restaurant, recovery=120, expiry=9999, reminder=True)

    with patch.object(cart_worker, "async_session_factory", _make_session_factory(db_session)):
        count = await cart_worker._run_sweep()

    assert count == 0
    items = (await db_session.scalars(select(OrderItem))).all()
    assert items  # cart untouched — customer is mid-order


async def test_no_nudge_without_cart(db_session, restaurant):
    """A conversation with no draft order is not nudged."""
    from app.conversation import worker as cart_worker

    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.n1"), restaurant_id=restaurant.id)
    await db_session.commit()
    await _set_cart_settings(db_session, restaurant, recovery=0, expiry=9999, reminder=True)

    with patch.object(cart_worker, "async_session_factory", _make_session_factory(db_session)):
        count = await cart_worker._run_sweep()

    assert count == 0


async def test_reminder_disabled_sends_no_nudge(db_session, restaurant):
    """With the reminder toggle OFF, no nudge is sent and the cart is left intact."""
    from app.conversation import worker as cart_worker

    await _build_abandoned_cart(db_session, restaurant.id)
    await _set_cart_settings(db_session, restaurant, recovery=0, expiry=9999, reminder=False)

    with patch.object(cart_worker, "async_session_factory", _make_session_factory(db_session)):
        count = await cart_worker._run_sweep()

    assert count == 0
    items = (await db_session.scalars(select(OrderItem))).all()
    assert items  # cart untouched


async def test_expired_cart_is_auto_cleared(db_session, restaurant):
    """Past cart_expiry_minutes, the draft cart is emptied and the pointer dropped."""
    from app.conversation import worker as cart_worker

    await _build_abandoned_cart(db_session, restaurant.id)
    await _set_cart_settings(db_session, restaurant, recovery=0, expiry=0, reminder=True)

    with patch.object(cart_worker, "async_session_factory", _make_session_factory(db_session)):
        await cart_worker._run_sweep()

    items = (await db_session.scalars(select(OrderItem))).all()
    assert items == []  # cleared
    conv = (await db_session.scalars(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).one()
    assert conv.state.get("draft_order_id") is None
