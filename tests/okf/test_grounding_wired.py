"""The conversation engine lazily builds + retrieves OKF grounding for a customer
question (proves the RAG path is wired end-to-end)."""
import copy
from decimal import Decimal

from sqlalchemy import func, select

from app.conversation.engine import _okf_grounding
from app.conversation.service import get_or_create_conversation
from app.identity.models import DEFAULT_SETTINGS, Restaurant
from app.menu.models import Dish, Menu
from app.okf.models import OkfDoc
from app.whatsapp.port import InboundMessage, MessageType


async def _resto(db_session):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    r = Restaurant(name="Ground R", phone="+97140000600", password_hash="x", lat=25.2, lng=55.2, settings=s)
    db_session.add(r)
    await db_session.flush()
    menu = Menu(restaurant_id=r.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=1, name="Chicken Biryani",
                        price_aed=Decimal("22"), category="Rice", is_available=True,
                        name_normalized="chicken biryani",
                        description="Halal chicken, basmati, mild spice."))
    await db_session.flush()
    return r


def _inb(r, phone, text):
    return InboundMessage(wa_message_id="w-g", from_phone=phone, type=MessageType.TEXT,
                          payload={"text": text}, restaurant_phone=r.phone, timestamp=1717660900)


async def test_grounding_lazily_builds_bundle_and_returns_facts(db_session):
    r = await _resto(db_session)
    phone = "+971500600001"
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=phone, counterpart="customer")
    # No OKF docs yet.
    assert await db_session.scalar(select(func.count(OkfDoc.id)).where(OkfDoc.restaurant_id == r.id)) == 0

    block = await _okf_grounding(db_session, conv, _inb(r, phone, "is the chicken halal?"), r.id)

    # Bundle was lazily built, and the grounding block carries the halal fact.
    assert await db_session.scalar(select(func.count(OkfDoc.id)).where(OkfDoc.restaurant_id == r.id)) > 0
    assert "GROUNDED KNOWLEDGE" in block
    assert "halal" in block.lower()


async def test_grounding_empty_for_non_text(db_session):
    r = await _resto(db_session)
    phone = "+971500600002"
    conv = await get_or_create_conversation(db_session, restaurant_id=r.id, phone=phone, counterpart="customer")
    loc = InboundMessage(wa_message_id="w-loc", from_phone=phone, type=MessageType.LOCATION,
                         payload={"latitude": 25.2, "longitude": 55.2}, restaurant_phone=r.phone, timestamp=1)
    assert await _okf_grounding(db_session, conv, loc, r.id) == ""
