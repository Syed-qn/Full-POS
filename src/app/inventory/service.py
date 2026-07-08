from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.inventory.models import (
    DishIngredient,
    Ingredient,
    IngredientBatch,
    IngredientSubstitute,
    PurchaseOrder,
    PurchaseOrderLine,
    StockAdjustmentRequest,
    Vendor,
    WasteLog,
)
from app.ordering.models import OrderItem

MONEY = Decimal("0.01")


async def deduct_for_order(session: AsyncSession, *, restaurant_id: int, order) -> None:
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    if not items:
        return

    dish_ids = [i.dish_id for i in items]
    recipe_rows = (await session.scalars(
        select(DishIngredient).where(DishIngredient.dish_id.in_(dish_ids))
    )).all()
    if not recipe_rows:
        return

    needed: dict[int, Decimal] = defaultdict(lambda: Decimal("0.000"))
    qty_by_dish = defaultdict(int)
    for item in items:
        qty_by_dish[item.dish_id] += item.qty
    for recipe in recipe_rows:
        needed[recipe.ingredient_id] += recipe.quantity_per_dish * qty_by_dish[recipe.dish_id]

    ingredients = (await session.scalars(
        select(Ingredient).where(Ingredient.id.in_(needed.keys()))
    )).all()
    for ingredient in ingredients:
        ingredient.current_stock -= needed[ingredient.id]
    await session.flush()


async def list_low_stock(session: AsyncSession, *, restaurant_id: int) -> list[Ingredient]:
    rows = (await session.scalars(
        select(Ingredient).where(Ingredient.restaurant_id == restaurant_id)
    )).all()
    return [r for r in rows if r.current_stock <= r.low_stock_threshold]


async def record_waste(
    session: AsyncSession, *, restaurant_id: int, ingredient_id: int,
    quantity: Decimal, reason: str | None, recorded_by: str,
) -> WasteLog:
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is not None and ingredient.restaurant_id == restaurant_id:
        ingredient.current_stock -= quantity
    log = WasteLog(
        restaurant_id=restaurant_id, ingredient_id=ingredient_id, quantity=quantity,
        reason=reason, recorded_by=recorded_by,
    )
    session.add(log)
    await session.flush()
    return log


async def record_stock_count(
    session: AsyncSession, *, restaurant_id: int, ingredient_id: int, counted_qty: Decimal,
) -> dict:
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is None or ingredient.restaurant_id != restaurant_id:
        raise ValueError("ingredient not found")

    previous_stock = ingredient.current_stock
    variance = counted_qty - previous_stock
    ingredient.current_stock = counted_qty

    await record_audit(
        session, actor="manager", entity="ingredient", entity_id=str(ingredient_id),
        action="stock_count", restaurant_id=restaurant_id,
        before={"current_stock": str(previous_stock)},
        after={"current_stock": str(counted_qty), "variance": str(variance)},
    )
    await session.flush()
    return {"variance": variance, "previous_stock": previous_stock, "counted_stock": counted_qty}


async def add_batch(
    session: AsyncSession, *, restaurant_id: int, ingredient_id: int, qty: Decimal, expiry_date: date,
) -> IngredientBatch:
    batch = IngredientBatch(
        restaurant_id=restaurant_id, ingredient_id=ingredient_id, qty=qty,
        expiry_date=expiry_date, received_at=datetime.now(timezone.utc),
    )
    session.add(batch)
    await session.flush()
    return batch


async def list_expiring_soon(
    session: AsyncSession, *, restaurant_id: int, within_days: int = 3,
) -> list[IngredientBatch]:
    cutoff = date.today() + timedelta(days=within_days)
    rows = (await session.scalars(
        select(IngredientBatch).where(
            IngredientBatch.restaurant_id == restaurant_id,
            IngredientBatch.expiry_date <= cutoff,
        )
    )).all()
    return list(rows)


async def suggest_reorder_quantities(session: AsyncSession, *, restaurant_id: int) -> list[dict]:
    """For every ingredient currently at/below its low_stock_threshold, suggest an order
    quantity that restocks it up to its par_level (the target stock level)."""
    rows = (await session.scalars(
        select(Ingredient).where(Ingredient.restaurant_id == restaurant_id)
    )).all()
    suggestions = []
    for ingredient in rows:
        if ingredient.current_stock <= ingredient.low_stock_threshold:
            suggestions.append({
                "ingredient_id": ingredient.id,
                "ingredient_name": ingredient.name,
                "current_stock": ingredient.current_stock,
                "par_level": ingredient.par_level,
                "suggested_order_qty": ingredient.par_level - ingredient.current_stock,
            })
    return suggestions


