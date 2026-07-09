"""Category 1 POS order-management — multi-type create, hold, courses, etc."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, OrderItem
from app.ordering.order_types import (
    ORDER_TYPE_DINE_IN,
    ORDER_TYPE_DRIVE_THRU,
    ORDER_TYPE_TAKEAWAY,
    PRIORITY_RUSH,
)
from app.ordering.pos_orders import (
    create_pos_order,
    fire_course,
    hold_order,
    list_held_orders,
    list_open_orders,
    mark_rush,
    refund_order,
    repeat_last_order,
    set_order_priority,
    unhold_order,
)
from app.ordering.scheduled import release_due_scheduled_orders
from app.tables.models import DiningTable


async def _menu_and_dish(db_session, restaurant):
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=101,
        name="Chicken Biryani",
        price_aed=Decimal("25.00"),
        category="Mains",
        is_available=True,
        name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.flush()
    return menu, dish


@pytest.mark.anyio
async def test_takeaway_order_no_address(db_session, restaurant):
    _, dish = await _menu_and_dish(db_session, restaurant)
    order = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_TAKEAWAY,
        customer_phone="+971500001001",
        customer_name="Walk In",
        items=[{"dish_id": dish.id, "qty": 1}],
    )
    await db_session.commit()
    assert order.order_type == ORDER_TYPE_TAKEAWAY
    assert order.address_id is None
    assert order.delivery_fee_aed == Decimal("0.00")
    assert order.status == OrderStatus.CONFIRMED


@pytest.mark.anyio
async def test_dine_in_requires_table(db_session, restaurant):
    _, dish = await _menu_and_dish(db_session, restaurant)
    with pytest.raises(ValueError, match="table_id"):
        await create_pos_order(
            db_session,
            restaurant_id=restaurant.id,
            order_type=ORDER_TYPE_DINE_IN,
            customer_phone="+971500001002",
            customer_name="Diner",
            items=[{"dish_id": dish.id, "qty": 1}],
        )


@pytest.mark.anyio
async def test_dine_in_and_drive_thru(db_session, restaurant):
    _, dish = await _menu_and_dish(db_session, restaurant)
    table = DiningTable(restaurant_id=restaurant.id, label="T1", seats=4)
    db_session.add(table)
    await db_session.flush()

    dine = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_DINE_IN,
        customer_phone="+971500001003",
        customer_name="Table Guest",
        items=[{"dish_id": dish.id, "qty": 2, "seat_number": 1}],
        table_id=table.id,
    )
    drive = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_DRIVE_THRU,
        customer_phone="+971500001004",
        customer_name="Driver",
        items=[{"dish_id": dish.id, "qty": 1}],
    )
    await db_session.commit()
    assert dine.table_id == table.id
    assert dine.order_type == ORDER_TYPE_DINE_IN
    assert drive.order_type == ORDER_TYPE_DRIVE_THRU
    assert drive.address_id is None


@pytest.mark.anyio
async def test_hold_unhold_and_open_list(db_session, restaurant):
    _, dish = await _menu_and_dish(db_session, restaurant)
    order = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_TAKEAWAY,
        customer_phone="+971500001005",
        customer_name="Hold Me",
        items=[{"dish_id": dish.id, "qty": 1}],
    )
    await hold_order(
        db_session, restaurant_id=restaurant.id, order_id=order.id, reason="wait for guest"
    )
    held = await list_held_orders(db_session, restaurant_id=restaurant.id)
    assert any(o.id == order.id for o in held)
    open_orders = await list_open_orders(db_session, restaurant_id=restaurant.id)
    assert all(o.id != order.id for o in open_orders)
    await unhold_order(db_session, restaurant_id=restaurant.id, order_id=order.id)
    assert order.held_at is None
    await db_session.commit()


@pytest.mark.anyio
async def test_rush_and_priority(db_session, restaurant):
    _, dish = await _menu_and_dish(db_session, restaurant)
    order = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_TAKEAWAY,
        customer_phone="+971500001006",
        customer_name="Rush",
        items=[{"dish_id": dish.id, "qty": 1}],
        priority="normal",
    )
    await mark_rush(db_session, restaurant_id=restaurant.id, order_id=order.id)
    assert order.priority == PRIORITY_RUSH
    await set_order_priority(
        db_session, restaurant_id=restaurant.id, order_id=order.id, priority="priority"
    )
    assert order.priority == "priority"
    await db_session.commit()


@pytest.mark.anyio
async def test_course_held_then_fire(db_session, restaurant):
    from app.kds.models import PrintJob

    _, dish = await _menu_and_dish(db_session, restaurant)
    order = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_TAKEAWAY,
        customer_phone="+971500001007",
        customer_name="Courses",
        items=[
            {"dish_id": dish.id, "qty": 1, "course_number": 1, "course_held": False},
            {"dish_id": dish.id, "qty": 1, "course_number": 2, "course_held": True},
        ],
    )
    await db_session.flush()
    from sqlalchemy import select

    items = list(
        (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    )
    held = [i for i in items if i.course_held]
    assert len(held) == 1
    jobs_before = list(
        (await db_session.scalars(select(PrintJob).where(PrintJob.order_id == order.id))).all()
    )
    assert len(jobs_before) >= 1  # course 1 fired at confirm

    await fire_course(
        db_session, restaurant_id=restaurant.id, order_id=order.id, course_number=2
    )
    await db_session.refresh(held[0])
    assert held[0].course_held is False
    assert held[0].fired_at is not None
    jobs_after = list(
        (await db_session.scalars(select(PrintJob).where(PrintJob.order_id == order.id))).all()
    )
    assert len(jobs_after) > len(jobs_before)
    await db_session.commit()


@pytest.mark.anyio
async def test_scheduled_release(db_session, restaurant):
    _, dish = await _menu_and_dish(db_session, restaurant)
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    due = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_TAKEAWAY,
        customer_phone="+971500001008",
        customer_name="Due",
        items=[{"dish_id": dish.id, "qty": 1}],
        scheduled_for=past,
        is_preorder=True,
        auto_confirm=True,
    )
    # past scheduled_for with auto_confirm True should confirm immediately
    assert due.status == OrderStatus.CONFIRMED

    pending = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_TAKEAWAY,
        customer_phone="+971500001009",
        customer_name="Later",
        items=[{"dish_id": dish.id, "qty": 1}],
        scheduled_for=future,
        is_preorder=True,
        auto_confirm=True,
    )
    assert pending.status == OrderStatus.DRAFT
    assert pending.is_preorder is True

    # Force due by setting scheduled_for to the past without release stamp
    pending.scheduled_for = datetime.now(timezone.utc) - timedelta(seconds=5)
    await db_session.flush()
    released = await release_due_scheduled_orders(db_session, restaurant_id=restaurant.id)
    assert any(o.id == pending.id for o in released)
    await db_session.refresh(pending)
    assert pending.status == OrderStatus.CONFIRMED
    assert pending.scheduled_released_at is not None
    await db_session.commit()


@pytest.mark.anyio
async def test_repeat_last_and_allergy_snapshot(db_session, restaurant):
    _, dish = await _menu_and_dish(db_session, restaurant)
    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500001010",
        name="Loyal",
        allergy_notes="peanuts",
    )
    db_session.add(cust)
    await db_session.flush()

    first = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_TAKEAWAY,
        customer_phone=cust.phone,
        customer_name=cust.name,
        items=[{"dish_id": dish.id, "qty": 2}],
    )
    assert first.customer_allergy_notes == "peanuts"

    # Mark as delivered-ish for "last order" query (non-draft)
    first.status = OrderStatus.DELIVERED
    await db_session.flush()

    repeat = await repeat_last_order(
        db_session, restaurant_id=restaurant.id, customer_phone=cust.phone
    )
    assert repeat.status == OrderStatus.DRAFT
    assert repeat.id != first.id
    from sqlalchemy import select

    items = list(
        (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == repeat.id))).all()
    )
    assert len(items) == 1
    assert items[0].qty == 2
    await db_session.commit()


@pytest.mark.anyio
async def test_refund_order(db_session, restaurant):
    from app.payments.mock import MockPaymentProcessor
    from app.payments.service import charge_tender

    _, dish = await _menu_and_dish(db_session, restaurant)
    order = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type=ORDER_TYPE_TAKEAWAY,
        customer_phone="+971500001011",
        customer_name="Pay",
        items=[{"dish_id": dish.id, "qty": 1}],
    )
    gw = MockPaymentProcessor()
    await charge_tender(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        tender_type="cash",
        amount_aed=order.total,
        tip_aed=Decimal("0.00"),
        gateway=gw,
    )
    result = await refund_order(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        reason="customer complaint",
        gateway=gw,
    )
    assert result["order_id"] == order.id
    assert len(result["refunds"]) == 1
    await db_session.commit()


@pytest.mark.anyio
async def test_qr_order_flow(db_session, restaurant):
    from app.ordering.qr_orders import create_qr_order, ensure_table_qr_token

    _, dish = await _menu_and_dish(db_session, restaurant)
    table = DiningTable(restaurant_id=restaurant.id, label="QR1", seats=2)
    db_session.add(table)
    await db_session.flush()
    table = await ensure_table_qr_token(
        db_session, restaurant_id=restaurant.id, table_id=table.id
    )
    assert table.qr_token
    order = await create_qr_order(
        db_session,
        qr_token=table.qr_token,
        customer_phone="+971500001012",
        customer_name="QR Guest",
        items=[{"dish_id": dish.id, "qty": 1}],
    )
    assert order.order_type == "qr"
    assert order.table_id == table.id
    await db_session.commit()
