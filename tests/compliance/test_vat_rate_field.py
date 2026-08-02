"""The VAT rate is settable, and it is the rate orders are actually charged at.

The dashboard printed the rate as read-only text with no field to change it, so
a restaurant was stuck on the 5% default and could not zero-rate anything. These
pin down the round trip the new field relies on: percentage in, rate stored,
rate applied to a confirmed order.
"""

from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_vat_rate_round_trips(client, auth_headers):
    # The form sends 0 / 100 style fractions, not percentages.
    patch = await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={"default_vat_rate": 0.0, "tax_pricing_mode": "inclusive"},
    )
    assert patch.status_code == 200, patch.text
    assert Decimal(patch.json()["default_vat_rate"]) == Decimal("0")

    back = await client.get("/api/v1/compliance/tax-settings", headers=auth_headers)
    assert Decimal(back.json()["default_vat_rate"]) == Decimal("0")
    assert back.json()["tax_pricing_mode"] == "inclusive"

    restored = await client.patch(
        "/api/v1/compliance/tax-settings",
        headers=auth_headers,
        json={"default_vat_rate": 0.05},
    )
    assert Decimal(restored.json()["default_vat_rate"]) == Decimal("0.05")


@pytest.mark.anyio
async def test_saved_rate_is_what_an_order_is_charged(db_session, restaurant):
    # Proves the field is not cosmetic: whatever is stored here is what
    # apply_order_vat_from_settings stamps onto the order at confirm time.
    from app.ordering.tax import apply_vat
    from app.compliance.tax_settings import merge_tax_settings, tax_settings

    merge_tax_settings(restaurant, {"default_vat_rate": 0.09, "tax_pricing_mode": "exclusive"})
    cfg = tax_settings(restaurant.settings)

    class _Order:
        subtotal = Decimal("100.00")
        vat_rate = None
        vat_amount_aed = None

    order = _Order()
    apply_vat(order, cfg["default_vat_rate"], pricing_mode=cfg["tax_pricing_mode"])
    assert order.vat_rate == Decimal("0.09")
    assert order.vat_amount_aed == Decimal("9.00")


@pytest.mark.anyio
async def test_inclusive_mode_extracts_vat_instead_of_adding_it(db_session, restaurant):
    # The setting a restaurant is most likely to get wrong: exclusive turns a
    # 20.00 menu price into 21.00 at the till, inclusive keeps it at 20.00.
    from app.ordering.tax import apply_vat

    class _Order:
        subtotal = Decimal("20.00")
        vat_rate = None
        vat_amount_aed = None

    exclusive = _Order()
    apply_vat(exclusive, Decimal("0.05"), pricing_mode="exclusive")
    assert exclusive.vat_amount_aed == Decimal("1.00")  # 20.00 + 1.00 = 21.00

    inclusive = _Order()
    apply_vat(inclusive, Decimal("0.05"), pricing_mode="inclusive")
    assert inclusive.vat_amount_aed == Decimal("0.95")  # 19.05 food + 0.95 tax
