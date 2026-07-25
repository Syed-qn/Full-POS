"""A second dine-in create on a table that already has an open tab MERGES into
that tab instead of opening a duplicate order — and never rewrites the original
creator's staff attribution. Guards the stale-POS-screen split-tab race."""

from decimal import Decimal

import pytest


async def _restaurant(db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


async def _setup(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.staff.models import StaffMember
    from app.tables.models import DiningTable

    table = DiningTable(
        restaurant_id=restaurant.id, label="D1", seats=4, status="available",
        pos_x=1.0, pos_y=1.0,
    )
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add_all([table, menu])
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), category="Grills", is_available=True,
        name_normalized="kebab",
    )
    cashier = StaffMember(
        restaurant_id=restaurant.id, name="Cashier Cathy", role="cashier",
        pin_hash="x", is_active=True,
    )
    waiter = StaffMember(
        restaurant_id=restaurant.id, name="Waiter Wal", role="waiter",
        pin_hash="x", is_active=True,
    )
    db_session.add_all([dish, cashier, waiter])
    await db_session.flush()
    return table, dish, cashier, waiter


@pytest.mark.anyio
async def test_second_dine_in_create_merges_into_open_tab(client, auth_headers, db_session):
    from app.ordering.pos_orders import create_pos_order

    restaurant = await _restaurant(db_session)
    table, dish, cashier, waiter = await _setup(db_session, restaurant)

    # Cashier opens the tab.
    first = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type="dine_in",
        customer_phone="0000000000",
        customer_name="Walk-in",
        items=[{"dish_id": dish.id, "qty": 2}],
        table_id=table.id,
        staff_id=cashier.id,
    )
    await db_session.flush()

    # Waiter (stale screen: thinks the table is free) adds a round on the SAME table.
    second = await create_pos_order(
        db_session,
        restaurant_id=restaurant.id,
        order_type="dine_in",
        customer_phone="0000000000",
        customer_name="Walk-in",
        items=[{"dish_id": dish.id, "qty": 1}],
        table_id=table.id,
        staff_id=waiter.id,
    )

    # Same order — no duplicate tab.
    assert second.id == first.id
    # Combined bill: 2 + 1 = 3 kebabs.
    from sqlalchemy import select

    from app.ordering.models import OrderItem

    items = (
        await db_session.scalars(
            select(OrderItem).where(
                OrderItem.order_id == second.id, OrderItem.cancelled.is_(False)
            )
        )
    ).all()
    total_qty = sum(i.qty for i in items)
    assert total_qty == 3
    # Original creator (cashier) is preserved — the waiter did NOT take it over.
    assert second.staff_id == cashier.id


@pytest.mark.anyio
async def test_only_one_open_order_per_table(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.ordering.models import Order
    from app.ordering.order_types import OPEN_ORDER_STATUSES
    from app.ordering.pos_orders import create_pos_order

    restaurant = await _restaurant(db_session)
    table, dish, cashier, waiter = await _setup(db_session, restaurant)

    for staff in (cashier, waiter, cashier):
        await create_pos_order(
            db_session,
            restaurant_id=restaurant.id,
            order_type="dine_in",
            customer_phone="0000000000",
            customer_name="Walk-in",
            items=[{"dish_id": dish.id, "qty": 1}],
            table_id=table.id,
            staff_id=staff.id,
        )
        await db_session.flush()

    open_orders = (
        await db_session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant.id,
                Order.table_id == table.id,
                Order.status.in_(OPEN_ORDER_STATUSES),
            )
        )
    ).all()
    assert len(open_orders) == 1
