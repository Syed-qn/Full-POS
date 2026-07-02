"""Regression: bare 'Ok' after order confirm must not trigger webhook error apology."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.conversation.service import record_message
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str, phone: str = "+971585997894") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


@pytest.mark.asyncio
async def test_ok_after_order_confirm_no_error_apology(db_session, restaurant):
    customer = Customer(
        restaurant_id=restaurant.id,
        phone="+971585997894",
        name="Syed",
        usual_order_times={},
        tags={},
        total_orders=1,
        total_spend=Decimal("15.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number="R1-0120",
        status=OrderStatus.CONFIRMED,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("15.00"),
        total=Decimal("15.00"),
    )
    db_session.add(order)
    await db_session.flush()
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="+971585997894",
        counterpart="customer",
        state={
            "dialogue_phase": "post_order",
            "dialogue_state": "order_placed",
            "draft_order_id": None,
            "pending_order_id": None,
        },
    )
    db_session.add(conv)
    await db_session.flush()
    await record_message(
        db_session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="text",
        payload={
            "body": (
                "Order confirmed! 🎉 Order #R1-0120\n"
                "Total: AED 15\nWallet credit applied: AED 10\n"
                "Pay on delivery: AED 5 (COD)\n"
                "Your food will arrive within ~40 minutes. We'll keep you posted! 🛵"
            ),
        },
    )
    await db_session.commit()

    await handle_inbound(db_session, _msg("Ok", "wamid.ok-post"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.scalars(select(OutboxMessage).order_by(OutboxMessage.id))).all()
    bodies = [r.payload.get("body", "") for r in rows]
    assert not any(
        "something went wrong on our end" in b.lower() for b in bodies
    ), bodies
    assert any(
        "keep you posted" in b.lower() or "got it" in b.lower() or "all set" in b.lower()
        for b in bodies
    ), bodies


@pytest.mark.asyncio
async def test_ok_after_resale_accept_no_error_apology(db_session, restaurant):
    customer = Customer(
        restaurant_id=restaurant.id,
        phone="+971585997894",
        name="Syed",
        usual_order_times={},
        tags={},
        total_orders=2,
        total_spend=Decimal("29.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number="R1-0086-RS-SOLD0120",
        status=OrderStatus.READY,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("14.00"),
        total=Decimal("14.00"),
    )
    db_session.add(order)
    await db_session.flush()
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="+971585997894",
        counterpart="customer",
        state={
            "dialogue_phase": "post_order",
            "dialogue_state": "order_placed",
            "resale_offer_id": None,
            "draft_order_id": None,
            "pending_order_id": None,
        },
    )
    db_session.add(conv)
    await db_session.flush()
    await record_message(
        db_session,
        conversation_id=conv.id,
        direction="outbound",
        wa_message_id=None,
        msg_type="text",
        payload={
            "body": (
                "Yours! 🎉 Order #R1-0086-RS-SOLD0120 — AED 14 (COD).\n"
                "It's already cooked and on its way fast."
            ),
        },
    )
    await db_session.commit()

    await handle_inbound(db_session, _msg("Ok", "wamid.ok-resale"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.scalars(select(OutboxMessage).order_by(OutboxMessage.id))).all()
    bodies = [r.payload.get("body", "") for r in rows]
    assert not any(
        "something went wrong on our end" in b.lower() for b in bodies
    ), bodies
    assert any(
        "keep you posted" in b.lower() or "got it" in b.lower() or "all set" in b.lower()
        for b in bodies
    ), bodies