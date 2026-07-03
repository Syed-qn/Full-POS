import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.menu.models import Dish, Menu
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str = "wamid.mb1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def _seed_menu(db_session, restaurant_id):
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=201,
        name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()


def _outbox_has_menu(rows: list[OutboxMessage]) -> bool:
    types = [r.payload.get("type") for r in rows]
    bodies = [r.payload.get("body", "") for r in rows]
    return "product_list" in types or any("Chicken Biryani" in b for b in bodies)


@pytest.mark.asyncio
async def test_post_order_show_me_sends_menu(db_session, restaurant):
    """post_order + 'OK show me' → menu text or product_list; resets to ordering."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.mb-hi"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    conv.state = {**conv.state, "dialogue_phase": "post_order", "dialogue_state": "order_placed"}
    await db_session.commit()

    with patch(
        "app.llm.fake.FakeConversationAgent.respond",
        new=AsyncMock(side_effect=AssertionError("LLM must not run for menu browse")),
    ):
        await handle_inbound(db_session, _msg("OK show me", "wamid.mb-show"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    assert _outbox_has_menu(rows)

    conv = await _conv(db_session)
    assert conv.state["dialogue_phase"] == "ordering"
    assert conv.state["dialogue_state"] == "menu_sent"


@pytest.mark.asyncio
async def test_menu_browse_intent_triggers_catalog_or_text_menu(db_session, restaurant):
    """Browse intent ('suggest me something') sends catalogue or text menu without LLM."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.mb2-hi"), restaurant_id=restaurant.id)
    await db_session.commit()

    with patch(
        "app.llm.fake.FakeConversationAgent.respond",
        new=AsyncMock(side_effect=AssertionError("LLM must not run for menu browse")),
    ):
        await handle_inbound(
            db_session, _msg("suggest me something", "wamid.mb2-suggest"),
            restaurant_id=restaurant.id,
        )
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    assert _outbox_has_menu(rows[1:])