async def flag_stock_anomaly(
    session: AsyncSession, *, restaurant_id: int, ingredient_id: int,
    expected_qty: Decimal, actual_qty: Decimal, threshold_pct: float = 15.0,
) -> dict | None:
    """Compare expected (recipe-derived) usage against actual deduction and flag possible
    over-portioning / theft-loss if the variance exceeds threshold_pct."""
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is None or ingredient.restaurant_id != restaurant_id:
        raise ValueError("ingredient not found")

    if expected_qty == 0:
        variance_pct = 0.0 if actual_qty == 0 else 100.0
    else:
        variance_pct = float(abs(actual_qty - expected_qty) / expected_qty * 100)

    if variance_pct <= threshold_pct:
        return None

    return {
        "ingredient_id": ingredient_id,
        "expected_qty": expected_qty,
        "actual_qty": actual_qty,
        "variance_pct": variance_pct,
    }


async def add_substitute(
    session: AsyncSession, *, restaurant_id: int, ingredient_id: int,
    substitute_ingredient_id: int, notes: str | None = None,
) -> IngredientSubstitute:
    substitute = IngredientSubstitute(
        restaurant_id=restaurant_id, ingredient_id=ingredient_id,
        substitute_ingredient_id=substitute_ingredient_id, notes=notes,
    )
    session.add(substitute)
    await session.flush()
    return substitute


async def list_substitutes(
    session: AsyncSession, *, restaurant_id: int, ingredient_id: int,
) -> list[IngredientSubstitute]:
    rows = (await session.scalars(
        select(IngredientSubstitute).where(
            IngredientSubstitute.restaurant_id == restaurant_id,
            IngredientSubstitute.ingredient_id == ingredient_id,
        )
    )).all()
    return list(rows)


async def daily_stock_closing(
    session: AsyncSession, *, restaurant_id: int, target_date: date,
) -> list[dict]:
    """Closing stock snapshot per ingredient as of end-of-day target_date.

    Limitation: reflects CURRENT stock, not a true point-in-time historical snapshot,
    since no stock-ledger table exists yet. target_date is accepted for API shape/future
    compatibility but does not affect the result today.
    """
    rows = (await session.scalars(
        select(Ingredient).where(Ingredient.restaurant_id == restaurant_id)
    )).all()
    return [
        {
            "ingredient_id": r.id,
            "ingredient_name": r.name,
            "closing_stock": r.current_stock,
            "unit": r.unit,
        }
        for r in rows
    ]


async def vendor_price_comparison(
    session: AsyncSession, *, restaurant_id: int, ingredient_id: int,
) -> list[dict]:
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is None or ingredient.restaurant_id != restaurant_id:
        raise ValueError("ingredient not found")

    rows = (await session.execute(
        select(PurchaseOrderLine, PurchaseOrder, Vendor)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.po_id)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(
            PurchaseOrder.restaurant_id == restaurant_id,
            PurchaseOrderLine.ingredient_id == ingredient_id,
        )
        .order_by(PurchaseOrderLine.id)
    )).all()

    latest_by_vendor: dict[int, dict] = {}
    for line, po, vendor in rows:
        latest_by_vendor[vendor.id] = {
            "vendor_id": vendor.id,
            "vendor_name": vendor.name,
            "unit_cost_aed": line.unit_cost_aed,
            "purchase_order_id": po.id,
            "purchase_order_line_id": line.id,
        }
    return sorted(latest_by_vendor.values(), key=lambda row: row["vendor_name"])


async def inventory_valuation(session: AsyncSession, *, restaurant_id: int) -> dict:
    ingredients = (await session.scalars(
        select(Ingredient)
        .where(Ingredient.restaurant_id == restaurant_id)
        .order_by(Ingredient.id)
    )).all()

    rows = []
    total = Decimal("0.00")
    for ingredient in ingredients:
        value = (ingredient.current_stock * ingredient.cost_per_unit_aed).quantize(MONEY)
        total += value
        rows.append({
            "ingredient_id": ingredient.id,
            "ingredient_name": ingredient.name,
            "unit": ingredient.unit,
            "current_stock": ingredient.current_stock,
            "cost_per_unit_aed": ingredient.cost_per_unit_aed,
            "value_aed": value,
        })
    return {"total_value_aed": total.quantize(MONEY), "rows": rows}


