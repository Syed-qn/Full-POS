"""Tests for full-AI phase-aware conversation agent."""
import time
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Message
from app.whatsapp.port import InboundMessage, MessageType


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()


async def test_outbound_message_stored_after_send(db_session, restaurant):
    """_send_text must record an outbound row in the messages table."""
    await _seed_menu(db_session, restaurant.id)

    from app.conversation.service import get_or_create_conversation

    inbound = InboundMessage(
        wa_message_id="wamid.out-test-1",
        from_phone="+971501111222",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone=restaurant.phone,
        timestamp=1717660900,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971501111222", counterpart="customer"
    )
    messages = (
        await db_session.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        )
    ).all()

    directions = [m.direction for m in messages]
    assert "inbound" in directions
    assert "outbound" in directions


async def test_build_history_alternates_roles(db_session, restaurant):
    """_build_history returns user/assistant alternating list from DB."""
    from app.conversation.engine import _build_history
    from app.conversation.service import get_or_create_conversation, record_message

    phone = "+971502222333"
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    ts = int(time.time())

    await record_message(db_session, conversation_id=conv.id, direction="inbound",
                         wa_message_id="w1", msg_type="text",
                         payload={"text": "hi"}, ts=ts)
    await record_message(db_session, conversation_id=conv.id, direction="outbound",
                         wa_message_id=None, msg_type="text",
                         payload={"body": "Hello! Here is our menu."}, ts=ts)
    await record_message(db_session, conversation_id=conv.id, direction="inbound",
                         wa_message_id="w2", msg_type="text",
                         payload={"text": "I want biryani"}, ts=ts)
    await db_session.commit()

    history = await _build_history(db_session, conv, limit=10)

    assert len(history) == 3
    assert history[0] == {"role": "user", "content": "hi"}
    assert history[1] == {"role": "assistant", "content": "Hello! Here is our menu."}
    assert history[2] == {"role": "user", "content": "I want biryani"}


async def test_build_history_maps_location_to_text(db_session, restaurant):
    """Location inbound messages become summarized text in history."""
    from app.conversation.engine import _build_history
    from app.conversation.service import get_or_create_conversation, record_message

    phone = "+971503333444"
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    ts = int(time.time())
    await record_message(db_session, conversation_id=conv.id, direction="inbound",
                         wa_message_id="w1", msg_type="location",
                         payload={"latitude": 25.1, "longitude": 55.2}, ts=ts)
    await db_session.commit()

    history = await _build_history(db_session, conv, limit=10)
    assert history[0]["role"] == "user"
    assert "[customer shared location pin" in history[0]["content"]


def test_resolve_phase_maps_old_states():
    """_resolve_phase maps legacy dialogue_state values to new phases."""
    from app.conversation.engine import _resolve_phase
    from unittest.mock import MagicMock

    def make_conv(state):
        c = MagicMock()
        c.state = state
        return c

    assert _resolve_phase(make_conv({"dialogue_state": "greeting"})) == "ordering"
    assert _resolve_phase(make_conv({"dialogue_state": "menu_sent"})) == "ordering"
    assert _resolve_phase(make_conv({"dialogue_state": "collecting_items"})) == "ordering"
    assert _resolve_phase(make_conv({"dialogue_state": "address_capture"})) == "address_capture"
    assert _resolve_phase(make_conv({"dialogue_state": "address_text_pending"})) == "address_capture"
    assert _resolve_phase(make_conv({"dialogue_state": "receiver_details"})) == "address_capture"
    assert _resolve_phase(make_conv({"dialogue_state": "order_confirmation"})) == "awaiting_confirmation"
    assert _resolve_phase(make_conv({"dialogue_state": "order_placed"})) == "post_order"
    assert _resolve_phase(make_conv({"dialogue_phase": "ordering"})) == "ordering"
    assert _resolve_phase(make_conv({"dialogue_phase": "post_order"})) == "post_order"
    assert _resolve_phase(make_conv({})) == "ordering"


def test_phase_guard_blocks_wrong_phase_action():
    """confirm_order action in ordering phase → falls back to no_action."""
    from app.conversation.engine import _is_valid_action_for_phase

    assert not _is_valid_action_for_phase("confirm_order", "ordering")
    assert _is_valid_action_for_phase("confirm_order", "awaiting_confirmation")
    assert _is_valid_action_for_phase("no_action", "ordering")
    assert _is_valid_action_for_phase("cancel_order", "ordering")


async def test_add_item_action_updates_cart(db_session, restaurant):
    """AI add_item action: cart grows after item added."""
    from unittest.mock import AsyncMock, patch
    from app.llm.port import ConversationAgentResult

    await _seed_menu(db_session, restaurant.id)

    fake_result = ConversationAgentResult(
        message="Added biryani!",
        action="add_item",
        action_data={"dish_query": "biryani", "qty": 1, "special_note": ""},
    )

    inbound = InboundMessage(
        wa_message_id="wamid.add1",
        from_phone="+971501234999",
        type=MessageType.TEXT,
        payload={"text": "I want biryani"},
        restaurant_phone=restaurant.phone,
        timestamp=1717660901,
    )
    with patch("app.llm.fake.FakeConversationAgent.respond",
               new=AsyncMock(return_value=fake_result)):
        await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    from app.conversation.service import get_or_create_conversation
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id,
        phone="+971501234999", counterpart="customer"
    )
    from app.ordering.models import OrderItem
    draft_order_id = conv.state.get("draft_order_id")
    assert draft_order_id is not None
    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == draft_order_id)
    )).all()
    assert len(items) == 1
    assert "biryani" in items[0].dish_name.lower()


async def test_location_pin_outside_radius_rejected(db_session, restaurant):
    """Location pin outside restaurant's max_radius_km → polite rejection, no crash."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.conversation.service import get_or_create_conversation

    phone = "+971505555666"

    # Pre-set conversation to address_capture phase
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    conv.state = {**conv.state, "dialogue_phase": "address_capture",
                  "dialogue_state": "address_capture", "draft_order_id": None}
    await db_session.commit()

    inbound = InboundMessage(
        wa_message_id="wamid.loc1",
        from_phone=phone,
        type=MessageType.LOCATION,
        payload={"latitude": 51.5074, "longitude": -0.1278},  # London
        restaurant_phone=restaurant.phone,
        timestamp=1717660910,
    )

    with patch("app.geo.factory.get_geo_provider") as mock_geo:
        geo = MagicMock()
        geo.distance = AsyncMock(return_value=MagicMock(distance_km=5432.0))
        mock_geo.return_value = geo

        await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    # No crash; conversation phase reset to ordering
    await db_session.refresh(conv)
    phase = conv.state.get("dialogue_phase") or conv.state.get("dialogue_state")
    assert phase == "ordering"
