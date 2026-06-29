"""Redeem options at checkout — shown only to customers who have wallet credit or
a coupon issued to them; coupon codes typed at the summary are applied."""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import _redeem_context, _send_order_summary
from app.conversation.models import Message
from app.conversation.service import get_or_create_conversation
from app.coupons import service as coupons
from app.identity.models import Restaurant
from app.ordering.models import Customer, Order
from app.wallet import service as wallet
from app.whatsapp.port import InboundMessage, MessageType


async def _seed(db_session):
    r = Restaurant(name="Redeem R", phone="+97140000030", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500000030", name="Redeem C")
    db_session.add(c)
    await db_session.flush()
    return r, c


async def _order(db_session, r, c):
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="RX-1",
              status="pending_confirmation", subtotal=Decimal("60.00"),
              total=Decimal("60.00"), delivery_fee_aed=Decimal("0.00"))
    db_session.add(o)
    await db_session.flush()
    return o


async def _last_outbound(db_session, conv_id):
    rows = (await db_session.scalars(
        select(Message)
        .where(Message.conversation_id == conv_id, Message.direction == "outbound")
        .order_by(Message.id.desc())
    )).all()
    return str(rows[0].payload) if rows else ""


def _inb(r, phone, text):
    return InboundMessage(wa_message_id="w-redeem", from_phone=phone, type=MessageType.TEXT,
                          payload={"text": text}, restaurant_phone=r.phone, timestamp=1717660900)


async def test_no_credit_no_coupon_no_option(db_session):
    r, c = await _seed(db_session)
    avail, active = await _redeem_context(db_session, restaurant_id=r.id, customer_id=c.id)
    assert avail == Decimal("0.00")
    assert active == []


async def test_wallet_balance_shows_option(db_session):
    r, c = await _seed(db_session)
    await wallet.credit(db_session, restaurant_id=r.id, customer_id=c.id,
                        amount=Decimal("15.00"), idempotency_key="k", created_by="mgr:1")
    o = await _order(db_session, r, c)
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=c.phone, counterpart="customer")
    conv.state = {"dialogue_phase": "awaiting_confirmation", "pending_order_id": o.id}
    await db_session.flush()
    await _send_order_summary(db_session, conv, _inb(r, c.phone, ""), r.id, o)
    body = await _last_outbound(db_session, conv.id)
    assert "wallet credit" in body.lower()


async def test_no_option_when_empty(db_session):
    r, c = await _seed(db_session)
    o = await _order(db_session, r, c)
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=c.phone, counterpart="customer")
    conv.state = {"dialogue_phase": "awaiting_confirmation", "pending_order_id": o.id}
    await db_session.flush()
    await _send_order_summary(db_session, conv, _inb(r, c.phone, ""), r.id, o)
    body = await _last_outbound(db_session, conv.id)
    assert "wallet credit" not in body.lower()
    assert "coupon" not in body.lower()


async def test_typing_coupon_code_applies_it(db_session, restaurant):
    from app.conversation.engine import handle_inbound
    r = restaurant
    c = Customer(restaurant_id=r.id, phone="+971500000031", name="Coupon Typer")
    db_session.add(c)
    await db_session.flush()
    coupon = await coupons.issue_coupon(db_session, restaurant_id=r.id, customer_id=c.id,
                                        order_id=None, discount_aed=Decimal("10.00"))
    o = await _order(db_session, r, c)
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=c.phone, counterpart="customer")
    conv.state = {"dialogue_phase": "awaiting_confirmation", "pending_order_id": o.id}
    await db_session.commit()

    await handle_inbound(db_session, _inb(r, c.phone, coupon.code), restaurant_id=r.id)
    await db_session.commit()

    refreshed = await db_session.get(Order, o.id)
    assert refreshed.total == Decimal("50.00")  # 60 - 10
    assert refreshed.coupon_id == coupon.id


async def test_issued_coupon_shows_option(db_session):
    r, c = await _seed(db_session)
    await coupons.issue_coupon(db_session, restaurant_id=r.id, customer_id=c.id,
                               order_id=None, discount_aed=Decimal("10.00"))
    o = await _order(db_session, r, c)
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=c.phone, counterpart="customer")
    conv.state = {"dialogue_phase": "awaiting_confirmation", "pending_order_id": o.id}
    await db_session.flush()
    await _send_order_summary(db_session, conv, _inb(r, c.phone, ""), r.id, o)
    body = await _last_outbound(db_session, conv.id)
    assert "coupon" in body.lower()
