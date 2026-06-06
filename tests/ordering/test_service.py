from app.ordering.models import Customer, CustomerAddress


async def test_customer_table_has_expected_columns(db_session):
    c = Customer(
        restaurant_id=1,
        phone="+971501234567",
        name="Ali Hassan",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend="0.00",
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    assert c.id is not None
    assert c.total_orders == 0


async def test_customer_address_table_has_expected_columns(db_session):
    c = Customer(
        restaurant_id=1, phone="+971501234568", name="Sara",
        usual_order_times={}, tags={}, total_orders=0, total_spend="0.00",
    )
    db_session.add(c)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=c.id,
        latitude=25.2048,
        longitude=55.2708,
        room_apartment="111",
        building="1-2",
        receiver_name="Sara",
        additional_details="Blue door",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()
    await db_session.refresh(addr)
    assert addr.id is not None
    assert addr.confirmed is True
    assert addr.last_used_at is None
