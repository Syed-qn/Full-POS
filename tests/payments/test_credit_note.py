from decimal import Decimal

import pytest

from app.payments.mock import MockPaymentProcessor
from app.payments.service import (
    PaymentFailedError,
    charge_tender,
    issue_credit_note,
    refund_transaction,
)


async def _seed_order_and_txn(db_session, restaurant, *, phone, order_number, total):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone=phone, name="Credit Note Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number=order_number,
        status="confirmed", subtotal=total, total=total,
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    gw = MockPaymentProcessor()
    txn = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="card", amount_aed=total, tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()
    return order, txn, gw


@pytest.mark.anyio
async def test_issue_credit_note_after_refund(db_session, restaurant):
    order, txn, gw = await _seed_order_and_txn(
        db_session, restaurant, phone="+971500000701", order_number="CN-TXN-0001", total=Decimal("75.00")
    )

    await refund_transaction(
        db_session, transaction_id=txn.id, restaurant_id=restaurant.id,
        amount_aed=Decimal("75.00"), gateway=gw,
    )
    await db_session.commit()

    note = await issue_credit_note(
        db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
        amount_aed=Decimal("75.00"), reason="customer refund",
    )
    await db_session.commit()

    assert note.id is not None
    assert note.restaurant_id == restaurant.id
    assert note.order_id == order.id
    assert note.transaction_id == txn.id
    assert note.amount_aed == Decimal("75.00")
    assert note.reason == "customer refund"
    assert note.credit_note_number == f"CN-{restaurant.id}-0001"
    assert note.issued_at is not None


@pytest.mark.anyio
async def test_credit_note_numbers_sequential_per_restaurant(db_session, restaurant):
    order, txn, gw = await _seed_order_and_txn(
        db_session, restaurant, phone="+971500000702", order_number="CN-TXN-0002", total=Decimal("30.00")
    )
    await refund_transaction(
        db_session, transaction_id=txn.id, restaurant_id=restaurant.id,
        amount_aed=Decimal("30.00"), gateway=gw,
    )
    await db_session.commit()

    note1 = await issue_credit_note(
        db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
        amount_aed=Decimal("10.00"), reason=None,
    )
    await db_session.commit()
    note2 = await issue_credit_note(
        db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
        amount_aed=Decimal("10.00"), reason=None,
    )
    await db_session.commit()

    assert note1.credit_note_number == f"CN-{restaurant.id}-0001"
    assert note2.credit_note_number == f"CN-{restaurant.id}-0002"


@pytest.mark.anyio
async def test_credit_note_via_router(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000703", name="Router CN")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="CN-RTR-0001",
        status="confirmed", subtotal=Decimal("50.00"), total=Decimal("50.00"),
    )
    db_session.add(order)
    await db_session.commit()

    charge = await client.post(
        "/api/v1/payments/charge",
        json={"order_id": order.id, "tender_type": "card", "amount_aed": "50.00", "tip_aed": "0.00"},
        headers=auth_headers,
    )
    assert charge.status_code == 201
    txn_id = charge.json()["id"]

    refund = await client.post(
        f"/api/v1/payments/{txn_id}/refund", json={"amount_aed": "50.00"}, headers=auth_headers,
    )
    assert refund.status_code == 200

    cn = await client.post(
        f"/api/v1/payments/{txn_id}/credit-note",
        json={"amount_aed": "50.00", "reason": "full refund"},
        headers=auth_headers,
    )
    assert cn.status_code == 201
    body = cn.json()
    assert body["amount_aed"] == "50.00"
    assert body["credit_note_number"].startswith(f"CN-{restaurant.id}-")


