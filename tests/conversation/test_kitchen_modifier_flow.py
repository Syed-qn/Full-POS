"""Kitchen-note / modifier clarification flow (biryani + chest piece + double masala)."""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.conversation.engine import _is_menu_request, handle_inbound
from app.conversation.models import Conversation
from app.llm.port import ConversationAgentResult
from app.ordering.models import OrderItem
from app.ordering.service import add_item, create_draft_order, get_or_create_customer
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str = "wamid.mod", phone: str = "+971501110099") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


@pytest.mark.parametrize(
    "text",
    [
        "i don't want menu",
        "I dont want menu I need chicken biriyani",
        "why are you sending me menu",
    ],
)
def test_negated_menu_phrases_are_not_menu_requests(text: str):
    assert _is_menu_request(text) is False


@pytest.mark.asyncio
async def test_with_modifiers_apply_note_to_in_cart_biryani(db_session, restaurant, seed_biryani_menu):
    """'chicken biriyani with chest piece and double masala' must set a kitchen note,
    not re-send the menu or add a duplicate line."""
    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110099"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    from app.menu.models import Dish

    dish = await db_session.scalar(
        select(Dish).where(
            Dish.restaurant_id == restaurant.id,
            Dish.name == "Chicken Biryani",
        )
    )
    await add_item(db_session, order=order, dish=dish, qty=1)
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="+971501110099",
        counterpart="customer",
        state={
            "draft_order_id": order.id,
            "dialogue_phase": "ordering",
            "dialogue_state": "collecting_items",
        },
    )
    db_session.add(conv)
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("chicken biriyani with chest piece and double masala", "wamid.with-mod"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    items = (
        await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    assert len(items) == 1
    notes = (items[0].notes or "").lower()
    assert "chest" in notes
    assert "masala" in notes


@pytest.mark.asyncio
async def test_try_kitchen_note_helper_combo_cart(db_session, restaurant):
    """Unit-level: _try_apply_kitchen_note_to_cart resolves combo lines by partial name."""
    from app.conversation.engine import _try_apply_kitchen_note_to_cart
    from app.menu.models import Dish, Menu

    menu = Menu(
        restaurant_id=restaurant.id, version=1, status="active", source_files=[],
    )
    db_session.add(menu)
    await db_session.flush()
    combo = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=10,
        name="Chicken Biriyani + Lemon Mint",
        price_aed=Decimal("140.00"),
        category="Combo",
        is_available=True,
        name_normalized="chicken biriyani lemon mint",
    )
    db_session.add(combo)
    await db_session.flush()

    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110066"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await add_item(db_session, order=order, dish=combo, qty=1)
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="+971501110066",
        counterpart="customer",
        state={"draft_order_id": order.id, "dialogue_phase": "ordering"},
    )
    db_session.add(conv)
    await db_session.commit()

    handled = await _try_apply_kitchen_note_to_cart(
        db_session,
        conv,
        _msg("chicken biriyani with chest piece and double masala", "wamid.unit"),
        restaurant.id,
    )
    await db_session.commit()
    assert handled is True
    items = (
        await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    assert "chest" in (items[0].notes or "").lower()


@pytest.mark.asyncio
async def test_combo_in_cart_gets_modifier_note_by_partial_name(db_session, restaurant):
    """When the cart holds a combo line, a partial dish reference still updates that line."""
    from app.menu.models import Dish, Menu

    menu = Menu(
        restaurant_id=restaurant.id,
        version=1,
        status="active",
        source_files=[],
    )
    db_session.add(menu)
    await db_session.flush()
    combo = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=10,
        name="Chicken Biriyani + Lemon Mint",
        price_aed=Decimal("140.00"),
        category="Combo",
        is_available=True,
        name_normalized="chicken biriyani lemon mint",
    )
    db_session.add(combo)
    await db_session.flush()

    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110088"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    await add_item(db_session, order=order, dish=combo, qty=1)
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="+971501110088",
        counterpart="customer",
        state={
            "draft_order_id": order.id,
            "dialogue_phase": "ordering",
            "dialogue_state": "collecting_items",
        },
    )
    db_session.add(conv)
    await db_session.commit()

    from app.conversation.service import get_or_create_conversation
    from app.outbox.models import OutboxMessage

    conv_loaded = await get_or_create_conversation(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971501110088",
        counterpart="customer",
    )
    assert conv_loaded.id == conv.id
    assert conv_loaded.state.get("draft_order_id") == order.id

    await handle_inbound(
        db_session,
        _msg(
            "chicken biriyani with chest piece and double masala",
            "wamid.combo-mod",
            phone="+971501110088",
        ),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    outbox = (
        await db_session.scalars(select(OutboxMessage).order_by(OutboxMessage.id))
    ).all()
    prefixes = [o.idempotency_key.split("-")[0] if o.idempotency_key else "" for o in outbox]

    items = (
        await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    assert len(items) == 1, f"outbox={prefixes} notes={items[0].notes!r}"
    assert items[0].dish_name == "Chicken Biriyani + Lemon Mint"
    notes = (items[0].notes or "").lower()
    assert "chest" in notes, f"outbox keys sample: {[o.idempotency_key for o in outbox]}"
    assert "masala" in notes


@pytest.mark.asyncio
async def test_ai_add_with_special_note_targets_in_cart_partial_name(
    db_session, restaurant, seed_biryani_menu
):
    """LLM add_item + special_note must attach to the in-cart biryani, not no_match."""
    cust = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110077"
    )
    order = await create_draft_order(db_session, restaurant_id=restaurant.id, customer_id=cust.id)
    from app.menu.models import Dish

    dish = await db_session.scalar(
        select(Dish).where(
            Dish.restaurant_id == restaurant.id,
            Dish.name == "Chicken Biryani",
        )
    )
    await add_item(db_session, order=order, dish=dish, qty=1)
    conv = Conversation(
        restaurant_id=restaurant.id,
        phone="+971501110077",
        counterpart="customer",
        state={
            "draft_order_id": order.id,
            "dialogue_phase": "ordering",
            "dialogue_state": "collecting_items",
        },
    )
    db_session.add(conv)
    await db_session.commit()

    result = ConversationAgentResult(
        message="Sure! I've added Chicken Biriyani + Lemon Mint to your order.",
        action="add_item",
        action_data={
            "dish_query": "chicken biriyani chest piece double masala",
            "qty": 1,
            "special_note": "chest piece and double masala",
        },
    )
    with patch(
        "app.llm.fake.FakeConversationAgent.respond",
        new=AsyncMock(return_value=result),
    ):
        await handle_inbound(
            db_session,
            _msg(
                "chicken biriyani chest piece and double masala",
                "wamid.ai-note",
                phone="+971501110077",
            ),
            restaurant_id=restaurant.id,
        )
    await db_session.commit()

    items = (
        await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    assert len(items) == 1
    notes = (items[0].notes or "").lower()
    assert "chest" in notes
    assert "masala" in notes