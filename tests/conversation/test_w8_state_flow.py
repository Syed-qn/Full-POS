"""W8 — State/flow correctness & ops hardening.

Task 1: confirm_order / cancel_order button taps must route deterministically
to _execute_confirm_order / _execute_cancel_order with NO LLM round-trip
(finding F23). We assert this by monkeypatching get_conversation_agent to a
stub that raises if ever invoked — if the button flow still succeeds, the
LLM was never called.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str = "wamid.o1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110002",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


def _btn(btn_id: str, wa_id: str = "wamid.btn1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110002",
        type=MessageType.BUTTON_REPLY,
        payload={"id": btn_id, "title": "Yes"},
        restaurant_phone="+97141234567",
        timestamp=1717660802,
    )


def _loc_msg(lat: float, lon: float, wa_id: str = "wamid.loc1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110002",
        type=MessageType.LOCATION,
        payload={"latitude": lat, "longitude": lon},
        restaurant_phone="+97141234567",
        timestamp=1717660801,
    )


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


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == "+971501110002")
    )).scalar_one()


class _ExplodingAgent:
    """Any call proves the button path took an LLM round-trip — which it must not."""

    async def respond(self, **kwargs):
        raise AssertionError("LLM agent.respond() must never be called for confirm/cancel button taps")


async def test_confirm_button_no_llm_round_trip(db_session, restaurant, monkeypatch):
    await _seed_menu(db_session, restaurant.id)
    monkeypatch.setattr("app.llm.factory.get_conversation_agent", lambda: _ExplodingAgent())

    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
    from app.menu.models import Dish

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110002", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="101", building="Tower A",
        receiver_name="Ali", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-0001", status="pending_confirmation",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.5,
    )
    db_session.add(order)
    await db_session.flush()
    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.dish_number == 110)
    )).first()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110, dish_name="Chicken Biryani",
        price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.flush()
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.greet1"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_phase": "awaiting_confirmation",
        "dialogue_state": "order_confirmation",
        "pending_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(db_session, _btn("confirm_order", "wamid.conf1"), restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "confirmed"

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"]
    assert "R1-0001" in last


async def test_cancel_button_no_llm_round_trip(db_session, restaurant, monkeypatch):
    await _seed_menu(db_session, restaurant.id)
    monkeypatch.setattr("app.llm.factory.get_conversation_agent", lambda: _ExplodingAgent())

    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
    from app.menu.models import Dish

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110002", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="101", building="Tower A",
        receiver_name="Ali", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-0002", status="pending_confirmation",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.5,
    )
    db_session.add(order)
    await db_session.flush()
    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.dish_number == 110)
    )).first()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110, dish_name="Chicken Biryani",
        price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.flush()
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.greet2"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_phase": "awaiting_confirmation",
        "dialogue_state": "order_confirmation",
        "pending_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(db_session, _btn("cancel_order", "wamid.can1"), restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "cancelled"


async def test_out_of_range_pin_retains_cart(db_session, restaurant):
    """R-008: an out-of-range pin clears only pin/fee state, never the cart."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.greet3"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("chicken biryani", "wamid.item3"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    draft_id_before = conv.state.get("draft_order_id")
    assert draft_id_before is not None

    conv.state = {**conv.state, "dialogue_phase": "address_capture",
                  "dialogue_state": "address_capture"}
    await db_session.commit()

    # Abu Dhabi pin — far from Dubai restaurant (25.2048, 55.2708)
    await handle_inbound(db_session, _loc_msg(24.4539, 54.3773, "wamid.far3"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    assert conv.state.get("draft_order_id") == draft_id_before

    from app.ordering.models import OrderItem
    items = (await db_session.execute(
        select(OrderItem).where(OrderItem.order_id == draft_id_before)
    )).scalars().all()
    assert len(items) == 1


async def test_resume_continue_then_done_advances_to_address_not_empty(db_session, restaurant):
    """TX-02: resume → continue → 'that's all' must advance to checkout, never
    read the cart as empty (draft_order_id must be restored into conv.state
    before the next turn is processed)."""
    await _seed_menu(db_session, restaurant.id)

    await handle_inbound(db_session, _msg("hi", "wamid.greet4"), restaurant_id=restaurant.id)
    await db_session.commit()
    await handle_inbound(db_session, _msg("chicken biryani", "wamid.item4"), restaurant_id=restaurant.id)
    await db_session.commit()

    conv = await _conv(db_session)
    draft_id = conv.state.get("draft_order_id")
    assert draft_id is not None

    # Simulate a fresh session (e.g. a redeploy or resumed conversation) via a
    # pure greeting — the draft still has items so this offers resume, not a wipe.
    await handle_inbound(db_session, _msg("hi", "wamid.greet5"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    assert conv.state.get("dialogue_state") == "resume_offer"
    assert conv.state.get("draft_order_id") == draft_id

    await handle_inbound(db_session, _btn("resume_cart", "wamid.resume4"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    # draft_order_id must be restored/pinned into state as part of resuming —
    # not merely left untouched by accident.
    assert conv.state.get("draft_order_id") == draft_id

    await handle_inbound(db_session, _msg("that's all", "wamid.done4"), restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"].lower()
    assert "empty" not in last
    assert "location" in last or "address" in last or "apartment" in last or "pin" in last or "📍" in rows[-1].payload["body"]


async def test_greeting_after_confirm_does_not_advance_delivery_state(db_session, restaurant):
    """TX-14/F114: a greeting/status message after confirmation must never mark
    the order delivered (or transition it at all) — only real dispatch/FSM
    events may do that. A greeting only reports the current status."""
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
    from app.menu.models import Dish

    await _seed_menu(db_session, restaurant.id)

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110002", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="101", building="Tower A",
        receiver_name="Ali", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-0009", status="confirmed",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.5,
    )
    db_session.add(order)
    await db_session.flush()
    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.dish_number == 110)
    )).first()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110, dish_name="Chicken Biryani",
        price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.flush()
    await db_session.commit()

    await handle_inbound(db_session, _msg("Hlo", "wamid.hlo1"), restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "confirmed", (
        "a greeting must never advance/close order status — only dispatch/FSM events may"
    )


async def test_conversation_lock_serializes_concurrent_turns(db_session, restaurant):
    """TX-22/TX-46/F94/F115: two 'simultaneous' inbound messages for the same
    conversation must be processed one at a time (never interleaved) so cart
    mutations from one turn can't race the other's read-modify-write of
    conv.state. We can't fork a second real connection inside this savepoint-
    isolated test session, so we assert the lock helper itself is callable
    twice in a row on the same session without deadlocking/erroring (Postgres
    advisory locks are re-entrant per session) and that handle_inbound still
    completes normally when the lock is engaged."""
    from app.conversation.engine import _acquire_conversation_lock

    await _seed_menu(db_session, restaurant.id)

    await _acquire_conversation_lock(db_session, restaurant.id, "+971501110099")
    await _acquire_conversation_lock(db_session, restaurant.id, "+971501110099")

    msg = InboundMessage(
        wa_message_id="wamid.lock1",
        from_phone="+971501110099",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone="+97141234567",
        timestamp=1717660900,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert len(rows) >= 1
