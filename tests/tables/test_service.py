import pytest

from app.tables.models import DiningTable
from app.tables.service import InvalidTableTransitionError, TableNotFoundError, transfer_order, transition_status


@pytest.mark.anyio
async def test_transition_available_to_seated(db_session, restaurant):
    table = DiningTable(restaurant_id=restaurant.id, label="T1", seats=4)
    db_session.add(table)
    await db_session.flush()
    await transition_status(db_session, table_id=table.id, restaurant_id=restaurant.id, to_status="seated")
    await db_session.commit()
    await db_session.refresh(table)
    assert table.status == "seated"


@pytest.mark.anyio
async def test_direct_available_to_needs_bill_rejected(db_session, restaurant):
    table = DiningTable(restaurant_id=restaurant.id, label="T2", seats=2)
    db_session.add(table)
    await db_session.flush()
    await db_session.commit()
    with pytest.raises(InvalidTableTransitionError):
        await transition_status(db_session, table_id=table.id, restaurant_id=restaurant.id, to_status="needs_bill")


@pytest.mark.anyio
async def test_transition_missing_table_raises(db_session, restaurant):
    with pytest.raises(TableNotFoundError):
        await transition_status(db_session, table_id=999999, restaurant_id=restaurant.id, to_status="seated")


@pytest.mark.anyio
async def test_transfer_order_moves_table_id(db_session, restaurant):
    from decimal import Decimal

    from app.ordering.models import Customer, Order

    t1 = DiningTable(restaurant_id=restaurant.id, label="T1", seats=4)
    t2 = DiningTable(restaurant_id=restaurant.id, label="T2", seats=4)
    db_session.add_all([t1, t2])
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000066", name="Dine In")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="D-0001",
        status="confirmed", subtotal=Decimal("50.00"), total=Decimal("50.00"), table_id=t1.id,
    )
    db_session.add(order)
    await db_session.commit()

    await transfer_order(db_session, order_id=order.id, restaurant_id=restaurant.id, to_table_id=t2.id)
    await db_session.commit()
    await db_session.refresh(order)
    assert order.table_id == t2.id
