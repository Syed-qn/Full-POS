"""Actual vs theoretical food cost for a period.

Theoretical is what the food SHOULD have cost if every portion matched the
recipe: sales mix multiplied by recipe. Actual is what left the store:
opening + purchases - closing. The gap between them is over-portioning, waste,
bad receiving or theft, and it is the number that says where margin goes.

Per-count variance already exists and answers a different question — one
ingredient at one moment. This is a period, across everything, ranked by money.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.inventory.models import (
    DishIngredient,
    Ingredient,
    StockClosingSnapshot,
)
from app.menu.models import Dish, Menu
from app.ordering.models import Customer, Order, OrderItem

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


async def _chicken(db_session, restaurant, *, cost="20.0000") -> Ingredient:
    row = Ingredient(
        restaurant_id=restaurant.id,
        name="Chicken",
        unit="kg",
        current_stock=Decimal("0.000"),
        low_stock_threshold=Decimal("1.000"),
        cost_per_unit_aed=Decimal(cost),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _snapshot(db_session, restaurant, ingredient, *, on: date, qty: str, value: str):
    db_session.add(
        StockClosingSnapshot(
            restaurant_id=restaurant.id,
            ingredient_id=ingredient.id,
            closing_date=on,
            closing_stock=Decimal(qty),
            unit=ingredient.unit,
            valuation_aed=Decimal(value),
        )
    )
    await db_session.flush()


async def _dish_with_recipe(
    db_session, restaurant, ingredient, *, per_dish: str, yield_pct: str = "100.00"
) -> Dish:
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Grilled Chicken",
        name_normalized="grilled chicken",
        price_aed=Decimal("40.00"),
        is_available=True,
    )
    db_session.add(dish)
    await db_session.flush()
    db_session.add(
        DishIngredient(
            dish_id=dish.id,
            ingredient_id=ingredient.id,
            quantity_per_dish=Decimal(per_dish),
            yield_pct=Decimal(yield_pct),
        )
    )
    await db_session.flush()
    return dish


async def _sell(db_session, restaurant, dish, *, qty: int, status="delivered"):
    # Unique per call: customers are unique per (restaurant, phone), and a test
    # that sells three times would otherwise collide on the second.
    customer = Customer(
        restaurant_id=restaurant.id, phone=f"+9715000{qty:03d}{len(status)}", name="Ann"
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number=f"R-{qty}-{status}",
        status=status,
        total=Decimal("40.00") * qty,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=dish.dish_number,
            dish_name=dish.name,
            price_aed=Decimal("40.00"),
            qty=qty,
        )
    )
    await db_session.flush()
    return order


@pytest.mark.anyio
async def test_perfect_portions_leave_no_variance(db_session, restaurant):
    """The control. If the kitchen used exactly the recipe, actual and
    theoretical agree and the report must not invent a gap."""
    from app.inventory.service import actual_vs_theoretical

    chicken = await _chicken(db_session, restaurant)
    dish = await _dish_with_recipe(db_session, restaurant, chicken, per_dish="0.500")
    await _sell(db_session, restaurant, dish, qty=20)  # 20 x 0.5 = 10 kg

    # Opened with 30 kg, bought nothing, closed with 20 kg — used exactly 10.
    await _snapshot(db_session, restaurant, chicken, on=YESTERDAY, qty="30.000", value="600.00")
    await _snapshot(db_session, restaurant, chicken, on=TODAY, qty="20.000", value="400.00")

    report = await actual_vs_theoretical(
        db_session, restaurant_id=restaurant.id, start=TODAY, end=TODAY
    )
    row = report["rows"][0]
    assert row["ingredient_name"] == "Chicken"
    assert Decimal(row["theoretical_qty"]) == Decimal("10.000")
    assert Decimal(row["actual_qty"]) == Decimal("10.000")
    assert Decimal(row["variance_qty"]) == Decimal("0.000")
    assert Decimal(row["variance_value_aed"]) == Decimal("0.00")


@pytest.mark.anyio
async def test_over_portioning_shows_up_as_a_costed_gap(db_session, restaurant):
    """Recipe says 10 kg, 14 left the store. The 4 kg is the leak."""
    from app.inventory.service import actual_vs_theoretical

    chicken = await _chicken(db_session, restaurant)
    dish = await _dish_with_recipe(db_session, restaurant, chicken, per_dish="0.500")
    await _sell(db_session, restaurant, dish, qty=20)

    await _snapshot(db_session, restaurant, chicken, on=YESTERDAY, qty="30.000", value="600.00")
    await _snapshot(db_session, restaurant, chicken, on=TODAY, qty="16.000", value="320.00")

    report = await actual_vs_theoretical(
        db_session, restaurant_id=restaurant.id, start=TODAY, end=TODAY
    )
    row = report["rows"][0]
    assert Decimal(row["theoretical_qty"]) == Decimal("10.000")
    assert Decimal(row["actual_qty"]) == Decimal("14.000")
    assert Decimal(row["variance_qty"]) == Decimal("4.000")
    # The money is what makes it actionable — 4 kg of saffron and 4 kg of
    # onions are not the same problem.
    assert Decimal(row["variance_value_aed"]) == Decimal("80.00")
    assert Decimal(report["variance_value_aed"]) == Decimal("80.00")


@pytest.mark.anyio
async def test_purchases_in_the_period_count_as_stock_that_came_in(db_session, restaurant):
    """Without purchases the sum is opening - closing, which reads a delivery
    as though the kitchen conjured food out of nothing."""
    from app.inventory.purchasing import create_grn
    from app.inventory.models import PurchaseOrder, PurchaseOrderLine, Vendor
    from app.inventory.service import actual_vs_theoretical

    chicken = await _chicken(db_session, restaurant)
    dish = await _dish_with_recipe(db_session, restaurant, chicken, per_dish="0.500")
    await _sell(db_session, restaurant, dish, qty=20)  # theoretical 10 kg

    vendor = Vendor(restaurant_id=restaurant.id, name="Spice Co")
    db_session.add(vendor)
    await db_session.flush()
    po = PurchaseOrder(restaurant_id=restaurant.id, vendor_id=vendor.id, status="ordered")
    db_session.add(po)
    await db_session.flush()
    po_line = PurchaseOrderLine(
        po_id=po.id,
        ingredient_id=chicken.id,
        qty_ordered=Decimal("50.000"),
        unit_cost_aed=Decimal("20.0000"),
    )
    db_session.add(po_line)
    await db_session.flush()
    await create_grn(
        db_session,
        restaurant_id=restaurant.id,
        po_id=po.id,
        lines=[{"po_line_id": po_line.id, "qty_received": Decimal("50.000")}],
        received_by="manager",
    )

    # Opened 30, bought 50, closed 70 — so 10 kg was used, exactly the recipe.
    await _snapshot(db_session, restaurant, chicken, on=YESTERDAY, qty="30.000", value="600.00")
    await _snapshot(db_session, restaurant, chicken, on=TODAY, qty="70.000", value="1400.00")

    report = await actual_vs_theoretical(
        db_session, restaurant_id=restaurant.id, start=TODAY, end=TODAY
    )
    row = report["rows"][0]
    assert Decimal(row["purchased_qty"]) == Decimal("50.000")
    assert Decimal(row["actual_qty"]) == Decimal("10.000")
    assert Decimal(row["variance_qty"]) == Decimal("0.000")


@pytest.mark.anyio
async def test_recipe_yield_is_applied_the_same_way_depletion_applies_it(
    db_session, restaurant
):
    """Theoretical usage must match what deduct_for_order actually takes off
    the shelf, or the report disagrees with the stock it is auditing."""
    from app.inventory.service import actual_vs_theoretical

    chicken = await _chicken(db_session, restaurant)
    # 80% yield: 0.5 kg on the plate needs 0.625 kg raw.
    dish = await _dish_with_recipe(
        db_session, restaurant, chicken, per_dish="0.500", yield_pct="80.00"
    )
    await _sell(db_session, restaurant, dish, qty=20)

    await _snapshot(db_session, restaurant, chicken, on=YESTERDAY, qty="30.000", value="600.00")
    await _snapshot(db_session, restaurant, chicken, on=TODAY, qty="17.500", value="350.00")

    report = await actual_vs_theoretical(
        db_session, restaurant_id=restaurant.id, start=TODAY, end=TODAY
    )
    row = report["rows"][0]
    assert Decimal(row["theoretical_qty"]) == Decimal("12.500")
    assert Decimal(row["variance_qty"]) == Decimal("0.000"), "trim loss is not a variance"


@pytest.mark.anyio
async def test_cancelled_lines_and_unsold_orders_are_not_theoretical_usage(
    db_session, restaurant
):
    """A cancelled item was never cooked. Counting it inflates theoretical and
    makes a healthy kitchen look like it is under-using stock."""
    from sqlalchemy import select

    from app.inventory.service import actual_vs_theoretical

    chicken = await _chicken(db_session, restaurant)
    dish = await _dish_with_recipe(db_session, restaurant, chicken, per_dish="0.500")
    await _sell(db_session, restaurant, dish, qty=20)

    cancelled_order = await _sell(db_session, restaurant, dish, qty=8, status="cancelled")
    # ...and a line cancelled inside an otherwise live order.
    live = await _sell(db_session, restaurant, dish, qty=4, status="delivered")
    item = await db_session.scalar(
        select(OrderItem).where(OrderItem.order_id == live.id)
    )
    item.cancelled = True
    await db_session.flush()
    assert cancelled_order.status == "cancelled"

    await _snapshot(db_session, restaurant, chicken, on=YESTERDAY, qty="30.000", value="600.00")
    await _snapshot(db_session, restaurant, chicken, on=TODAY, qty="20.000", value="400.00")

    report = await actual_vs_theoretical(
        db_session, restaurant_id=restaurant.id, start=TODAY, end=TODAY
    )
    row = report["rows"][0]
    assert Decimal(row["theoretical_qty"]) == Decimal("10.000"), "only the 20 sold count"


@pytest.mark.anyio
async def test_a_missing_opening_count_is_said_out_loud_not_guessed(db_session, restaurant):
    """Without an opening snapshot there is no actual usage to compute. Assuming
    zero would report the entire closing stock as a variance and send someone
    hunting for a theft that never happened."""
    from app.inventory.service import actual_vs_theoretical

    chicken = await _chicken(db_session, restaurant)
    dish = await _dish_with_recipe(db_session, restaurant, chicken, per_dish="0.500")
    await _sell(db_session, restaurant, dish, qty=20)
    await _snapshot(db_session, restaurant, chicken, on=TODAY, qty="20.000", value="400.00")

    report = await actual_vs_theoretical(
        db_session, restaurant_id=restaurant.id, start=TODAY, end=TODAY
    )
    assert report["rows"] == []
    assert chicken.name in report["missing_counts"]
    assert report["complete"] is False


@pytest.mark.anyio
async def test_rows_are_ranked_by_money_not_quantity(db_session, restaurant):
    """2 kg of saffron matters more than 40 kg of onions, and a report sorted
    by quantity buries it."""
    from app.inventory.service import actual_vs_theoretical

    onions = Ingredient(
        restaurant_id=restaurant.id,
        name="Onions",
        unit="kg",
        current_stock=Decimal("0.000"),
        low_stock_threshold=Decimal("1.000"),
        cost_per_unit_aed=Decimal("2.0000"),
    )
    saffron = Ingredient(
        restaurant_id=restaurant.id,
        name="Saffron",
        unit="kg",
        current_stock=Decimal("0.000"),
        low_stock_threshold=Decimal("0.100"),
        cost_per_unit_aed=Decimal("300.0000"),
    )
    db_session.add_all([onions, saffron])
    await db_session.flush()

    # Nothing sold, so every kilo missing is pure variance.
    await _snapshot(db_session, restaurant, onions, on=YESTERDAY, qty="100.000", value="200.00")
    await _snapshot(db_session, restaurant, onions, on=TODAY, qty="60.000", value="120.00")
    await _snapshot(db_session, restaurant, saffron, on=YESTERDAY, qty="5.000", value="1500.00")
    await _snapshot(db_session, restaurant, saffron, on=TODAY, qty="3.000", value="900.00")

    report = await actual_vs_theoretical(
        db_session, restaurant_id=restaurant.id, start=TODAY, end=TODAY
    )
    assert [r["ingredient_name"] for r in report["rows"]] == ["Saffron", "Onions"]
    assert Decimal(report["rows"][0]["variance_value_aed"]) == Decimal("600.00")


@pytest.mark.anyio
async def test_another_restaurant_sees_none_of_it(db_session, restaurant):
    """Food cost variance is exactly what a competitor would want."""
    from app.identity.auth import hash_password
    from app.identity.models import Restaurant
    from app.inventory.service import actual_vs_theoretical

    chicken = await _chicken(db_session, restaurant)
    await _snapshot(db_session, restaurant, chicken, on=YESTERDAY, qty="30.000", value="600.00")
    await _snapshot(db_session, restaurant, chicken, on=TODAY, qty="16.000", value="320.00")

    other = Restaurant(
        name="Someone Else",
        phone="+971466666666",
        password_hash=hash_password("hunter2!"),
        lat=25.2,
        lng=55.2,
    )
    db_session.add(other)
    await db_session.flush()

    theirs = await actual_vs_theoretical(
        db_session, restaurant_id=other.id, start=TODAY, end=TODAY
    )
    assert theirs["rows"] == []
    # Positive control: the owner still gets their own figures, so the empty
    # result above means isolation and not a broken report.
    mine = await actual_vs_theoretical(
        db_session, restaurant_id=restaurant.id, start=TODAY, end=TODAY
    )
    assert Decimal(mine["rows"][0]["variance_value_aed"]) == Decimal("280.00")