async def request_stock_adjustment(
    session: AsyncSession, *, restaurant_id: int, ingredient_id: int,
    requested_qty: Decimal, reason: str | None, requested_by: str,
) -> StockAdjustmentRequest:
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is None or ingredient.restaurant_id != restaurant_id:
        raise ValueError("ingredient not found")

    request = StockAdjustmentRequest(
        restaurant_id=restaurant_id,
        ingredient_id=ingredient_id,
        requested_qty=requested_qty,
        previous_qty_snapshot=ingredient.current_stock,
        reason=reason,
        requested_by=requested_by,
    )
    session.add(request)
    await session.flush()
    return request


async def _get_pending_adjustment(
    session: AsyncSession, *, restaurant_id: int, adjustment_id: int,
) -> StockAdjustmentRequest:
    request = await session.get(StockAdjustmentRequest, adjustment_id)
    if request is None or request.restaurant_id != restaurant_id:
        raise ValueError("stock adjustment not found")
    if request.status != "pending":
        raise ValueError("stock adjustment already decided")
    return request


async def approve_stock_adjustment(
    session: AsyncSession, *, restaurant_id: int, adjustment_id: int, approved_by: str,
) -> StockAdjustmentRequest:
    request = await _get_pending_adjustment(
        session, restaurant_id=restaurant_id, adjustment_id=adjustment_id,
    )
    ingredient = await session.get(Ingredient, request.ingredient_id)
    if ingredient is None or ingredient.restaurant_id != restaurant_id:
        raise ValueError("ingredient not found")

    before = ingredient.current_stock
    ingredient.current_stock = request.requested_qty
    request.status = "approved"
    request.approved_by = approved_by
    request.decided_at = datetime.now(timezone.utc)
    await record_audit(
        session,
        actor=approved_by,
        entity="stock_adjustment",
        entity_id=str(request.id),
        action="approve",
        restaurant_id=restaurant_id,
        before={"current_stock": str(before), "status": "pending"},
        after={"current_stock": str(request.requested_qty), "status": "approved"},
    )
    await session.flush()
    return request


async def reject_stock_adjustment(
    session: AsyncSession, *, restaurant_id: int, adjustment_id: int, approved_by: str,
) -> StockAdjustmentRequest:
    request = await _get_pending_adjustment(
        session, restaurant_id=restaurant_id, adjustment_id=adjustment_id,
    )
    request.status = "rejected"
    request.approved_by = approved_by
    request.decided_at = datetime.now(timezone.utc)
    await record_audit(
        session,
        actor=approved_by,
        entity="stock_adjustment",
        entity_id=str(request.id),
        action="reject",
        restaurant_id=restaurant_id,
        before={"status": "pending"},
        after={"status": "rejected"},
    )
    await session.flush()
    return request


async def list_stock_adjustments(
    session: AsyncSession, *, restaurant_id: int, status: str | None = None,
) -> list[StockAdjustmentRequest]:
    query = select(StockAdjustmentRequest).where(
        StockAdjustmentRequest.restaurant_id == restaurant_id,
    )
    if status is not None:
        query = query.where(StockAdjustmentRequest.status == status)
    rows = await session.scalars(query.order_by(StockAdjustmentRequest.id.desc()))
    return list(rows)


async def low_stock_alert(session: AsyncSession, *, restaurant) -> dict:
    low_items = await list_low_stock(session, restaurant_id=restaurant.id)
    if not low_items:
        return {"enqueued": False, "reason": "no_low_stock", "outbox_id": None}
    if not restaurant.phone:
        raise ValueError("restaurant manager phone not configured")

    item_ids = "-".join(str(item.id) for item in sorted(low_items, key=lambda row: row.id))
    today = date.today().isoformat()
    lines = [
        f"- {item.name}: {item.current_stock} {item.unit} (threshold {item.low_stock_threshold})"
        for item in sorted(low_items, key=lambda row: row.name)
    ]
    body = "Low-stock alert:\n" + "\n".join(lines)

    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    msg = await enqueue_message(
        session,
        restaurant_id=restaurant.id,
        to_phone=restaurant.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
        idempotency_key=f"inventory-low-stock:{restaurant.id}:{today}:{item_ids}",
        mirror_rider_conversation=False,
        mirror_customer_conversation=False,
    )
    await session.flush()
    return {"enqueued": True, "reason": None, "outbox_id": msg.id}
