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
    StockAnomalyAlert,
    StockClosingSnapshot,
    StockCountLog,
    StockLocation,
    Vendor,
    WasteLog,
)
from app.ordering.models import OrderItem

MONEY = Decimal("0.01")


async def _deduct_fefo_batches(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ingredient_id: int,
    qty: Decimal,
) -> Decimal:
    """Consume batch qty FEFO (earliest expiry first). Returns remaining unfilled qty."""
    remaining = qty
    batches = (
        await session.scalars(
            select(IngredientBatch)
            .where(
                IngredientBatch.restaurant_id == restaurant_id,
                IngredientBatch.ingredient_id == ingredient_id,
                IngredientBatch.qty_remaining > 0,
            )
            .order_by(IngredientBatch.expiry_date.asc(), IngredientBatch.id.asc())
        )
    ).all()
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.qty_remaining, remaining)
        batch.qty_remaining -= take
        remaining -= take
    return remaining


async def _apply_substitutes(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ingredient_id: int,
    shortfall: Decimal,
    ingredients_by_id: dict[int, Ingredient],
) -> Decimal:
    """Try substitutes when primary is short. Returns still-unfilled amount."""
    if shortfall <= 0:
        return Decimal("0.000")
    subs = (
        await session.scalars(
            select(IngredientSubstitute)
            .where(
                IngredientSubstitute.restaurant_id == restaurant_id,
                IngredientSubstitute.ingredient_id == ingredient_id,
            )
            .order_by(IngredientSubstitute.priority.asc(), IngredientSubstitute.id.asc())
        )
    ).all()
    still = shortfall
    for sub in subs:
        if still <= 0:
            break
        alt = ingredients_by_id.get(sub.substitute_ingredient_id)
        if alt is None:
            alt = await session.get(Ingredient, sub.substitute_ingredient_id)
            if alt is not None:
                ingredients_by_id[alt.id] = alt
        if alt is None or alt.current_stock <= 0:
            continue
        factor = sub.conversion_factor or Decimal("1")
        need_alt = (still * factor).quantize(Decimal("0.001"))
        take = min(alt.current_stock, need_alt)
        alt.current_stock -= take
        await _deduct_fefo_batches(
            session, restaurant_id=restaurant_id, ingredient_id=alt.id, qty=take
        )
        covered = (take / factor).quantize(Decimal("0.001")) if factor else take
        still -= covered
    return max(still, Decimal("0.000"))


async def deduct_for_order(session: AsyncSession, *, restaurant_id: int, order) -> None:
    """Deduct recipe stock with yield, FEFO batch consumption, and auto-substitute."""
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id, OrderItem.cancelled.is_(False))
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
        # Yield < 100% means more raw ingredient is required.
        yield_pct = getattr(recipe, "yield_pct", None) or Decimal("100")
        if yield_pct <= 0:
            yield_pct = Decimal("100")
        factor = Decimal("100") / yield_pct
        needed[recipe.ingredient_id] += (
            recipe.quantity_per_dish * qty_by_dish[recipe.dish_id] * factor
        )

    ingredients = (await session.scalars(
        select(Ingredient).where(Ingredient.id.in_(needed.keys()))
    )).all()
    ingredients_by_id = {i.id: i for i in ingredients}
    oos_ingredient_ids: set[int] = set()
    for ingredient_id, need_qty in needed.items():
        ingredient = ingredients_by_id.get(ingredient_id)
        if ingredient is None:
            continue
        available = ingredient.current_stock
        take = min(available, need_qty)
        ingredient.current_stock -= take
        await _deduct_fefo_batches(
            session, restaurant_id=restaurant_id, ingredient_id=ingredient.id, qty=take
        )
        shortfall = need_qty - take
        if shortfall > 0:
            still = await _apply_substitutes(
                session,
                restaurant_id=restaurant_id,
                ingredient_id=ingredient_id,
                shortfall=shortfall,
                ingredients_by_id=ingredients_by_id,
            )
            if still > 0:
                # Allow negative stock to record theoretical usage gap.
                ingredient.current_stock -= still
        if ingredient.current_stock <= 0:
            oos_ingredient_ids.add(ingredient.id)

    if oos_ingredient_ids:
        from app.menu.models import Dish

        affected_recipes = (
            await session.scalars(
                select(DishIngredient).where(
                    DishIngredient.ingredient_id.in_(oos_ingredient_ids)
                )
            )
        ).all()
        affected_dish_ids = {r.dish_id for r in affected_recipes}
        if affected_dish_ids:
            dishes = (
                await session.scalars(
                    select(Dish).where(
                        Dish.id.in_(affected_dish_ids),
                        Dish.restaurant_id == restaurant_id,
                        Dish.auto_hide_when_oos.is_(True),
                    )
                )
            ).all()
            for d in dishes:
                d.is_available = False
                if d.stock_remaining is not None:
                    d.stock_remaining = 0
    await session.flush()


