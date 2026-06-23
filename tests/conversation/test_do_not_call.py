""""Don't call me" → persistent customer contact preference.

When a customer asks not to be phoned, we set ``Customer.tags['do_not_call']`` so
every rider stop can show a "message only" flag. Detection is non-intercepting: the
flag is set and the message still flows through the normal ordering path.
"""
from sqlalchemy import select

from app.conversation.engine import _mentions_do_not_call, handle_inbound
from app.ordering.models import Customer
from app.whatsapp.port import InboundMessage, MessageType

PHONE = "+971501119999"


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=PHONE, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone="+97141234567", timestamp=1717660800,
    )


def test_mentions_do_not_call_positive():
    for t in [
        "please don't call",
        "dont call me, just message",
        "Do Not Call — text instead",
        "no calls please",
        "kindly dont ring",
        "just message me",
        "don’t call",  # curly apostrophe
    ]:
        assert _mentions_do_not_call(t), t


def test_mentions_do_not_call_negative():
    for t in ["one biryani please", "call me when you arrive", "", "where is my order", None]:
        assert not _mentions_do_not_call(t), t


async def _customer(db_session) -> Customer | None:
    return (await db_session.execute(
        select(Customer).where(Customer.phone == PHONE)
    )).scalar_one_or_none()


async def test_dont_call_sets_customer_preference(db_session, restaurant):
    await handle_inbound(db_session, _msg("please don't call, just message", "d1"),
                         restaurant_id=restaurant.id)
    await db_session.commit()
    cust = await _customer(db_session)
    assert cust is not None
    assert (cust.tags or {}).get("do_not_call") is True


async def test_ordinary_message_does_not_set_preference(db_session, restaurant):
    await handle_inbound(db_session, _msg("call me when you reach", "d2"),
                         restaurant_id=restaurant.id)
    await db_session.commit()
    cust = await _customer(db_session)
    # Either no customer yet, or one without the flag — but never set to True.
    assert not (cust and (cust.tags or {}).get("do_not_call"))
