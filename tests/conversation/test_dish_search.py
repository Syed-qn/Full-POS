import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.conversation.engine import (
    _is_menu_browse_intent,
    _parse_dish_search_query,
    handle_inbound,
)
from app.menu.models import Dish, Menu
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str = "wamid.ds1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


@pytest.fixture
async def seeded_menu_with_chicken(db_session, restaurant):
    """Active menu with a boneless chicken dish for ingredient search tests."""
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=301,
        name="Boneless Chicken Tikka", price_aed=Decimal("28.00"),
        category="Starters", is_available=True, name_normalized="boneless chicken tikka",
        description="Tender boneless chicken pieces marinated in spices",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=302,
        name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


def test_parse_dish_search_boneless_chicken():
    assert _parse_dish_search_query("I want to have boneless chicken") == "boneless chicken"


def test_menu_browse_ok_show_me():
    assert _is_menu_browse_intent("OK show me") is True


def test_menu_browse_suggest():
    assert _is_menu_browse_intent("Suggest me something") is True


@pytest.mark.asyncio
async def test_dish_search_sends_matching_dishes(db_session, restaurant, seeded_menu_with_chicken):
    """Text mode: inbound boneless query returns bullet list with at least one dish."""
    await handle_inbound(db_session, _msg("hi", "wamid.ds-hi"), restaurant_id=restaurant.id)
    await db_session.commit()

    with patch(
        "app.llm.fake.FakeConversationAgent.respond",
        new=AsyncMock(side_effect=AssertionError("LLM must not run for dish search")),
    ):
        await handle_inbound(
            db_session, _msg("I want boneless chicken", "wamid.ds-search"),
            restaurant_id=restaurant.id,
        )
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    body = rows[-1].payload["body"]
    assert "chicken" in body.lower()
    assert "AED" in body