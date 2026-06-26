"""Regression: at the confirm step, a non-confirm/non-cancel message must re-show the
REAL order summary from the DB — never a free-text reply that could claim a change
that wasn't applied.

Prod bug: in awaiting_confirmation a customer said "make it two special"; the bot
replied "updated to 2x, total 97" but never touched the DB, then confirmed the order
at the OLD total (AED 62, 1x). The model narrated a modification it didn't perform.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
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
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("20.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()


async def test_confirmation_no_action_reshows_real_summary(db_session, restaurant):
    """A modify-ish message at confirm time → the deterministic summary is re-shown
    and the order is left UNCHANGED (no fabricated 'updated to 2x')."""
    from app.ordering.models import OrderItem
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    await _seed_menu(db_session, restaurant.id)
    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110001"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    from app.menu.models import Dish
    chicken = (await db_session.execute(
        select(Dish).where(Dish.dish_number == 110, Dish.restaurant_id == restaurant.id)
    )).scalar_one()
    await add_item(db_session, order=order, dish=chicken, qty=1)

    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"dialogue_phase": "awaiting_confirmation",
               "pending_order_id": order.id, "draft_order_id": order.id},
    )
    db_session.add(conv)
    await db_session.commit()

    # A modification request at the confirm step (the fake maps unknown confirm-phase
    # text to no_action — exactly the case that used to forward a fabricated reply).
    await handle_inbound(
        db_session, _msg("two special, make it two please", "wamid.cf-1"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    body = rows[-1].payload["body"]
    # The DETERMINISTIC summary is re-shown (real dish, real subtotal) — not a free-text
    # "Please confirm or cancel" / fabricated update.
    assert "Order summary:" in body
    assert "Chicken Biryani" in body
    assert "1x Chicken Biryani" in body

    # The order itself is unchanged — still exactly 1 chicken biryani.
    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).scalars().all()
    assert len(items) == 1 and items[0].qty == 1
