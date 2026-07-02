"""Post-order modify: cancel/remove a dish, keep-only, correct order resolution."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.conversation.engine import (
    _parse_keep_only,
    _parse_remove_item,
    handle_inbound,
)
from app.conversation.models import Conversation
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, phone: str = "+971501110099", wa_id: str = "wamid.modpo") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def _seed_combo_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    combo = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant_id,
        dish_number=10,
        name="Chicken Biriyani + Lemon Mint",
        price_aed=Decimal("1400.00"),
        category="Combo",
        is_available=True,
        name_normalized="chicken biriyani lemon mint",
    )
    lemon = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant_id,
        dish_number=11,
        name="Lemon Mint",
        price_aed=Decimal("12.00"),
        category="Drinks",
        is_available=True,
        name_normalized="lemon mint",
    )
    db_session.add_all([combo, lemon])
    await db_session.commit()
    return combo, lemon


async def _placed_order_with_combo(
    db_session, restaurant, *, order_number: str, phone: str, combo=None, customer=None,
):
    if combo is None:
        combo, _ = await _seed_combo_menu(db_session, restaurant.id)

    if customer is None:
        customer = Customer(
            restaurant_id=restaurant.id,
            phone=phone,
            name="Syed",
            usual_order_times={},
            tags={},
            total_orders=0,
            total_spend=Decimal("0.00"),
        )
        db_session.add(customer)
        await db_session.flush()
        addr = CustomerAddress(
            customer_id=customer.id,
            latitude=25.21,
            longitude=55.27,
            room_apartment="816",
            building="1-14",
            receiver_name="Syed",
            confirmed=True,
        )
        db_session.add(addr)
        await db_session.flush()
    else:
        addr = (
            await db_session.execute(
                select(CustomerAddress).where(CustomerAddress.customer_id == customer.id).limit(1)
            )
        ).scalar_one()

    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number=order_number,
        status=OrderStatus.CONFIRMED,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("1400.00"),
        total=Decimal("1400.00"),
        address_id=addr.id,
        distance_km=1.0,
        sla_confirmed_at=now,
        sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=combo.id,
            dish_number=combo.dish_number,
            dish_name=combo.name,
            price_aed=combo.price_aed,
            qty=1,
            notes="chest peice and double masala",
        )
    )
    await db_session.commit()
    return order, customer, combo


async def _conv(db_session, phone: str) -> Conversation:
    return (
        await db_session.execute(
            select(Conversation).where(Conversation.phone == phone)
        )
    ).scalar_one()


def test_parse_cancel_dish_as_remove():
    """'cancel chicken biriyani' is remove-item, not whole-order cancel."""
    parsed = _parse_remove_item("cancel chicken biriyani")
    assert parsed is not None
    assert parsed[1] == "chicken biriyani"


def test_parse_keep_only_lemon_mint():
    assert _parse_keep_only("Only lemon mint") == "lemon mint"


@pytest.mark.asyncio
async def test_cancel_dish_uses_last_placed_order_not_stale_draft(db_session, restaurant):
    """After confirming R1-0118, 'cancel chicken biriyani' must target that order,
    not an older draft R1-0100 still in conv.state."""
    phone = "+971501110099"
    combo, _ = await _seed_combo_menu(db_session, restaurant.id)
    old_order, customer, _ = await _placed_order_with_combo(
        db_session, restaurant, order_number="R1-0100", phone=phone, combo=combo,
    )
    new_order, _, _ = await _placed_order_with_combo(
        db_session, restaurant, order_number="R1-0118", phone=phone, combo=combo,
        customer=customer,
    )

    await handle_inbound(db_session, _msg("hi", phone=phone, wa_id="wamid.hi"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session, phone)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "order_placed",
        "pending_order_id": old_order.id,
        "last_placed_order_id": new_order.id,
    }
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("cancel chicken biriyani", phone=phone, wa_id="wamid.cancel"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    body = rows[-1].payload.get("body", "")
    assert "R1-0118" in body or conv.state.get("modify_order_id") == new_order.id
    assert conv.state.get("modify_order_id") != old_order.id
    assert conv.state.get("dialogue_state") == "modify_confirm"


@pytest.mark.asyncio
async def test_only_lemon_mint_in_modify_sets_proposed_not_no_changes(db_session, restaurant):
    """Regression: 'Only lemon mint' in modify_items must not reply 'No changes proposed'."""
    phone = "+971501110088"
    order, _, combo = await _placed_order_with_combo(
        db_session, restaurant, order_number="R1-0118", phone=phone
    )

    await handle_inbound(db_session, _msg("hi", phone=phone), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session, phone)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "modify_items",
        "modify_order_id": order.id,
        "modify_proposed": [
            {
                "dish_id": combo.id,
                "dish_number": combo.dish_number,
                "name": combo.name,
                "price_aed": str(combo.price_aed),
                "qty": 1,
            }
        ],
        "last_placed_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(
        db_session,
        _msg("Only lemon mint", phone=phone, wa_id="wamid.only"),
        restaurant_id=restaurant.id,
    )
    await db_session.commit()

    conv = await _conv(db_session, phone)
    proposed = conv.state.get("modify_proposed", [])
    assert proposed, "proposed must be updated"
    assert any("lemon mint" in p.get("name", "").lower() for p in proposed)
    assert not any("biriyani" in p.get("name", "").lower() for p in proposed)

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    body = rows[-1].payload.get("body", "").lower()
    assert "no changes proposed" not in body