"""Category 5 — full payment & billing wiring tests."""

from decimal import Decimal

import pytest

from app.payments.billing import apply_billing_fees, set_billing_settings
from app.payments.mock import MockPaymentProcessor
from app.payments.service import (
    charge_tender,
    complete_payment_link,
    create_payment_link,
    import_settlement,
    mark_pay_later,
    reconciliation_report,
    total_paid,
)


async def _order(db_session, restaurant, total="100.00", phone="+971500009901"):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone=phone, name="Pay C5")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number=f"C5-{phone[-4:]}",
        status="confirmed",
        subtotal=Decimal(total),
        total=Decimal(total),
    )
    db_session.add(order)
    await db_session.flush()
    return order


@pytest.mark.anyio
async def test_tap_to_pay_and_wallet_tenders(db_session, restaurant):
    order = await _order(db_session, restaurant, phone="+971500009911")
    gw = MockPaymentProcessor()
    for i, tender in enumerate(("tap_to_pay", "apple_pay", "google_pay", "online"), start=1):
        txn = await charge_tender(
            db_session,
            restaurant_id=restaurant.id,
            order_id=order.id,
            tender_type=tender,
            amount_aed=Decimal(f"{10 + i}.00"),  # unique amounts avoid 30s duplicate window
            tip_aed=Decimal("0"),
            gateway=gw,
            channel="terminal" if tender == "tap_to_pay" else "online",
            reference_meta="term-1" if tender == "tap_to_pay" else None,
        )
        assert txn.status == "succeeded"
        assert txn.provider_charge_id
        if tender in ("apple_pay", "google_pay", "tap_to_pay", "online"):
            assert txn.wallet_session_id


@pytest.mark.anyio
async def test_room_charge_and_pay_later(db_session, restaurant):
    order = await _order(db_session, restaurant, total="50.00", phone="+971500009912")
    gw = MockPaymentProcessor()
    room = await charge_tender(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        tender_type="room_charge",
        amount_aed=Decimal("20.00"),
        tip_aed=Decimal("0"),
        gateway=gw,
        reference_meta="1204",
    )
    assert room.status == "succeeded"
    await db_session.refresh(order)
    assert order.room_number == "1204"
    assert order.payment_terms == "room_charge"

    pl = await mark_pay_later(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        amount_aed=Decimal("30.00"),
        gateway=gw,
    )
    assert pl.tender_type == "pay_later"
    await db_session.refresh(order)
    assert order.payment_terms == "pay_later"
    assert await total_paid(db_session, order_id=order.id) == Decimal("50.00")


@pytest.mark.anyio
async def test_payment_link_roundtrip(db_session, restaurant):
    order = await _order(db_session, restaurant, total="40.00", phone="+971500009913")
    link = await create_payment_link(
        db_session, restaurant_id=restaurant.id, order_id=order.id, amount_aed=Decimal("40")
    )
    assert link.token
    assert link.status == "pending"
    txn = await complete_payment_link(
        db_session,
        token=link.token,
        tender_type="online",
        gateway=MockPaymentProcessor(),
    )
    assert txn.status == "succeeded"
    await db_session.refresh(link)
    assert link.status == "paid"
    assert link.paid_transaction_id == txn.id


@pytest.mark.anyio
async def test_billing_fees_and_discounts(db_session, restaurant):
    from app.ordering.payments import recompute_order_total
    from app.payments.service import apply_order_discount

    set_billing_settings(
        restaurant,
        {"service_charge_pct": 10, "packaging_charge_aed": 2, "min_order_aed": 50},
    )
    order = await _order(db_session, restaurant, total="20.00", phone="+971500009914")
    order.subtotal = Decimal("20.00")
    apply_billing_fees(order, restaurant)
    assert order.service_charge_aed == Decimal("2.00")
    assert order.packaging_charge_aed == Decimal("2.00")
    assert order.min_order_surcharge_aed == Decimal("30.00")
    await recompute_order_total(db_session, order=order)
    # 20 + 0 fee + 2 svc + 2 pack + 30 min = 54
    assert order.total == Decimal("54.00")

    await apply_order_discount(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        discount_type="manager",
        amount_aed=Decimal("4.00"),
        reason="comp",
    )
    await db_session.refresh(order)
    assert order.manager_discount_aed == Decimal("4.00")
    assert order.total == Decimal("50.00")


