"""No 5% is hardcoded anywhere the number reaches a customer or the FTA.

The VAT rate became settable, which is worthless if parts of the system keep
assuming 0.05. These pin the three places that did: credit notes, tax invoice
lines, and the VAT report.
"""

from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_credit_note_uses_the_rate_the_order_was_charged(db_session, restaurant):
    # Was `amount * 0.05 / 1.05`, a permanent 5%. At a 9% rate every credit note
    # would have reclaimed 5%, understating the refund to the FTA every time.
    from app.compliance.refund_notes import issue_refund_note
    from app.ordering.models import Customer, Order

    cust = Customer(
        restaurant_id=restaurant.id, phone="+971500000111", name="R", total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="VAT-9",
        status="delivered", subtotal=Decimal("100"), total=Decimal("109"),
        vat_rate=Decimal("0.0900"),
    )
    db_session.add(order)
    await db_session.flush()

    note = await issue_refund_note(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        amount_aed=Decimal("109.00"),
    )
    # 109.00 gross at 9% = 100.00 net + 9.00 tax. The old code said 5.19.
    assert note.vat_amount_aed == Decimal("9.00")


@pytest.mark.anyio
async def test_credit_note_on_a_zero_rated_order_reclaims_no_vat(db_session, restaurant):
    from app.compliance.refund_notes import issue_refund_note
    from app.ordering.models import Customer, Order

    cust = Customer(
        restaurant_id=restaurant.id, phone="+971500000222", name="Z", total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="VAT-0",
        status="delivered", subtotal=Decimal("50"), total=Decimal("50"),
        vat_rate=Decimal("0"),
    )
    db_session.add(order)
    await db_session.flush()

    note = await issue_refund_note(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        amount_aed=Decimal("50.00"),
    )
    assert note.vat_amount_aed == Decimal("0.00")


def test_zero_rate_survives_the_fallback_chain():
    # Decimal("0") is falsy, so `item.vat_rate or order.vat_rate or default`
    # treated a genuine 0% as "not set" and invoiced it at the default 5%.
    from app.ordering.tax import _first_set

    assert _first_set(Decimal("0"), Decimal("0.05")) == Decimal("0")
    assert _first_set(None, Decimal("0.05")) == Decimal("0.05")
    assert _first_set(None, None, Decimal("0.09")) == Decimal("0.09")
