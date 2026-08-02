"""net + VAT must equal gross on the sheet the VAT return is filed from.

The export reported ``net = order.subtotal`` and ``gross = order.total``, which
reconciles in neither pricing mode:

* inclusive — the menu price already contains the VAT, so subtotal IS gross.
  A 14.00 order came out as net 14.00, VAT 2.33, gross 14.00: revenue
  overstated by exactly the tax.
* exclusive — VAT is never added to ``order.total`` anywhere in the app, so
  ``total`` is net plus delivery, not gross.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select


async def _order(
    db_session, restaurant, *, mode: str, subtotal: str, vat: str, total: str, num: str
):
    from app.ordering.models import Customer, Order

    cust = await db_session.scalar(
        select(Customer).where(Customer.restaurant_id == restaurant.id)
    )
    if cust is None:
        cust = Customer(restaurant_id=restaurant.id, phone="+971500007777", name="AE")
        db_session.add(cust)
        await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number=num,
        status="confirmed",
        subtotal=Decimal(subtotal),
        total=Decimal(total),
        vat_rate=Decimal("0.20"),
        vat_amount_aed=Decimal(vat),
        tax_pricing_mode=mode,
    )
    db_session.add(order)
    await db_session.commit()


async def _export(db_session, restaurant, fmt="json"):
    from app.compliance.accountant_export import build_accountant_export

    today = date.today()
    return await build_accountant_export(
        db_session,
        restaurant=restaurant,
        start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=1),
        format=fmt,
    )


@pytest.mark.anyio
async def test_inclusive_net_excludes_the_tax(db_session, restaurant):
    # A 14.00 inclusive bill at 20%: 11.67 net + 2.33 VAT = 14.00 gross.
    await _order(
        db_session,
        restaurant,
        mode="inclusive",
        subtotal="14.00",
        vat="2.33",
        total="14.00",
        num="AE-INC-1",
    )
    summary = (await _export(db_session, restaurant))["summary"]

    assert summary["net_total_aed"] == "11.67"
    assert summary["vat_total_aed"] == "2.33"
    assert summary["gross_total_aed"] == "14.00"
    assert Decimal(summary["net_total_aed"]) + Decimal(summary["vat_total_aed"]) == Decimal(
        summary["gross_total_aed"]
    )


@pytest.mark.anyio
async def test_exclusive_gross_includes_the_tax(db_session, restaurant):
    # A 20.00 exclusive bill at 20%: 20.00 net + 4.00 VAT = 24.00 gross, even
    # though order.total stops at 20.00.
    await _order(
        db_session,
        restaurant,
        mode="exclusive",
        subtotal="20.00",
        vat="4.00",
        total="20.00",
        num="AE-EXC-1",
    )
    summary = (await _export(db_session, restaurant))["summary"]

    assert summary["net_total_aed"] == "20.00"
    assert summary["gross_total_aed"] == "24.00"
    assert Decimal(summary["net_total_aed"]) + Decimal(summary["vat_total_aed"]) == Decimal(
        summary["gross_total_aed"]
    )


@pytest.mark.anyio
async def test_each_row_reconciles_too(db_session, restaurant):
    await _order(
        db_session,
        restaurant,
        mode="inclusive",
        subtotal="14.00",
        vat="2.33",
        total="14.00",
        num="AE-ROW-1",
    )
    row = (await _export(db_session, restaurant))["orders"][0]

    assert Decimal(row["net_aed"]) + Decimal(row["vat_amount_aed"]) == Decimal(row["gross_aed"])
    # The raw order figures stay available for tying a line back to a bill.
    assert row["subtotal_aed"] == "14.00"
    assert row["total_aed"] == "14.00"


@pytest.mark.anyio
async def test_csv_carries_net_and_gross(db_session, restaurant):
    await _order(
        db_session,
        restaurant,
        mode="inclusive",
        subtotal="14.00",
        vat="2.33",
        total="14.00",
        num="AE-CSV-1",
    )
    csv_text = (await _export(db_session, restaurant, fmt="csv"))["csv"]

    header = csv_text.splitlines()[0]
    assert "net_aed" in header
    assert "gross_aed" in header
    assert "11.67" in csv_text
