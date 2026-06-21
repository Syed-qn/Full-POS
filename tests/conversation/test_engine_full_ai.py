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


async def test_update_qty_and_remove_item_actions(db_session, restaurant):
    """AI cart edits: add → 'make it 4' (update_qty) → add a 2nd dish →
    'remove' the first. Cart must reflect each edit exactly."""
    from unittest.mock import AsyncMock, patch

    from app.llm.port import ConversationAgentResult
    from app.menu.models import Dish, Menu
    from app.ordering.models import OrderItem

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=120,
        name="Mutton Biryani", price_aed=Decimal("30.00"),
        category="Rice", is_available=True, name_normalized="mutton biryani",
    ))
    await db_session.commit()

    phone = "+971501230111"

    def _inb(wamid: str, text: str) -> InboundMessage:
        return InboundMessage(
            wa_message_id=wamid, from_phone=phone, type=MessageType.TEXT,
            payload={"text": text}, restaurant_phone=restaurant.phone,
            timestamp=1717660000,
        )

    results = [
        ConversationAgentResult(message="Added!", action="add_item",
                                action_data={"dish_query": "chicken biryani", "qty": 1, "special_note": ""}),
        ConversationAgentResult(message="ok", action="update_qty",
                                action_data={"dish_query": "chicken biryani", "qty": 4}),
        ConversationAgentResult(message="Added!", action="add_item",
                                action_data={"dish_query": "mutton biryani", "qty": 1, "special_note": ""}),
        ConversationAgentResult(message="ok", action="remove_item",
                                action_data={"dish_query": "chicken biryani"}),
    ]

    async def _drive(wamid, text):
        with patch("app.llm.fake.FakeConversationAgent.respond",
                   new=AsyncMock(return_value=results.pop(0))):
            await handle_inbound(db_session, _inb(wamid, text), restaurant_id=restaurant.id)
        await db_session.commit()

    from app.conversation.service import get_or_create_conversation

    async def _cart():
        conv = await get_or_create_conversation(
            db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
        )
        draft = conv.state.get("draft_order_id")
        items = (await db_session.scalars(
            select(OrderItem).where(OrderItem.order_id == draft)
        )).all()
        return {i.dish_name.lower(): i.qty for i in items}

    await _drive("wamid.e1", "chicken biryani")
    assert (await _cart()) == {"chicken biryani": 1}

    await _drive("wamid.e2", "make it 4")
    assert (await _cart()) == {"chicken biryani": 4}      # update_qty = new TOTAL

    await _drive("wamid.e3", "mutton biryani")
    assert (await _cart()) == {"chicken biryani": 4, "mutton biryani": 1}

    await _drive("wamid.e4", "remove chicken biryani")
    assert (await _cart()) == {"mutton biryani": 1}        # only the named dish removed


async def test_location_pin_outside_radius_rejected(db_session, restaurant):
    """Location pin outside restaurant's max_radius_km → polite rejection, no crash."""
    from unittest.mock import MagicMock, patch
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
        # Engine uses the GeoPort sync method distance_km(lat1,lng1,lat2,lng2).
        geo.distance_km = MagicMock(return_value=5432.0)
        mock_geo.return_value = geo

        await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    # No crash; conversation phase reset to ordering
    await db_session.refresh(conv)
    phase = conv.state.get("dialogue_phase") or conv.state.get("dialogue_state")
    assert phase == "ordering"


