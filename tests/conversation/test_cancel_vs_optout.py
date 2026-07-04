"""'Cancel' during an active order must cancel the order, not opt out of marketing.

Prod regression: customer had 1x Lemon mint in cart (no order confirmed yet) and
typed 'Cancel' → bot replied "You've been unsubscribed from marketing messages"
(marketing/optout.py's _STOP_KEYWORDS includes "cancel" as a WhatsApp-convention
opt-out word). The opt-out check in handle_inbound runs unconditionally BEFORE any
dialogue/cart-state check, so it swallowed the order-cancel intent that
_is_cancel_intent already exists to handle.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.marketing.optout import is_opted_out
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

_PHONE = "+971501119888"
_REST_PHONE = "+97141234567"


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=_PHONE, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone=_REST_PHONE, timestamp=1717660800,
    )


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == _PHONE)
    )).scalar_one()


async def _latest_body(db_session) -> str:
    row = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id.desc())
    )).scalars().first()
    return row.payload.get("body", "") if row else ""


async def _seed_draft_cart(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=201,
        name="Lemon Mint", price_aed=Decimal("12.00"), category="Drinks",
        is_available=True, name_normalized="lemon mint",
    )
    db_session.add(dish)
    await db_session.flush()

    await handle_inbound(db_session, _msg("hi", "wamid.cvo0"), restaurant_id=restaurant.id)
    await db_session.commit()

    customer = await get_or_create_customer(db_session, restaurant_id=restaurant.id, phone=_PHONE)
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    await add_item(db_session, order=order, dish=dish, qty=1)
    await db_session.flush()

    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_phase": "ordering", "dialogue_state": "collecting_items",
                  "draft_order_id": order.id, "pending_order_id": order.id}
    await db_session.commit()
    return order


async def test_bare_cancel_with_active_cart_cancels_order_not_marketing(db_session, restaurant):
    order = await _seed_draft_cart(db_session, restaurant)

    await handle_inbound(db_session, _msg("Cancel", "wamid.cvo1"), restaurant_id=restaurant.id)
    await db_session.commit()

    body = await _latest_body(db_session)
    low = body.lower()
    assert "cancelled" in low
    assert "unsubscribed" not in low
    assert "marketing" not in low

    await db_session.refresh(order)
    assert str(order.status) == "cancelled"

    # Must NOT have recorded a marketing opt-out as a side effect of an order cancel.
    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone=_PHONE)


async def test_bare_cancel_no_active_order_still_opts_out(db_session, restaurant):
    """No order/cart context → 'cancel' keeps its WhatsApp-convention opt-out meaning."""
    await handle_inbound(db_session, _msg("hi", "wamid.cvo2"), restaurant_id=restaurant.id)
    await db_session.commit()

    await handle_inbound(db_session, _msg("cancel", "wamid.cvo3"), restaurant_id=restaurant.id)
    await db_session.commit()

    body = await _latest_body(db_session)
    assert "unsubscribed" in body.lower()
    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone=_PHONE)


async def test_unsubscribe_keyword_always_opts_out_even_mid_order(db_session, restaurant):
    """Unambiguous compliance keywords (not overloaded with order semantics) still
    always opt out, even with an active cart — only 'cancel'/'stop' are contextual."""
    await _seed_draft_cart(db_session, restaurant)

    await handle_inbound(db_session, _msg("unsubscribe", "wamid.cvo4"), restaurant_id=restaurant.id)
    await db_session.commit()

    body = await _latest_body(db_session)
    assert "unsubscribed" in body.lower()
    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone=_PHONE)