@pytest.mark.anyio
async def test_credit_note_router_404_for_unknown_transaction(client, auth_headers):
    resp = await client.post(
        "/api/v1/payments/999999/credit-note",
        json={"amount_aed": "10.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_credit_note_router_rejects_non_refunded_transaction(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000704", name="Router CN Guard")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="CN-RTR-0002",
        status="confirmed",
        subtotal=Decimal("40.00"),
        total=Decimal("40.00"),
    )
    db_session.add(order)
    await db_session.commit()

    charge = await client.post(
        "/api/v1/payments/charge",
        json={"order_id": order.id, "tender_type": "card", "amount_aed": "40.00", "tip_aed": "0.00"},
        headers=auth_headers,
    )
    assert charge.status_code == 201

    resp = await client.post(
        f"/api/v1/payments/{charge.json()['id']}/credit-note",
        json={"amount_aed": "40.00", "reason": "not refunded yet"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.anyio
@pytest.mark.parametrize("bad_amount", ["0.00", "-5.00"])
async def test_credit_note_router_rejects_non_positive_amount(client, auth_headers, bad_amount):
    resp = await client.post(
        "/api/v1/payments/999999/credit-note",
        json={"amount_aed": bad_amount},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_issue_credit_note_rejects_non_refunded_transaction(db_session, restaurant):
    """A transaction that was never refunded must not be able to back a
    credit note — otherwise a manager (or a compromised session) can mint
    store credit out of thin air."""
    order, txn, gw = await _seed_order_and_txn(
        db_session, restaurant, phone="+971500000705", order_number="CN-TXN-0005", total=Decimal("40.00")
    )

    with pytest.raises(PaymentFailedError):
        await issue_credit_note(
            db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
            amount_aed=Decimal("40.00"), reason="never refunded",
        )


@pytest.mark.anyio
async def test_issue_credit_note_rejects_amount_exceeding_refunded(db_session, restaurant):
    """Even after a real refund, credit notes issued against it must not
    exceed the refunded amount — otherwise the same refund can be
    double-spent as store credit."""
    order, txn, gw = await _seed_order_and_txn(
        db_session, restaurant, phone="+971500000706", order_number="CN-TXN-0006", total=Decimal("50.00")
    )
    await refund_transaction(
        db_session, transaction_id=txn.id, restaurant_id=restaurant.id,
        amount_aed=Decimal("30.00"), gateway=gw,
    )
    await db_session.commit()

    with pytest.raises(PaymentFailedError):
        await issue_credit_note(
            db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
            amount_aed=Decimal("30.01"), reason="over the refunded amount",
        )


@pytest.mark.anyio
async def test_issue_credit_note_rejects_sum_exceeding_refunded_across_notes(db_session, restaurant):
    order, txn, gw = await _seed_order_and_txn(
        db_session, restaurant, phone="+971500000707", order_number="CN-TXN-0007", total=Decimal("50.00")
    )
    await refund_transaction(
        db_session, transaction_id=txn.id, restaurant_id=restaurant.id,
        amount_aed=Decimal("30.00"), gateway=gw,
    )
    await db_session.commit()

    await issue_credit_note(
        db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
        amount_aed=Decimal("20.00"), reason="first note",
    )
    await db_session.commit()

    with pytest.raises(PaymentFailedError):
        await issue_credit_note(
            db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
            amount_aed=Decimal("10.01"), reason="pushes total past refunded amount",
        )


@pytest.mark.anyio
async def test_issue_credit_notes_up_to_refunded_amount_across_multiple_notes_succeeds(
    db_session, restaurant,
):
    order, txn, gw = await _seed_order_and_txn(
        db_session, restaurant, phone="+971500000708", order_number="CN-TXN-0008", total=Decimal("50.00")
    )
    await refund_transaction(
        db_session, transaction_id=txn.id, restaurant_id=restaurant.id,
        amount_aed=Decimal("30.00"), gateway=gw,
    )
    await db_session.commit()

    note1 = await issue_credit_note(
        db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
        amount_aed=Decimal("20.00"), reason="first note",
    )
    await db_session.commit()
    note2 = await issue_credit_note(
        db_session, restaurant_id=restaurant.id, order_id=order.id, transaction_id=txn.id,
        amount_aed=Decimal("10.00"), reason="second note, exactly to the limit",
    )
    await db_session.commit()

    assert note1.amount_aed + note2.amount_aed == Decimal("30.00")
