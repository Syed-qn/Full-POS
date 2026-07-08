from decimal import Decimal

import pytest

from app.payments.mock import MockPaymentProcessor
from app.payments.service import (
    DuplicateChargeError,
    charge_tender,
    detect_duplicate_charge,
)


async def _seed_order(db_session, restaurant, *, phone, order_number, total):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone=phone, name="Dup Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number=order_number,
        status="confirmed", subtotal=total, total=total,
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()
    return order


@pytest.mark.anyio
async def test_detect_duplicate_charge_true_within_window(db_session, restaurant):
    order = await _seed_order(
        db_session, restaurant, phone="+971500001001", order_number="DUP-0001", total=Decimal("40.00")
    )
    gw = MockPaymentProcessor()
    await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id, tender_type="cash",
        amount_aed=Decimal("40.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()

    is_dup = await detect_duplicate_charge(
        db_session, restaurant_id=restaurant.id, order_id=order.id, amount_aed=Decimal("40.00"),
    )
    assert is_dup is True


@pytest.mark.anyio
async def test_detect_duplicate_charge_false_different_amount(db_session, restaurant):
    order = await _seed_order(
        db_session, restaurant, phone="+971500001002", order_number="DUP-0002", total=Decimal("40.00")
    )
    gw = MockPaymentProcessor()
    await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id, tender_type="cash",
        amount_aed=Decimal("15.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()

    is_dup = await detect_duplicate_charge(
        db_session, restaurant_id=restaurant.id, order_id=order.id, amount_aed=Decimal("25.00"),
    )
    assert is_dup is False


@pytest.mark.anyio
async def test_charge_tender_raises_on_double_tap(db_session, restaurant):
    order = await _seed_order(
        db_session, restaurant, phone="+971500001003", order_number="DUP-0003", total=Decimal("50.00")
    )
    gw = MockPaymentProcessor()
    await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id, tender_type="card",
        amount_aed=Decimal("50.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()

    with pytest.raises(DuplicateChargeError):
        await charge_tender(
            db_session, restaurant_id=restaurant.id, order_id=order.id, tender_type="card",
            amount_aed=Decimal("50.00"), tip_aed=Decimal("0.00"), gateway=gw,
        )


@pytest.mark.anyio
async def test_charge_tender_allows_different_amount_split_payment(db_session, restaurant):
    order = await _seed_order(
        db_session, restaurant, phone="+971500001004", order_number="DUP-0004", total=Decimal("100.00")
    )
    gw = MockPaymentProcessor()
    await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id, tender_type="cash",
        amount_aed=Decimal("40.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()
    # different amount -> not a duplicate, must succeed
    txn2 = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id, tender_type="card",
        amount_aed=Decimal("60.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()
    assert txn2.status == "succeeded"


@pytest.mark.anyio
async def test_charge_tender_allows_same_amount_different_orders(db_session, restaurant):
    order1 = await _seed_order(
        db_session, restaurant, phone="+971500001005", order_number="DUP-0005", total=Decimal("30.00")
    )
    order2 = await _seed_order(
        db_session, restaurant, phone="+971500001006", order_number="DUP-0006", total=Decimal("30.00")
    )
    gw = MockPaymentProcessor()
    await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order1.id, tender_type="cash",
        amount_aed=Decimal("30.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()
    txn2 = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order2.id, tender_type="cash",
        amount_aed=Decimal("30.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()
    assert txn2.status == "succeeded"


@pytest.mark.anyio
async def test_duplicate_charge_via_router(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500001007", name="Router Dup")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="DUP-RTR-0001",
        status="confirmed", subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()

    body = {"order_id": order.id, "tender_type": "card", "amount_aed": "22.00", "tip_aed": "0.00"}
    first = await client.post("/api/v1/payments/charge", json=body, headers=auth_headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/payments/charge", json=body, headers=auth_headers)
    assert second.status_code == 409