async def test_address_step_recovers_stale_draft_pointer(db_session, restaurant):
    """Cart must NOT be lost if draft_order_id goes missing from conv.state.

    Live bug: customer adds a dish, shares location, then on the apt/building/
    receiver step the bot replied "Your cart is empty" — the draft_order_id
    pointer had been lost while the draft order + items still existed. The
    address handler must recover the customer's latest non-empty draft instead
    of declaring the cart empty.
    """
    from unittest.mock import AsyncMock, patch

    from app.conversation.service import get_or_create_conversation
    from app.llm.port import ConversationAgentResult
    from app.menu.models import Dish
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    await _seed_menu(db_session, restaurant.id)
    phone = "+971507000111"

    # A real draft order with one item exists for this customer...
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone=phone
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    dish = await db_session.scalar(select(Dish))
    await add_item(db_session, order=order, dish=dish, qty=1, notes=None)

    # ...but the conversation has reached address_capture WITHOUT a draft pointer
    # (simulates the lost-pointer failure), with a location pin already shared.
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    conv.state = {
        **conv.state,
        "dialogue_phase": "address_capture",
        "dialogue_state": "address_capture",
        "pin_lat": 25.1877,
        "pin_lon": 55.2633,
        "distance_km": 1.0,
        # NOTE: no draft_order_id on purpose
    }
    await db_session.commit()

    fake_result = ConversationAgentResult(
        message="Saving your address",
        action="save_address_text",
        action_data={"apt_room": "123", "building": "Tower 5", "receiver_name": "asfer"},
    )
    inbound = InboundMessage(
        wa_message_id="wamid.addr-recover",
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": "123, Tower 5, asfer"},
        restaurant_phone=restaurant.phone,
        timestamp=1717661000,
    )
    with patch("app.llm.fake.FakeConversationAgent.respond",
               new=AsyncMock(return_value=fake_result)):
        await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    # Recovered: pointer re-linked, address attached, advanced to confirmation.
    await db_session.refresh(conv)
    assert conv.state.get("draft_order_id") == order.id
    assert conv.state.get("dialogue_phase") == "awaiting_confirmation"
    await db_session.refresh(order)
    assert order.address_id is not None

    # The customer must NOT have been told the cart is empty.
    msgs = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id,
                              Message.direction == "outbound")
    )).all()
    assert not any("cart is empty" in (m.payload or {}).get("body", "") for m in msgs)