@pytest.mark.anyio
async def test_gift_card_issue_and_redeem(db_session, restaurant):
    from app.giftcards.service import issue_gift_card, redeem_gift_card

    order = await _order(db_session, restaurant, total="25.00", phone="+971500009915")
    card = await issue_gift_card(
        db_session,
        restaurant_id=restaurant.id,
        amount_aed=Decimal("50.00"),
        pin="1234",
        code="GCATEST1",
    )
    assert card.balance_aed == Decimal("50.00")
    card2, txn = await redeem_gift_card(
        db_session,
        restaurant_id=restaurant.id,
        code="GCATEST1",
        pin="1234",
        order_id=order.id,
        amount_aed=Decimal("25.00"),
    )
    assert txn.tender_type == "gift_card"
    assert card2.balance_aed == Decimal("25.00")


@pytest.mark.anyio
async def test_psp_reconciliation(db_session, restaurant):
    order = await _order(db_session, restaurant, total="80.00", phone="+971500009916")
    txn = await charge_tender(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        tender_type="card",
        amount_aed=Decimal("80.00"),
        tip_aed=Decimal("0"),
        gateway=MockPaymentProcessor(),
    )
    settlement = await import_settlement(
        db_session,
        restaurant_id=restaurant.id,
        provider="stripe",
        provider_payout_id="po_test_1",
        amount_aed=Decimal("80.00"),
        lines=[{"provider_charge_id": txn.provider_charge_id, "amount_aed": "80.00"}],
    )
    assert settlement.status == "matched"
    assert settlement.matched_txn_count == 1
    report = await reconciliation_report(db_session, restaurant_id=restaurant.id)
    assert report["matched_line_count"] >= 1
    assert report["unmatched_txn_count"] == 0


@pytest.mark.anyio
async def test_category5_http_paths(client, auth_headers, db_session):
    """HTTP wiring — order belongs to the auth_headers tenant (signup restaurant)."""
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    assert restaurant is not None
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009920", name="HTTP")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C5-HTTP",
        status="confirmed",
        subtotal=Decimal("60.00"),
        total=Decimal("60.00"),
    )
    db_session.add(order)
    await db_session.flush()

    bill = await client.put(
        "/api/v1/payments/billing-settings",
        headers=auth_headers,
        json={"service_charge_pct": 5, "packaging_charge_aed": 1, "min_order_aed": 0},
    )
    assert bill.status_code == 200, bill.text
    assert bill.json()["service_charge_pct"] == 5

    charge = await client.post(
        "/api/v1/payments/charge",
        headers=auth_headers,
        json={
            "order_id": order.id,
            "tender_type": "tap_to_pay",
            "amount_aed": "20.00",
            "tip_aed": "2.00",
            "terminal_id": "softpos-1",
            "channel": "terminal",
        },
    )
    assert charge.status_code == 201, charge.text

    link = await client.post(
        "/api/v1/payments/links",
        headers=auth_headers,
        json={"order_id": order.id, "amount_aed": "18.00"},
    )
    assert link.status_code == 201, link.text
    token = link.json()["token"]
    pub = await client.get(f"/api/v1/public/pay/{token}")
    assert pub.status_code == 200
    done = await client.post(
        f"/api/v1/public/pay/{token}/complete",
        json={"tender_type": "online"},
    )
    assert done.status_code == 200, done.text

    disc = await client.post(
        f"/api/v1/orders/{order.id}/discounts",
        headers=auth_headers,
        json={"discount_type": "manager", "amount_aed": "5.00", "reason": "VIP"},
    )
    assert disc.status_code == 201, disc.text

    gc = await client.post(
        "/api/v1/gift-cards/issue",
        headers=auth_headers,
        json={"amount_aed": "30.00", "pin": "9999", "code": "HTTPCARD1"},
    )
    assert gc.status_code == 201, gc.text
    redeem = await client.post(
        "/api/v1/gift-cards/redeem",
        headers=auth_headers,
        json={
            "code": "HTTPCARD1",
            "pin": "9999",
            "order_id": order.id,
            "amount_aed": "15.00",
        },
    )
    assert redeem.status_code == 201, redeem.text

    pay_later = await client.post(
        f"/api/v1/orders/{order.id}/pay-later",
        headers=auth_headers,
        json={},
    )
    assert pay_later.status_code in (201, 409), pay_later.text

    payments = await client.get(
        f"/api/v1/orders/{order.id}/payments", headers=auth_headers
    )
    assert payments.status_code == 200
    assert len(payments.json()["transactions"]) >= 2

    recon = await client.get("/api/v1/payments/reconciliation/report", headers=auth_headers)
    assert recon.status_code == 200
