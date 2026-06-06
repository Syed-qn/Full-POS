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


def _get_test_token() -> str:
    """Bearer token for the autouse-seeded restaurant (id=1)."""
    from app.identity.auth import create_access_token

    return create_access_token(restaurant_id=1)


async def test_get_order_api_returns_order(client, db_session):
    """GET /api/v1/orders/{id} returns order JSON for the authenticated restaurant."""
    from decimal import Decimal

    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    customer = Customer(
        restaurant_id=1, phone="+971501220001", name="API Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-API1", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/orders/{order.id}",
        headers={"Authorization": f"Bearer {_get_test_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_number"] == "R1-API1"
    assert data["status"] == "confirmed"


async def test_get_order_api_404_for_unknown(client):
    """GET /api/v1/orders/{id} returns 404 when the order does not exist."""
    resp = await client.get(
        "/api/v1/orders/999999",
        headers={"Authorization": f"Bearer {_get_test_token()}"},
    )
    assert resp.status_code == 404


async def test_list_orders_api_filters_by_status(client, db_session):
    """GET /api/v1/orders?status=... returns only matching orders for the restaurant."""
    from decimal import Decimal

    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Customer, Order

    customer = Customer(
        restaurant_id=1, phone="+971501220002", name="List Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    db_session.add_all([
        Order(
            restaurant_id=1, customer_id=customer.id, order_number="R1-LIST1",
            status=OrderStatus.CONFIRMED, priority="normal",
            weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("10.00"), total=Decimal("10.00"),
        ),
        Order(
            restaurant_id=1, customer_id=customer.id, order_number="R1-LIST2",
            status=OrderStatus.DRAFT, priority="normal",
            weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("12.00"), total=Decimal("12.00"),
        ),
    ])
    await db_session.commit()

    resp = await client.get(
        "/api/v1/orders",
        params={"status": "confirmed"},
        headers={"Authorization": f"Bearer {_get_test_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    numbers = {o["order_number"] for o in data}
    assert "R1-LIST1" in numbers
    assert "R1-LIST2" not in numbers