async def test_greeting_starts_fresh_and_drops_abandoned_cart(db_session, restaurant):
    """A pure greeting ("As salam walekum") means start fresh.

    Live bug: a customer who added a dish, never bought it, then greeted again
    was shown the OLD cart ("You've got 1x ... in your cart") instead of a fresh
    start. A pure-greeting message must clear the stale draft pointer so the
    abandoned cart cannot carry into the new order — in ANY state.
    """
    from unittest.mock import AsyncMock, patch

    from app.conversation.engine import _build_cart_summary
    from app.conversation.service import get_or_create_conversation
    from app.llm.port import ConversationAgentResult

    await _seed_menu(db_session, restaurant.id)
    phone = "+971507111222"

    # Customer adds a dish (creates a draft) then walks away.
    add_result = ConversationAgentResult(
        message="Chicken Biryani added!",
        action="add_item",
        action_data={"dish_query": "biryani", "qty": 1, "special_note": ""},
    )
    add_inbound = InboundMessage(
        wa_message_id="wamid.greet-add", from_phone=phone, type=MessageType.TEXT,
        payload={"text": "one biryani"}, restaurant_phone=restaurant.phone,
        timestamp=1717662000,
    )
    with patch("app.llm.fake.FakeConversationAgent.respond",
               new=AsyncMock(return_value=add_result)):
        await handle_inbound(db_session, add_inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    assert conv.state.get("draft_order_id") is not None  # cart exists

    # Customer greets again instead of buying — must start fresh.
    greet_inbound = InboundMessage(
        wa_message_id="wamid.greet-hi", from_phone=phone, type=MessageType.TEXT,
        payload={"text": "As salam walekum"}, restaurant_phone=restaurant.phone,
        timestamp=1717662050,
    )
    await handle_inbound(db_session, greet_inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(conv)
    assert conv.state.get("draft_order_id") is None        # abandoned cart dropped
    assert await _build_cart_summary(db_session, conv) == ""  # fresh, empty cart


async def test_new_order_clears_previous_address_state(db_session, restaurant):
    """Starting a new order must clear address state from the previous order.

    Returning-customer bug: after the first order set address_offer_made=True
    (and pinned a location), the SECOND order skipped the "Use saved address"
    offer and reused stale pin/fee. A fresh draft must reset that state so every
    order re-offers the saved address and recomputes distance/fee.
    """
    from unittest.mock import AsyncMock, patch

    from app.conversation.service import get_or_create_conversation
    from app.llm.port import ConversationAgentResult

    await _seed_menu(db_session, restaurant.id)
    phone = "+971507333444"

    # Simulate state left over from a previous order (offer made, pin set), no draft.
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    conv.state = {
        **conv.state,
        "dialogue_phase": "ordering", "dialogue_state": "collecting_items",
        "address_offer_made": True, "saved_address_id": 42,
        "pin_lat": 25.1, "pin_lon": 55.2, "distance_km": 3.0, "delivery_fee": "5",
        "draft_order_id": None,
    }
    await db_session.commit()

    add_result = ConversationAgentResult(
        message="Added!", action="add_item",
        action_data={"dish_query": "biryani", "qty": 1, "special_note": ""},
    )
    inbound = InboundMessage(
        wa_message_id="wamid.reorder", from_phone=phone, type=MessageType.TEXT,
        payload={"text": "one biryani"}, restaurant_phone=restaurant.phone,
        timestamp=1717663000,
    )
    with patch("app.llm.fake.FakeConversationAgent.respond",
               new=AsyncMock(return_value=add_result)):
        await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(conv)
    assert conv.state.get("draft_order_id") is not None       # new order created
    assert conv.state.get("address_offer_made") is None        # offer flag reset
    assert conv.state.get("pin_lat") is None                   # stale pin cleared
    assert conv.state.get("distance_km") is None               # stale distance cleared


def test_is_tracking_query_detection():
    """'live location' / 'where is my order' style messages are tracking queries."""
    from app.conversation.engine import _is_tracking_query

    assert _is_tracking_query("Can I see live location")
    assert _is_tracking_query("where is my order")
    assert _is_tracking_query("track my order")
    assert _is_tracking_query("Where is my rider?")
    assert not _is_tracking_query("one chicken biryani")
    assert not _is_tracking_query("hi")
    assert not _is_tracking_query("")


def test_is_restaurant_location_request_detection():
    """'where are you / I'll come direct' messages ask for the restaurant pin."""
    from app.conversation.engine import _is_restaurant_location_request

    assert _is_restaurant_location_request("Restaurant location")
    assert _is_restaurant_location_request("what is your exact location i will come direct")
    assert _is_restaurant_location_request("where are you located")
    assert _is_restaurant_location_request("send me your location pin")
    assert _is_restaurant_location_request("I'll come and collect myself")
    assert not _is_restaurant_location_request("where is my order")
    assert not _is_restaurant_location_request("one chicken biryani")
    assert not _is_restaurant_location_request("")


async def test_restaurant_location_request_sends_pin_no_draft(db_session, restaurant):
    """Asking for the restaurant location sends a native pin and must NOT create a
    draft order or push the customer into address capture."""
    from app.outbox.models import OutboxMessage

    await _seed_menu(db_session, restaurant.id)
    phone = "+971509998888"
    inbound = InboundMessage(
        wa_message_id="wamid.restloc", from_phone=phone, type=MessageType.TEXT,
        payload={"text": "what is your exact location i will come direct"},
        restaurant_phone=restaurant.phone, timestamp=1717664000,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    msgs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == phone)
    )).all()
    loc = [m for m in msgs if m.payload.get("type") == "location"]
    assert loc, "should send a native location pin"
    assert loc[0].payload["latitude"] == restaurant.lat
    assert loc[0].payload["longitude"] == restaurant.lng

    from app.conversation.service import get_or_create_conversation
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    assert conv.state.get("draft_order_id") is None
    assert conv.state.get("dialogue_phase") != "address_capture"


async def _status_reply_body(db_session, restaurant, phone, wamid):
    """Helper: send 'where is my order' and return the latest outbound body."""
    inbound = InboundMessage(
        wa_message_id=wamid, from_phone=phone, type=MessageType.TEXT,
        payload={"text": "where is my order"}, restaurant_phone=restaurant.phone,
        timestamp=1717664000,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()
    from app.conversation.service import get_or_create_conversation
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    rows = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id,
                              Message.direction == "outbound").order_by(Message.id.desc())
    )).all()
    return rows[0].payload.get("body", "")


