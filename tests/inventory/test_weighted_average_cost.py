"""Receiving must blend the cost, not overwrite it with the newest invoice.

Setting cost_per_unit_aed to the latest price re-prices every kilo you already
hold at the newest rate. One expensive delivery then inflates the valuation of
stock bought cheap, and every figure derived from cost — valuation, count
variance in dirhams, actual-vs-theoretical — inherits the error.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.inventory.models import Ingredient, PurchaseOrder, PurchaseOrderLine, Vendor
from app.inventory.purchasing import create_grn
from app.inventory.service import inventory_valuation


async def _ingredient(db_session, restaurant, *, stock: str, cost: str) -> Ingredient:
    row = Ingredient(
        restaurant_id=restaurant.id,
        name="Chicken",
        unit="kg",
        current_stock=Decimal(stock),
        low_stock_threshold=Decimal("1.000"),
        cost_per_unit_aed=Decimal(cost),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _po_line(db_session, restaurant, ingredient, *, qty: str, cost: str):
    vendor = Vendor(restaurant_id=restaurant.id, name="Spice Co")
    db_session.add(vendor)
    await db_session.flush()
    po = PurchaseOrder(
        restaurant_id=restaurant.id,
        vendor_id=vendor.id,
        status="ordered",
    )
    db_session.add(po)
    await db_session.flush()
    line = PurchaseOrderLine(
        po_id=po.id,
        ingredient_id=ingredient.id,
        qty_ordered=Decimal(qty),
        unit_cost_aed=Decimal(cost),
    )
    db_session.add(line)
    await db_session.flush()
    return po, line


@pytest.mark.anyio
async def test_receiving_blends_the_cost_instead_of_overwriting_it(db_session, restaurant):
    """10 kg at 20 plus 10 kg at 30 is 25 a kilo, not 30."""
    ingredient = await _ingredient(db_session, restaurant, stock="10.000", cost="20.0000")
    po, line = await _po_line(db_session, restaurant, ingredient, qty="10.000", cost="30.0000")

    await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po.id,
        lines=[{"po_line_id": line.id, "qty_received": Decimal("10.000")}],
        received_by="manager",
    )

    assert ingredient.current_stock == Decimal("20.000")
    assert ingredient.cost_per_unit_aed == Decimal("25.0000"), (
        "the 10 kg already in the fridge did not become more expensive because "
        "the next delivery did"
    )


@pytest.mark.anyio
async def test_valuation_follows_the_blended_cost(db_session, restaurant):
    """The bug is only worth fixing because valuation reads this number."""
    ingredient = await _ingredient(db_session, restaurant, stock="10.000", cost="20.0000")
    po, line = await _po_line(db_session, restaurant, ingredient, qty="10.000", cost="30.0000")

    await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po.id,
        lines=[{"po_line_id": line.id, "qty_received": Decimal("10.000")}],
        received_by="manager",
    )

    report = await inventory_valuation(db_session, restaurant_id=restaurant.id)
    # 20 kg at the blended 25. Latest-cost would have said 600 and overstated
    # the store by 100 dirhams on a single delivery.
    assert Decimal(str(report["total_value_aed"])) == Decimal("500.00")


@pytest.mark.anyio
async def test_first_delivery_into_an_empty_shelf_takes_the_invoice_price(
    db_session, restaurant
):
    """There is nothing to blend with, and averaging against a zero-cost zero
    would drag the new cost to nothing."""
    ingredient = await _ingredient(db_session, restaurant, stock="0.000", cost="0.0000")
    po, line = await _po_line(db_session, restaurant, ingredient, qty="5.000", cost="18.0000")

    await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po.id,
        lines=[{"po_line_id": line.id, "qty_received": Decimal("5.000")}],
        received_by="manager",
    )
    assert ingredient.cost_per_unit_aed == Decimal("18.0000")


@pytest.mark.anyio
async def test_negative_stock_falls_back_to_the_invoice_price(db_session, restaurant):
    """Stock is deliberately allowed to go negative when a recipe outruns the
    shelf. A negative quantity in a weighted average produces a nonsense cost,
    so the delivery price stands on its own."""
    ingredient = await _ingredient(db_session, restaurant, stock="-4.000", cost="20.0000")
    po, line = await _po_line(db_session, restaurant, ingredient, qty="10.000", cost="30.0000")

    await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po.id,
        lines=[{"po_line_id": line.id, "qty_received": Decimal("10.000")}],
        received_by="manager",
    )
    assert ingredient.cost_per_unit_aed == Decimal("30.0000")
    assert ingredient.current_stock == Decimal("6.000")


@pytest.mark.anyio
async def test_each_receipt_blends_onto_the_last(db_session, restaurant):
    """Two deliveries in a row, so the average is not just a one-shot special
    case of the opening figure."""
    ingredient = await _ingredient(db_session, restaurant, stock="0.000", cost="0.0000")
    po, line = await _po_line(db_session, restaurant, ingredient, qty="20.000", cost="10.0000")

    await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po.id,
        lines=[{"po_line_id": line.id, "qty_received": Decimal("10.000")}],
        received_by="manager",
    )
    assert ingredient.cost_per_unit_aed == Decimal("10.0000")

    po2, line2 = await _po_line(db_session, restaurant, ingredient, qty="30.000", cost="20.0000")
    await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po2.id,
        lines=[{"po_line_id": line2.id, "qty_received": Decimal("30.000")}],
        received_by="manager",
    )
    # 10 at 10 plus 30 at 20 = 700 over 40 kg.
    assert ingredient.cost_per_unit_aed == Decimal("17.5000")
    assert ingredient.current_stock == Decimal("40.000")


@pytest.mark.anyio
async def test_the_receipt_line_still_records_what_was_actually_paid(
    db_session, restaurant
):
    """The blended figure belongs on the ingredient. The GRN line is the
    invoice record and must keep the real price, or the audit trail is gone."""
    from app.inventory.models import GoodsReceivedLine

    ingredient = await _ingredient(db_session, restaurant, stock="10.000", cost="20.0000")
    po, line = await _po_line(db_session, restaurant, ingredient, qty="10.000", cost="30.0000")

    await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po.id,
        lines=[{"po_line_id": line.id, "qty_received": Decimal("10.000")}],
        received_by="manager",
    )
    received = await db_session.scalar(
        select(GoodsReceivedLine).where(GoodsReceivedLine.ingredient_id == ingredient.id)
    )
    assert received.unit_cost_aed == Decimal("30.0000")
