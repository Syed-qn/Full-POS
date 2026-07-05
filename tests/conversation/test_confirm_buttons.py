"""Order-confirmed message must carry quick-action buttons (Track/Modify/Cancel).

Prod pattern: after "Order confirmed! 🎉" the customer had no tap target and
typed free text ("Cancel order", "where is my order") — the same dead-end that
caused the cancel/marketing-opt-out collision. Same rule as cart updates: every
actionable state carries buttons.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

_PHONE = "+971501113003"
_REST_PHONE = "+97141234567"


def _msg(text: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=_PHONE, type=MessageType.TEXT,
        payload={"text": text}, restaurant_phone=_REST_PHONE, timestamp=1717660800,
    )


def _btn(btn_id: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=_PHONE, type=MessageType.BUTTON_REPLY,
        payload={"id": btn_id, "title": "x"}, restaurant_phone=_REST_PHONE,
        timestamp=1717660802,
    )


async def _seed_confirmable_order(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.flush()

    customer = Customer(
        restaurant_id=restaurant.id, phone=_PHONE, name="Btn",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="101", building="Tower A", receiver_name="Btn", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-9001", status="pending_confirmation",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.5,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110,
        dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1,
    ))
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", "wamid.cb0"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = (await db_session.execute(
        select(Conversation).where(Conversation.phone == _PHONE)
    )).scalar_one()
    conv.state = {
        **conv.state, "dialogue_phase": "awaiting_confirmation",
        "dialogue_state": "order_confirmation", "pending_order_id": order.id,
    }
    await db_session.commit()
    return order


async def _confirm(db_session, restaurant):
    order = await _seed_confirmable_order(db_session, restaurant)
    await handle_inbound(db_session, _btn("confirm_order", "wamid.cb1"), restaurant_id=restaurant.id)
    await db_session.commit()
    return order


async def test_confirmation_message_has_track_modify_cancel_buttons(db_session, restaurant):
    await _confirm(db_session, restaurant)
    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    confirm_msgs = [r for r in rows if "confirmed" in (r.payload.get("body") or "").lower()]
    assert confirm_msgs, "confirmation message must exist"
    buttons = confirm_msgs[-1].payload.get("buttons") or []
    ids = [b["id"] for b in buttons]
    assert "track_order" in ids
    assert "modify_order" in ids
    assert "cancel_order" in ids
    assert all(len(b["title"]) <= 20 for b in buttons)


async def test_track_order_button_returns_status(db_session, restaurant):
    await _confirm(db_session, restaurant)
    await handle_inbound(db_session, _btn("track_order", "wamid.cb2"), restaurant_id=restaurant.id)
    await db_session.commit()
    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    body = rows[-1].payload.get("body", "").lower()
    assert "r1-9001" in body or "order" in body  # status reply, not an error
    assert "wrong" not in body and "having a moment" not in body


async def test_modify_order_button_enters_modify_flow(db_session, restaurant):
    await _confirm(db_session, restaurant)
    await handle_inbound(db_session, _btn("modify_order", "wamid.cb3"), restaurant_id=restaurant.id)
    await db_session.commit()
    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    body = rows[-1].payload.get("body", "").lower()
    # Modify handler replies asking what to change (or shows the order) — never an error.
    assert "wrong" not in body and "having a moment" not in body
    assert body.strip(), "modify tap must produce a reply"