async def test_status_query_ignores_stale_draft(db_session, restaurant):
    """A leftover DRAFT cart must never be reported as 'being assembled' — it's an
    incomplete cart, not a placed order. The latest PLACED order is reported."""
    from app.ordering.models import Customer, Order

    await _seed_menu(db_session, restaurant.id)
    phone = "+971507770001"
    customer = Customer(
        restaurant_id=restaurant.id, phone=phone, name="A",
        usual_order_times={}, tags={}, total_orders=1, total_spend=Decimal("10.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    for num, st in (("R1-D1", "delivered"), ("R1-D2", "draft")):
        db_session.add(Order(
            restaurant_id=restaurant.id, customer_id=customer.id, order_number=num,
            status=st, priority="normal", weather_delay_disclosed=False,
            delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("10.00"),
            total=Decimal("10.00"),
        ))
    await db_session.commit()

    body = await _status_reply_body(db_session, restaurant, phone, "wamid.stq")
    assert "being assembled" not in body.lower()  # draft never shown


async def test_status_query_reports_latest_not_older_open_order(db_session, restaurant):
    """The bug: an OLDER still-confirmed order shadowed a NEWER delivered order, so
    'where is my order' said 'ready in 40 min' right after a delivery. The latest
    order (delivered) must be reported instead."""
    from datetime import datetime, timedelta

    from app.ordering.models import Customer, Order

    await _seed_menu(db_session, restaurant.id)
    phone = "+971507770002"
    customer = Customer(
        restaurant_id=restaurant.id, phone=phone, name="Asfer",
        usual_order_times={}, tags={}, total_orders=2, total_spend=Decimal("20.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    now = datetime.utcnow()
    # Older order stuck at 'confirmed', then a NEWER order that got delivered.
    db_session.add(Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="R1-0008",
        status="confirmed", priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("10.00"), total=Decimal("10.00"),
        created_at=now - timedelta(minutes=2),
    ))
    db_session.add(Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="R1-0009",
        status="delivered", priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("10.00"), total=Decimal("10.00"),
        created_at=now,
    ))
    await db_session.commit()

    body = await _status_reply_body(db_session, restaurant, phone, "wamid.stq2")
    assert "R1-0009" in body and "delivered" in body.lower()
    assert "R1-0008" not in body
    assert "40 minutes" not in body


async def test_tracking_query_replies_with_live_link(db_session, restaurant):
    """A 'see live location' message on an en-route order re-sends the track link."""
    from datetime import datetime, timedelta, timezone

    from app.dispatch.models import OrderTrackingSession
    from app.identity.models import Rider
    from app.ordering.models import Customer, Order

    await _seed_menu(db_session, restaurant.id)
    phone = "+971507555666"

    customer = Customer(
        restaurant_id=restaurant.id, phone=phone, name="Asfer",
        usual_order_times={}, tags={}, total_orders=1, total_spend=Decimal("10.00"),
    )
    db_session.add(customer)
    rider = Rider(restaurant_id=restaurant.id, name="Live Rider", phone="+971500000001",
                  status="on_delivery")
    db_session.add(rider)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, rider_id=rider.id,
        order_number="R1-0007", status="picked_up", priority="normal",
        weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"), total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(OrderTrackingSession(
        order_id=order.id, rider_id=rider.id, restaurant_id=restaurant.id,
        tracking_token="tok_TESTTRACK123", rider_token="rtok_TEST123",
        status="active", started_at=now, expires_at=now + timedelta(hours=2),
    ))
    await db_session.commit()

    inbound = InboundMessage(
        wa_message_id="wamid.track-q", from_phone=phone, type=MessageType.TEXT,
        payload={"text": "Can I see live location"}, restaurant_phone=restaurant.phone,
        timestamp=1717664000,
    )
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    from app.conversation.service import get_or_create_conversation
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone=phone, counterpart="customer"
    )
    rows = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id,
                              Message.direction == "outbound").order_by(Message.id.desc())
    )).all()
    # The live tracker is now handed back as a tappable "Track my order" CTA URL
    # button (mirroring the rider's button), not a raw link in the body.
    payload = rows[0].payload
    assert payload.get("type") == "cta_url"
    assert "track my order" in payload.get("button_label", "").lower()
    assert "/track/tok_TESTTRACK123" in payload.get("url", "")