async def list_low_stock(session: AsyncSession, *, restaurant_id: int) -> list[Ingredient]:
    rows = (await session.scalars(
        select(Ingredient).where(Ingredient.restaurant_id == restaurant_id)
    )).all()
    return [r for r in rows if r.current_stock <= r.low_stock_threshold]


async def record_waste(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ingredient_id: int,
    quantity: Decimal,
    reason: str | None,
    recorded_by: str,
    reason_type: str = "wastage",
    batch_id: int | None = None,
) -> WasteLog:
    from app.inventory.models import WASTE_REASON_TYPES

    rt = (reason_type or "wastage").strip().lower()
    if rt not in WASTE_REASON_TYPES:
        rt = "other"
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is not None and ingredient.restaurant_id == restaurant_id:
        ingredient.current_stock -= quantity
        await _deduct_fefo_batches(
            session, restaurant_id=restaurant_id, ingredient_id=ingredient_id, qty=quantity
        )
    log = WasteLog(
        restaurant_id=restaurant_id,
        ingredient_id=ingredient_id,
        quantity=quantity,
        reason=reason,
        reason_type=rt,
        recorded_by=recorded_by,
        batch_id=batch_id,
    )
    session.add(log)
    if rt in ("theft", "over_portion"):
        session.add(
            StockAnomalyAlert(
                restaurant_id=restaurant_id,
                ingredient_id=ingredient_id,
                alert_type="theft_loss" if rt == "theft" else "over_portion",
                expected_qty=Decimal("0"),
                actual_qty=quantity,
                variance_pct=Decimal("100"),
                message=reason or rt,
            )
        )
    await session.flush()
    return log


async def record_stock_count(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ingredient_id: int,
    counted_qty: Decimal,
    counted_by: str = "manager",
    anomaly_threshold_pct: float = 15.0,
) -> dict:
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is None or ingredient.restaurant_id != restaurant_id:
        raise ValueError("ingredient not found")

    previous_stock = ingredient.current_stock
    variance = counted_qty - previous_stock
    ingredient.current_stock = counted_qty

    session.add(
        StockCountLog(
            restaurant_id=restaurant_id,
            ingredient_id=ingredient_id,
            previous_stock=previous_stock,
            counted_stock=counted_qty,
            variance=variance,
            counted_by=counted_by,
        )
    )

    # Persist count variance alert when large swing
    if previous_stock != 0:
        variance_pct = float(abs(variance) / abs(previous_stock) * 100)
    else:
        variance_pct = 100.0 if variance != 0 else 0.0
    if variance_pct > anomaly_threshold_pct:
        alert_type = "theft_loss" if variance < 0 else "count_variance"
        session.add(
            StockAnomalyAlert(
                restaurant_id=restaurant_id,
                ingredient_id=ingredient_id,
                alert_type=alert_type,
                expected_qty=previous_stock,
                actual_qty=counted_qty,
                variance_pct=Decimal(str(round(variance_pct, 2))),
                message=f"Stock count variance {variance_pct:.1f}%",
            )
        )

    await record_audit(
        session, actor=counted_by, entity="ingredient", entity_id=str(ingredient_id),
        action="stock_count", restaurant_id=restaurant_id,
        before={"current_stock": str(previous_stock)},
        after={"current_stock": str(counted_qty), "variance": str(variance)},
    )
    await session.flush()
    return {
        "variance": variance,
        "previous_stock": previous_stock,
        "counted_stock": counted_qty,
        "variance_pct": variance_pct,
    }


