import copy
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Message
from app.conversation.service import get_or_create_conversation
from app.identity.models import DEFAULT_SETTINGS, Restaurant
from app.ordering.models import Customer
from app.whatsapp.port import InboundMessage, MessageType


def _inb(r, phone, text):
    return InboundMessage(wa_message_id="w-tier", from_phone=phone, type=MessageType.TEXT,
                          payload={"text": text}, restaurant_phone=r.phone, timestamp=1717660900)


async def _last(db_session, conv_id):
    rows = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv_id, Message.direction == "outbound")
        .order_by(Message.id.desc())
    )).all()
    return str(rows[0].payload) if rows else ""


async def test_tier_query_answers_from_settings(db_session):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s["loyalty"]["enabled"] = True
    r = Restaurant(name="Tier R", phone="+97140000091", password_hash="x", lat=25.2, lng=55.2, settings=s)
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500000091", name="C",
                 total_orders=1, total_spend=Decimal("20.00"))
    db_session.add(c)
    await db_session.flush()
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=c.phone, counterpart="customer")
    conv.state = {"dialogue_phase": "post_order"}
    await db_session.commit()

    await handle_inbound(db_session, _inb(r, c.phone, "how do I reach gold?"), restaurant_id=r.id)
    await db_session.commit()
    body = (await _last(db_session, conv.id)).lower()
    assert "gold" in body or "silver" in body or "bronze" in body
