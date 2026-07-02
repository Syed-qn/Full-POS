"""Partial item cancellation — Options A/B/C from 2026-06-30 spec."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.conversation.engine import _proposed_from_order, handle_inbound
from app.conversation.models import Conversation
from app.llm import action_schema as A
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, phone: str = "+971501110200", wa_id: str = "wamid.pic") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


def _btn(btn_id: str, phone: str = "+971501110200") -> InboundMessage:
    return InboundMessage(
        wa_message_id="wamid.btn",
        from_phone=phone,
        type=MessageType.BUTTON_REPLY,
        payload={"id": btn_id, "title": "Yes"},
        restaurant_phone="+97141234567",
        timestamp=1717660801,
    )


async def _seed_four_item_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dishes = []
    for num, name, price in [
        (1, "Chicken Biryani", "22.00"),
        (2, "Mutton Biryani", "25.00"),
        (3, "Grill Mandi", "30.00"),
        (4, "Lemon Mint", "12.00"),
    ]:
        d = Dish(
            menu_id=menu.id,
            restaurant_id=restaurant_id,
            dish_number=num,
            name=name,
            price_aed=Decimal(price),
            category="Main",
            is_available=True,
            name_normalized=name.lower(),
        )
        db_session.add(d)
        dishes.append(d)
    await db_session.commit()
    return dishes


async def _confirmed_four_item_order(db_session, restaurant, phone: str = "+971501110200"):
    dishes = await _seed_four_item_menu(db_session, restaurant.id)
    customer = Customer(
        restaurant_id=restaurant.id,
        phone=phone,
        name="Test",
        usual_order_times={},
        tags={},
        total_orders=1,
        total_spend=Decimal("89.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id,
        latitude=25.21,
        longitude=55.27,
        room_apartment="1",
        building="Tower",
        receiver_name="Test",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number="R1-FOUR",
        status=OrderStatus.CONFIRMED,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("89.00"),
        total=Decimal("89.00"),
        address_id=addr.id,
        distance_km=1.0,
        sla_confirmed_at=now,
        sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()
    for d in dishes:
        db_session.add(
            OrderItem(
                order_id=order.id,
                dish_id=d.id,
                dish_number=d.dish_number,
                dish_name=d.name,
                price_aed=d.price_aed,
                qty=1,
            )
        )
    await db_session.commit()
    return order, dishes


async def _conv(db_session, phone: str) -> Conversation:
    return (
        await db_session.execute(select(Conversation).where(Conversation.phone == phone))
    ).scalar_one()


def test_option_c_schema_has_order_line_actions():
    """Option C: post-confirm line edits are first-class canonical actions."""
    assert "order_line_remove" in A.ACTION_SPECS
    assert "order_line_set_qty" in A.ACTION_SPECS
    assert "order_modify_confirm" in A.ACTION_SPECS
    assert "post_order" in A.ACTION_SPECS["order_line_remove"].phases
    assert A.CANON_TO_LEGACY["order_line_remove"] == "remove_item"
    assert A.CANON_TO_LEGACY["order_line_set_qty"] == "update_qty"
    assert A.CANON_TO_LEGACY["order_modify_confirm"] == "confirm_line_edit"
    assert "remove_item" in A.LEGACY_PHASE_ACTIONS["post_order"]
    assert "update_qty" in A.LEGACY_PHASE_ACTIONS["post_order"]


@pytest.mark.asyncio
async def test_t5_confirmed_modify_remove_one_of_four(db_session, restaurant):
    """T5: 4 items → modify → remove 1 → confirm → 3 items remain."""
    phone = "+971501110200"
    order, dishes = await _confirmed_four_item_order(db_session, restaurant, phone)
    lemon = next(d for d in dishes if "lemon" in d.name.lower())

    await handle_inbound(db_session, _msg("hi", phone=phone), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session, phone)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "modify_items",
        "modify_order_id": order.id,
        "modify_proposed": await _proposed_from_order(db_session, order.id),
        "modify_proposed_initialized": True,
        "last_placed_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(
        db_session, _msg("remove lemon mint", phone=phone, wa_id="wamid.rm"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()
    conv = await _conv(db_session, phone)
    proposed = conv.state.get("modify_proposed", [])
    assert len(proposed) == 3
    assert not any(p.get("dish_id") == lemon.id for p in proposed)

    await handle_inbound(
        db_session, _msg("done", phone=phone, wa_id="wamid.done"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()
    conv = await _conv(db_session, phone)
    assert conv.state.get("dialogue_state") == "modify_confirm"

    await handle_inbound(
        db_session, _btn("confirm_modify", phone=phone),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()
    await db_session.refresh(order)
    items = (
        await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    assert len(items) == 3
    assert not any(i.dish_id == lemon.id for i in items)


@pytest.mark.asyncio
async def test_t6_modify_remove_all_offers_full_cancel(db_session, restaurant):
    """T6: removing every line offers full cancel, not empty modify."""
    phone = "+971501110201"
    order, dishes = await _confirmed_four_item_order(db_session, restaurant, phone)

    await handle_inbound(db_session, _msg("hi", phone=phone), restaurant_id=restaurant.id)
    await db_session.commit()
    from app.conversation.engine import _proposed_from_order

    conv = await _conv(db_session, phone)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "modify_items",
        "modify_order_id": order.id,
        "modify_proposed": await _proposed_from_order(db_session, order.id),
        "modify_proposed_initialized": True,
        "last_placed_order_id": order.id,
    }
    await db_session.commit()

    for d in dishes:
        await handle_inbound(
            db_session,
            _msg(f"remove {d.name.lower()}", phone=phone, wa_id=f"wamid.rm{d.dish_number}"),
            restaurant_id=restaurant.id,
        )
        await db_session.commit()

    await handle_inbound(
        db_session, _msg("done", phone=phone, wa_id="wamid.done"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    body = rows[-1].payload.get("body", "").lower()
    assert "cancel" in body and ("whole" in body or "entire" in body or "all" in body)


@pytest.mark.asyncio
async def test_t3_confirmation_inline_remove(db_session, restaurant):
    """T3: at order summary (draft), remove one dish inline without modify FSM."""
    phone = "+971501110203"
    order, dishes = await _confirmed_four_item_order(db_session, restaurant, phone)
    lemon = next(d for d in dishes if "lemon" in d.name.lower())
    order.status = "draft"
    await db_session.commit()

    await handle_inbound(db_session, _msg("hi", phone=phone), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session, phone)
    conv.state = {
        **conv.state,
        "dialogue_phase": "awaiting_confirmation",
        "dialogue_state": "order_confirmation",
        "pending_order_id": order.id,
        "draft_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(
        db_session, _msg("remove lemon mint", phone=phone),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    items = (
        await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    assert len(items) == 3
    assert not any(i.dish_id == lemon.id for i in items)
    assert conv.state.get("dialogue_state") != "modify_items"


@pytest.mark.asyncio
async def test_option_b_inline_post_order_remove_shows_confirm(db_session, restaurant):
    """Option B: post_order remove goes straight to confirm summary."""
    phone = "+971501110202"
    order, dishes = await _confirmed_four_item_order(db_session, restaurant, phone)

    await handle_inbound(db_session, _msg("hi", phone=phone), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session, phone)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "order_placed",
        "last_placed_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(
        db_session, _msg("remove lemon mint", phone=phone),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    conv = await _conv(db_session, phone)
    assert conv.state.get("dialogue_state") == "modify_confirm"
    proposed = conv.state.get("modify_proposed", [])
    assert len(proposed) == 3