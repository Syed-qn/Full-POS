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
