from decimal import Decimal

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.inventory.models import Ingredient
from app.inventory.purchasing import create_purchase_order, create_vendor
from app.inventory.service import (
    approve_stock_adjustment,
    inventory_valuation,
    low_stock_alert,
    reject_stock_adjustment,
    request_stock_adjustment,
    vendor_price_comparison,
)
from app.outbox.models import OutboxMessage


@pytest.mark.anyio
async def test_vendor_price_comparison_uses_latest_po_cost_per_vendor(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id,
        name="Tomato",
        unit="kg",
        current_stock=Decimal("10.000"),
        cost_per_unit_aed=Decimal("2.0000"),
    )
    db_session.add(ingredient)
    await db_session.flush()
    vendor_one = await create_vendor(
        db_session, restaurant_id=restaurant.id, name="Fresh One",
    )
    vendor_two = await create_vendor(
        db_session, restaurant_id=restaurant.id, name="Fresh Two",
    )
    await db_session.flush()
    await create_purchase_order(
        db_session,
        restaurant_id=restaurant.id,
        vendor_id=vendor_one.id,
        lines=[{
            "ingredient_id": ingredient.id,
            "qty_ordered": "1.000",
            "unit_cost_aed": "3.0000",
        }],
    )
    await create_purchase_order(
        db_session,
        restaurant_id=restaurant.id,
        vendor_id=vendor_one.id,
        lines=[{
            "ingredient_id": ingredient.id,
            "qty_ordered": "1.000",
            "unit_cost_aed": "2.5000",
        }],
    )
    await create_purchase_order(
        db_session,
        restaurant_id=restaurant.id,
        vendor_id=vendor_two.id,
        lines=[{
            "ingredient_id": ingredient.id,
            "qty_ordered": "1.000",
            "unit_cost_aed": "2.7500",
        }],
    )
    await db_session.commit()

    rows = await vendor_price_comparison(
        db_session, restaurant_id=restaurant.id, ingredient_id=ingredient.id,
    )

    assert [(row["vendor_name"], row["unit_cost_aed"]) for row in rows] == [
        ("Fresh One", Decimal("2.5000")),
        ("Fresh Two", Decimal("2.7500")),
    ]


@pytest.mark.anyio
async def test_inventory_valuation_returns_rows_and_total(db_session, restaurant):
    db_session.add_all([
        Ingredient(
            restaurant_id=restaurant.id,
            name="Rice",
            unit="kg",
            current_stock=Decimal("5.000"),
            cost_per_unit_aed=Decimal("4.0000"),
        ),
        Ingredient(
            restaurant_id=restaurant.id,
            name="Oil",
            unit="L",
            current_stock=Decimal("2.000"),
            cost_per_unit_aed=Decimal("8.5000"),
        ),
    ])
    await db_session.commit()

    result = await inventory_valuation(db_session, restaurant_id=restaurant.id)

    assert result["total_value_aed"] == Decimal("37.00")
    assert [row["ingredient_name"] for row in result["rows"]] == ["Rice", "Oil"]


@pytest.mark.anyio
async def test_stock_adjustment_requires_approval_before_stock_changes(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id,
        name="Flour",
        unit="kg",
        current_stock=Decimal("9.000"),
        cost_per_unit_aed=Decimal("1.0000"),
    )
    db_session.add(ingredient)
    await db_session.commit()

    request = await request_stock_adjustment(
        db_session,
        restaurant_id=restaurant.id,
        ingredient_id=ingredient.id,
        requested_qty=Decimal("12.000"),
        reason="closing count",
        requested_by="cashier",
    )
    await db_session.commit()
    await db_session.refresh(ingredient)
    assert ingredient.current_stock == Decimal("9.000")
    assert request.status == "pending"

    approved = await approve_stock_adjustment(
        db_session,
        restaurant_id=restaurant.id,
        adjustment_id=request.id,
        approved_by="manager",
    )
    await db_session.commit()
    await db_session.refresh(ingredient)
    assert approved.status == "approved"
    assert ingredient.current_stock == Decimal("12.000")
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity == "stock_adjustment",
            AuditLog.entity_id == str(request.id),
        )
    )
    assert audit is not None


@pytest.mark.anyio
async def test_rejected_stock_adjustment_leaves_stock_unchanged(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id,
        name="Cheese",
        unit="kg",
        current_stock=Decimal("4.000"),
        cost_per_unit_aed=Decimal("10.0000"),
    )
    db_session.add(ingredient)
    await db_session.commit()

    request = await request_stock_adjustment(
        db_session,
        restaurant_id=restaurant.id,
        ingredient_id=ingredient.id,
        requested_qty=Decimal("2.000"),
        reason="bad count",
        requested_by="cashier",
    )
    await db_session.commit()
    rejected = await reject_stock_adjustment(
        db_session,
        restaurant_id=restaurant.id,
        adjustment_id=request.id,
        approved_by="manager",
    )
    await db_session.commit()
    await db_session.refresh(ingredient)
    assert rejected.status == "rejected"
    assert ingredient.current_stock == Decimal("4.000")


@pytest.mark.anyio
async def test_low_stock_alert_enqueues_idempotent_owner_message(db_session, restaurant):
    restaurant.phone = "+971500001111"
    ingredient = Ingredient(
        restaurant_id=restaurant.id,
        name="Mint",
        unit="bunch",
        current_stock=Decimal("1.000"),
        low_stock_threshold=Decimal("2.000"),
        par_level=Decimal("10.000"),
        cost_per_unit_aed=Decimal("0.5000"),
    )
    db_session.add(ingredient)
    await db_session.commit()

    first = await low_stock_alert(db_session, restaurant=restaurant)
    second = await low_stock_alert(db_session, restaurant=restaurant)
    await db_session.commit()

    assert first["enqueued"] is True
    assert second["enqueued"] is True
    rows = (await db_session.scalars(select(OutboxMessage))).all()
    assert len(rows) == 1
    assert "Mint" in rows[0].payload["body"]
