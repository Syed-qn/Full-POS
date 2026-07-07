from decimal import Decimal

import pytest

from app.payments.mock import MockPaymentProcessor
from app.payments.service import (
    InsufficientPaymentError,
    charge_tender,
    refund_transaction,
    total_paid,
)


@pytest.mark.anyio
async def test_charge_tender_cash_never_calls_gateway(db_session, restaurant):
    from decimal import Decimal as D

    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000501", name="Pay Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="PAY-0001",
        status="confirmed", subtotal=D("50.00"), total=D("50.00"),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    txn = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="cash", amount_aed=Decimal("50.00"), tip_aed=Decimal("0.00"),
        gateway=MockPaymentProcessor(),
    )
    await db_session.commit()
    assert txn.status == "succeeded"
    assert txn.provider == "cash"
    assert txn.provider_charge_id is None


@pytest.mark.anyio
async def test_charge_tender_card_uses_gateway_and_records_charge_id(db_session, restaurant):
    from decimal import Decimal as D

    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000502", name="Pay Test2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="PAY-0002",
        status="confirmed", subtotal=D("80.00"), total=D("80.00"),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    txn = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="card", amount_aed=Decimal("80.00"), tip_aed=Decimal("10.00"),
        gateway=MockPaymentProcessor(),
    )
    await db_session.commit()
    assert txn.status == "succeeded"
    assert txn.provider_charge_id is not None
    assert txn.tip_aed == Decimal("10.00")


@pytest.mark.anyio
async def test_split_payment_two_tenders_sum_to_total(db_session, restaurant):
    from decimal import Decimal as D

    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000503", name="Split Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="PAY-0003",
        status="confirmed", subtotal=D("100.00"), total=D("100.00"),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    gw = MockPaymentProcessor()
    await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="cash", amount_aed=Decimal("40.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()
    await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="card", amount_aed=Decimal("60.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()

    total = await total_paid(db_session, order_id=order.id)
    assert total == Decimal("100.00")


@pytest.mark.anyio
async def test_refund_transaction_reduces_effective_paid(db_session, restaurant):
    from decimal import Decimal as D

    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000504", name="Refund Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="PAY-0004",
        status="confirmed", subtotal=D("60.00"), total=D("60.00"),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    gw = MockPaymentProcessor()
    txn = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="card", amount_aed=Decimal("60.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()

    await refund_transaction(db_session, transaction_id=txn.id, restaurant_id=restaurant.id, amount_aed=Decimal("20.00"), gateway=gw)
    await db_session.commit()
    await db_session.refresh(txn)
    assert txn.refunded_amount_aed == Decimal("20.00")
    assert txn.status == "partially_refunded"  # 20 of 60 refunded, not the full amount


@pytest.mark.anyio
async def test_refund_more_than_paid_rejected(db_session, restaurant):
    from decimal import Decimal as D

    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000505", name="Over Refund")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="PAY-0005",
        status="confirmed", subtotal=D("20.00"), total=D("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    gw = MockPaymentProcessor()
    txn = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="card", amount_aed=Decimal("20.00"), tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()

    with pytest.raises(InsufficientPaymentError):
        await refund_transaction(db_session, transaction_id=txn.id, restaurant_id=restaurant.id, amount_aed=Decimal("25.00"), gateway=gw)