async def add_batch(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ingredient_id: int,
    qty: Decimal,
    expiry_date: date,
    location_id: int | None = None,
    update_stock: bool = True,
) -> IngredientBatch:
    batch = IngredientBatch(
        restaurant_id=restaurant_id,
        ingredient_id=ingredient_id,
        qty=qty,
        qty_remaining=qty,
        expiry_date=expiry_date,
        received_at=datetime.now(timezone.utc),
        location_id=location_id,
    )
    session.add(batch)
    if update_stock:
        ingredient = await session.get(Ingredient, ingredient_id)
        if ingredient is not None and ingredient.restaurant_id == restaurant_id:
            ingredient.current_stock += qty
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
    session: AsyncSession,
    *,
    restaurant_id: int,
    ingredient_id: int,
    expected_qty: Decimal,
    actual_qty: Decimal,
    threshold_pct: float = 15.0,
    persist: bool = True,
) -> dict | None:
    """Compare expected vs actual usage; flag over-portioning / theft-loss."""
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is None or ingredient.restaurant_id != restaurant_id:
        raise ValueError("ingredient not found")

    if expected_qty == 0:
        variance_pct = 0.0 if actual_qty == 0 else 100.0
    else:
        variance_pct = float(abs(actual_qty - expected_qty) / expected_qty * 100)

    if variance_pct <= threshold_pct:
        return None

    alert_type = "over_portion" if actual_qty > expected_qty else "theft_loss"
    result = {
        "ingredient_id": ingredient_id,
        "expected_qty": expected_qty,
        "actual_qty": actual_qty,
        "variance_pct": variance_pct,
        "alert_type": alert_type,
    }
    if persist:
        session.add(
            StockAnomalyAlert(
                restaurant_id=restaurant_id,
                ingredient_id=ingredient_id,
                alert_type=alert_type,
                expected_qty=expected_qty,
                actual_qty=actual_qty,
                variance_pct=Decimal(str(round(variance_pct, 2))),
                message=f"{alert_type}: {variance_pct:.1f}% variance",
            )
        )
        await session.flush()
    return result


