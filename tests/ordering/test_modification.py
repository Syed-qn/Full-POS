from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order, OrderItem
from app.ordering.service import modify_order


async def _seed_confirmed_order(db_session) -> tuple[Order, object]:
    """Seed a confirmed order with one item. Returns (order, dish)."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=1,
        dish_number=110, name="Chicken Biryani",
        price_aed=Decimal("22.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.flush()

    customer = Customer(
        restaurant_id=1, phone="+971501230099", name="Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-MOD1", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        sla_confirmed_at=now, sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id, dish_id=dish.id,
        dish_number=110, dish_name="Chicken Biryani",
        price_aed=Decimal("22.00"), qty=1,
    )
    db_session.add(item)
    await db_session.commit()
    return order, dish


async def test_modify_order_recalculates_total(db_session):
    """Adding an item via modify_order recalculates subtotal + total."""
    order, dish = await _seed_confirmed_order(db_session)

    await modify_order(
        db_session, order=order,
        new_items=[{"dish": dish, "qty": 2, "notes": None}],
        actor="customer",
    )
    await db_session.commit()
    await db_session.refresh(order)

    assert order.subtotal == Decimal("44.00")
    assert order.total == Decimal("44.00")


async def test_modify_order_restarts_sla_clock(db_session):
    """SLA deadline is reset to now+40 min after modification."""
    order, dish = await _seed_confirmed_order(db_session)
    original_deadline = order.sla_deadline

    await modify_order(
        db_session, order=order,
        new_items=[{"dish": dish, "qty": 1, "notes": None}],
        actor="customer",
    )
    await db_session.commit()
    await db_session.refresh(order)

    assert order.sla_deadline > original_deadline


async def test_modify_order_blocked_at_ready(db_session):
    """Modification at or after ready raises ValueError."""
    order, dish = await _seed_confirmed_order(db_session)
    order.status = OrderStatus.READY
    await db_session.commit()

    with pytest.raises(ValueError, match="modification.*not allowed"):
        await modify_order(
            db_session, order=order,
            new_items=[{"dish": dish, "qty": 1, "notes": None}],
            actor="customer",
        )


async def test_modify_order_produces_audit_log(db_session):
    """Each modification is recorded in audit_log."""
    order, dish = await _seed_confirmed_order(db_session)

    await modify_order(
        db_session, order=order,
        new_items=[{"dish": dish, "qty": 1, "notes": "extra spicy"}],
        actor="customer",
    )
    await db_session.commit()

    logs = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(r.action == "order_modified" for r in logs)
