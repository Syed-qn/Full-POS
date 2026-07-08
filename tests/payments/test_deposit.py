from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.payments.mock import MockPaymentProcessor
from app.payments.service import charge_deposit


@pytest.mark.anyio
async def test_charge_deposit_increments_order_deposit_paid(db_session, restaurant):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000801", name="Deposit Test")
    db_session.add(cust)
    await db_session.flush()
    scheduled_for = datetime.now(timezone.utc) + timedelta(hours=3)
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="DEP-0001",
        status="confirmed", subtotal=Decimal("100.00"), total=Decimal("100.00"),
        scheduled_for=scheduled_for,
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    txn = await charge_deposit(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        amount_aed=Decimal("25.00"), gateway=MockPaymentProcessor(),
    )
    await db_session.commit()
    await db_session.refresh(order)

    assert txn.status == "succeeded"
    assert order.deposit_paid_aed == Decimal("25.00")


@pytest.mark.anyio
async def test_charge_deposit_twice_accumulates(db_session, restaurant):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000802", name="Deposit Test 2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="DEP-0002",
        status="confirmed", subtotal=Decimal("200.00"), total=Decimal("200.00"),
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=5),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    gw = MockPaymentProcessor()
    await charge_deposit(db_session, restaurant_id=restaurant.id, order_id=order.id, amount_aed=Decimal("30.00"), gateway=gw)
    await db_session.commit()
    await charge_deposit(db_session, restaurant_id=restaurant.id, order_id=order.id, amount_aed=Decimal("20.00"), gateway=gw)
    await db_session.commit()
    await db_session.refresh(order)

    assert order.deposit_paid_aed == Decimal("50.00")


@pytest.mark.anyio
async def test_charge_deposit_unknown_order_raises(db_session, restaurant):
    with pytest.raises(ValueError):
        await charge_deposit(
            db_session, restaurant_id=restaurant.id, order_id=999999,
            amount_aed=Decimal("10.00"), gateway=MockPaymentProcessor(),
        )


@pytest.mark.anyio
async def test_deposit_via_router(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000803", name="Router Deposit")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="DEP-RTR-0001",
        status="confirmed", subtotal=Decimal("120.00"), total=Decimal("120.00"),
        scheduled_for=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/deposit",
        json={"amount_aed": "40.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["deposit_paid_aed"] == "40.00"


@pytest.mark.anyio
@pytest.mark.parametrize("bad_amount", ["0.00", "-10.00"])
async def test_deposit_router_rejects_non_positive_amount(client, auth_headers, bad_amount):
    resp = await client.post(
        "/api/v1/orders/999999/deposit",
        json={"amount_aed": bad_amount},
        headers=auth_headers,
    )
    assert resp.status_code == 422
