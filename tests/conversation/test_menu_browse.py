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


async def _seed_many_dishes(db_session, restaurant_id, count: int = 5):
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    names = [
        "Chicken Biryani", "Mutton Karahi", "Paneer Tikka", "Dal Makhani",
        "Butter Chicken", "Fish Curry", "Veg Pulao",
    ]
    for i in range(count):
        name = names[i % len(names)] + (f" {i}" if i >= len(names) else "")
        db_session.add(Dish(
            menu_id=menu.id, restaurant_id=restaurant_id, dish_number=100 + i,
            name=name, price_aed=Decimal("20.00") + i,
            category="Rice" if i % 2 == 0 else "Curries",
            is_available=True, name_normalized=name.lower(),
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


def _outbox_bodies(rows: list[OutboxMessage]) -> list[str]:
    return [r.payload.get("body", "") for r in rows if r.payload.get("type") == "text"]


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
    """'OK show me' sends catalogue or text menu without LLM."""
    await _seed_menu(db_session, restaurant.id)
    await handle_inbound(db_session, _msg("hi", "wamid.mb2-hi"), restaurant_id=restaurant.id)
    await db_session.commit()

    with patch(
        "app.llm.fake.FakeConversationAgent.respond",
        new=AsyncMock(side_effect=AssertionError("LLM must not run for menu browse")),
    ):
        await handle_inbound(
            db_session, _msg("OK show me", "wamid.mb2-show"),
            restaurant_id=restaurant.id,
        )
    await db_session.commit()

    rows = (await db_session.execute(
        select(OutboxMessage).order_by(OutboxMessage.id)
    )).scalars().all()
    assert _outbox_has_menu(rows[1:])


@pytest.mark.asyncio
async def test_suggest_me_something_uses_sub_agent_when_many_matches(db_session, restaurant):
    """'suggest me something' with >3 dishes invokes suggestion sub-agent, not full menu."""
    await _seed_many_dishes(db_session, restaurant.id, count=5)
    await handle_inbound(db_session, _msg("hi", "wamid.mb3-hi"), restaurant_id=restaurant.id)
    await db_session.commit()

    mock_suggest = AsyncMock(return_value={
        "intro": "Here are some great picks!",
        "picks": [
            {"dish_name": "Chicken Biryani", "reason": "Our signature dish"},
            {"dish_name": "Mutton Karahi", "reason": "Rich and flavourful"},
        ],
    })

    with patch(
        "app.llm.fake.FakeConversationAgent.respond",
        new=AsyncMock(side_effect=AssertionError("LLM must not run for suggestions")),
    ), patch(
        "app.llm.factory.get_suggestion_agent",
    ) as mock_factory:
        mock_factory.return_value.suggest = mock_suggest
        await handle_inbound(
            db_session, _msg("suggest me something", "wamid.mb3-suggest"),
            restaurant_id=restaurant.id,
        )
    await db_session.commit()

    mock_suggest.assert_awaited_once()
    call_candidates = mock_suggest.await_args.args[0]
    assert len(call_candidates) >= 4

    rows = (await db_session.execute(
        select(OutboxMessage)
        .where(OutboxMessage.idempotency_key.like("%mb3-suggest%"))
        .order_by(OutboxMessage.id)
    )).scalars().all()
    bodies = _outbox_bodies(rows)
    assert len(bodies) == 1
    suggestion_body = bodies[0]
    assert "great picks" in suggestion_body or "signature dish" in suggestion_body
    assert "Chicken Biryani" in suggestion_body
    assert "Mutton Karahi" in suggestion_body
    assert "Paneer Tikka" not in suggestion_body