from decimal import Decimal

import pytest
from sqlalchemy import select

from app.kds.models import KitchenStation, PrintJob
from app.kds.service import create_tickets_for_order
from app.menu.models import Dish, Menu
from app.ordering.models import Customer, Order, OrderItem


@pytest.mark.anyio
async def test_create_tickets_sets_status_and_snapshot_and_enqueues_print_jobs(db_session, restaurant):
    grill = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    db_session.add(grill)
    await db_session.flush()

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), category="Grills", is_available=True,
        name_normalized="kebab", station_id=grill.id,
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000099", name="Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="T-0001",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=1,
    )
    db_session.add(item)
    await db_session.commit()

    await create_tickets_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.commit()

    await db_session.refresh(item)
    assert item.kitchen_status == "received"
    assert item.station_id_snapshot == grill.id

    jobs = (await db_session.scalars(
        select(PrintJob).where(PrintJob.order_id == order.id)
    )).all()
    assert len(jobs) == 1
    assert jobs[0].station_id == grill.id
    assert jobs[0].status == "pending"
    assert "Kebab" in jobs[0].payload
    assert "T-0001" in jobs[0].payload