async def add_substitute(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ingredient_id: int,
    substitute_ingredient_id: int,
    notes: str | None = None,
    conversion_factor: Decimal = Decimal("1"),
    priority: int = 0,
) -> IngredientSubstitute:
    substitute = IngredientSubstitute(
        restaurant_id=restaurant_id,
        ingredient_id=ingredient_id,
        substitute_ingredient_id=substitute_ingredient_id,
        notes=notes,
        conversion_factor=conversion_factor,
        priority=priority,
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


async def take_stock_closing_snapshot(
    session: AsyncSession, *, restaurant_id: int, target_date: date | None = None,
) -> list[dict]:
    """Persist a true EOD snapshot for every ingredient (idempotent per day)."""
    target = target_date or date.today()
    rows = (
        await session.scalars(
            select(Ingredient).where(Ingredient.restaurant_id == restaurant_id)
        )
    ).all()
    result = []
    for r in rows:
        existing = await session.scalar(
            select(StockClosingSnapshot).where(
                StockClosingSnapshot.restaurant_id == restaurant_id,
                StockClosingSnapshot.ingredient_id == r.id,
                StockClosingSnapshot.closing_date == target,
            )
        )
        val = (r.current_stock * r.cost_per_unit_aed).quantize(MONEY)
        if existing is None:
            snap = StockClosingSnapshot(
                restaurant_id=restaurant_id,
                ingredient_id=r.id,
                closing_date=target,
                closing_stock=r.current_stock,
                unit=r.unit,
                valuation_aed=val,
            )
            session.add(snap)
        else:
            existing.closing_stock = r.current_stock
            existing.unit = r.unit
            existing.valuation_aed = val
        result.append(
            {
                "ingredient_id": r.id,
                "ingredient_name": r.name,
                "closing_stock": r.current_stock,
                "unit": r.unit,
                "valuation_aed": val,
                "closing_date": target.isoformat(),
            }
        )
    await session.flush()
    return result


async def daily_stock_closing(
    session: AsyncSession, *, restaurant_id: int, target_date: date,
) -> list[dict]:
    """Return stored EOD snapshot for target_date; if none, take one now (today)."""
    snaps = (
        await session.scalars(
            select(StockClosingSnapshot).where(
                StockClosingSnapshot.restaurant_id == restaurant_id,
                StockClosingSnapshot.closing_date == target_date,
            )
        )
    ).all()
    if snaps:
        names = {}
        ing_ids = [s.ingredient_id for s in snaps]
        for i in (
            await session.scalars(select(Ingredient).where(Ingredient.id.in_(ing_ids)))
        ).all():
            names[i.id] = i.name
        return [
            {
                "ingredient_id": s.ingredient_id,
                "ingredient_name": names.get(s.ingredient_id, ""),
                "closing_stock": s.closing_stock,
                "unit": s.unit,
                "valuation_aed": s.valuation_aed,
                "closing_date": s.closing_date.isoformat(),
            }
            for s in snaps
        ]
    # No snapshot yet — capture current levels as the closing for that date.
    return await take_stock_closing_snapshot(
        session, restaurant_id=restaurant_id, target_date=target_date
    )


async def stock_variance_report(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """Historical stock-count variance rows."""
    q = select(StockCountLog).where(StockCountLog.restaurant_id == restaurant_id)
    if start_date is not None:
        q = q.where(StockCountLog.created_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date is not None:
        q = q.where(
            StockCountLog.created_at
            < datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        )
    rows = (await session.scalars(q.order_by(StockCountLog.id.desc()).limit(500))).all()
    names = {}
    ids = {r.ingredient_id for r in rows}
    if ids:
        for i in (
            await session.scalars(select(Ingredient).where(Ingredient.id.in_(ids)))
        ).all():
            names[i.id] = i.name
    return [
        {
            "id": r.id,
            "ingredient_id": r.ingredient_id,
            "ingredient_name": names.get(r.ingredient_id, ""),
            "previous_stock": r.previous_stock,
            "counted_stock": r.counted_stock,
            "variance": r.variance,
            "counted_by": r.counted_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def list_anomaly_alerts(
    session: AsyncSession, *, restaurant_id: int, status: str | None = "open"
) -> list[StockAnomalyAlert]:
    q = select(StockAnomalyAlert).where(StockAnomalyAlert.restaurant_id == restaurant_id)
    if status:
        q = q.where(StockAnomalyAlert.status == status)
    return list(
        (await session.scalars(q.order_by(StockAnomalyAlert.id.desc()).limit(200))).all()
    )


async def spoilage_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    rows = (
        await session.scalars(
            select(WasteLog).where(
                WasteLog.restaurant_id == restaurant_id,
                WasteLog.reason_type == "spoilage",
                WasteLog.created_at
                >= datetime.combine(start_date, datetime.min.time()),
                WasteLog.created_at
                < datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
            )
        )
    ).all()
    names: dict[int, str] = {}
    ids = {r.ingredient_id for r in rows}
    if ids:
        for i in (
            await session.scalars(select(Ingredient).where(Ingredient.id.in_(ids)))
        ).all():
            names[i.id] = i.name
    return [
        {
            "id": r.id,
            "ingredient_id": r.ingredient_id,
            "ingredient_name": names.get(r.ingredient_id, ""),
            "quantity": r.quantity,
            "reason": r.reason,
            "reason_type": r.reason_type,
            "recorded_by": r.recorded_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def ensure_default_location(
    session: AsyncSession, *, restaurant_id: int, kitchen_role: str = "branch"
) -> StockLocation:
    code = {"branch": "main", "central": "central", "commissary": "commissary"}.get(
        kitchen_role, "main"
    )
    existing = await session.scalar(
        select(StockLocation).where(
            StockLocation.restaurant_id == restaurant_id, StockLocation.code == code
        )
    )
    if existing:
        return existing
    loc = StockLocation(
        restaurant_id=restaurant_id,
        name={"branch": "Main Store", "central": "Central Kitchen", "commissary": "Commissary"}[
            kitchen_role if kitchen_role in ("branch", "central", "commissary") else "branch"
        ],
        code=code,
        kitchen_role=kitchen_role if kitchen_role in ("branch", "central", "commissary") else "branch",
    )
    session.add(loc)
    await session.flush()
    return loc


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
