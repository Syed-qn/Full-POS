from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.inventory.models import DishIngredient, Ingredient
from app.inventory.schemas import (
    AnomalyCheckIn,
    AnomalyCheckOut,
    BatchIn,
    BatchOut,
    CostIn,
    IngredientIn,
    IngredientOut,
    LowStockAlertOut,
    RecipeLinkIn,
    ReorderSuggestionOut,
    RestockIn,
    StockAdjustmentIn,
    StockAdjustmentOut,
    StockCountIn,
    StockCountOut,
    SubstituteIn,
    SubstituteOut,
    WasteIn,
    VendorPriceComparisonOut,
)
from app.inventory.service import (
    add_batch,
    add_substitute,
    approve_stock_adjustment,
    flag_stock_anomaly,
    list_stock_adjustments,
    list_expiring_soon,
    list_low_stock,
    list_substitutes,
    low_stock_alert,
    record_stock_count,
    record_waste,
    reject_stock_adjustment,
    request_stock_adjustment,
    suggest_reorder_quantities,
    vendor_price_comparison,
)

router = APIRouter(prefix="/api/v1/ingredients", tags=["inventory"])


async def _get_owned_ingredient(session: AsyncSession, *, ingredient_id: int, restaurant_id: int) -> Ingredient:
    ingredient = await session.get(Ingredient, ingredient_id)
    if ingredient is None or ingredient.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="ingredient not found")
    return ingredient


@router.post("", response_model=IngredientOut, status_code=status.HTTP_201_CREATED)
async def create_ingredient(
    body: IngredientIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    ingredient = Ingredient(restaurant_id=restaurant.id, **body.model_dump())
    session.add(ingredient)
    await session.commit()
    await session.refresh(ingredient)
    return ingredient


@router.get("", response_model=list[IngredientOut])
async def list_ingredients(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(Ingredient).where(Ingredient.restaurant_id == restaurant.id)
    )
    return list(rows)


@router.get("/expiring-soon", response_model=list[BatchOut])
async def expiring_soon(
    within_days: int = 3,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_expiring_soon(session, restaurant_id=restaurant.id, within_days=within_days)


@router.get("/low-stock", response_model=list[IngredientOut])
async def low_stock(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_low_stock(session, restaurant_id=restaurant.id)


@router.get("/reorder-suggestions", response_model=list[ReorderSuggestionOut])
async def reorder_suggestions(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await suggest_reorder_quantities(session, restaurant_id=restaurant.id)


@router.get("/stock-adjustments", response_model=list[StockAdjustmentOut])
async def stock_adjustments(
    status: str | None = None,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_stock_adjustments(
        session, restaurant_id=restaurant.id, status=status,
    )


@router.post("/stock-adjustments/{adjustment_id}/approve", response_model=StockAdjustmentOut)
async def approve_stock_adjustment_endpoint(
    adjustment_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        adjustment = await approve_stock_adjustment(
            session, restaurant_id=restaurant.id, adjustment_id=adjustment_id,
            approved_by="manager",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(adjustment)
    return adjustment


@router.post("/stock-adjustments/{adjustment_id}/reject", response_model=StockAdjustmentOut)
async def reject_stock_adjustment_endpoint(
    adjustment_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        adjustment = await reject_stock_adjustment(
            session, restaurant_id=restaurant.id, adjustment_id=adjustment_id,
            approved_by="manager",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(adjustment)
    return adjustment


@router.post("/low-stock-alert", response_model=LowStockAlertOut)
async def send_low_stock_alert(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await low_stock_alert(session, restaurant=restaurant)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return result


@router.post("/{ingredient_id}/recipe-links", status_code=status.HTTP_201_CREATED)
async def link_recipe(
    ingredient_id: int,
    body: RecipeLinkIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    link = DishIngredient(
        dish_id=body.dish_id, ingredient_id=ingredient_id, quantity_per_dish=body.quantity_per_dish,
    )
    session.add(link)
    await session.commit()
    return {"id": link.id, "dish_id": link.dish_id, "ingredient_id": link.ingredient_id}


@router.get("/{ingredient_id}/vendor-price-comparison", response_model=list[VendorPriceComparisonOut])
async def get_vendor_price_comparison(
    ingredient_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await vendor_price_comparison(
            session, restaurant_id=restaurant.id, ingredient_id=ingredient_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{ingredient_id}/stock-adjustments",
    response_model=StockAdjustmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_stock_adjustment(
    ingredient_id: int,
    body: StockAdjustmentIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        adjustment = await request_stock_adjustment(
            session, restaurant_id=restaurant.id, ingredient_id=ingredient_id,
            requested_qty=body.requested_qty, reason=body.reason,
            requested_by=body.requested_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(adjustment)
    return adjustment


@router.post("/{ingredient_id}/waste", response_model=IngredientOut)
async def log_waste(
    ingredient_id: int,
    body: WasteIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    await record_waste(
        session, restaurant_id=restaurant.id, ingredient_id=ingredient_id,
        quantity=body.quantity, reason=body.reason, recorded_by="manager",
    )
    await record_audit(
        session, actor="manager", entity="ingredient", entity_id=str(ingredient_id),
        action="waste", restaurant_id=restaurant.id, before=None,
        after={"quantity": str(body.quantity), "reason": body.reason},
    )
    await session.commit()
    ingredient = await session.get(Ingredient, ingredient_id)
    return ingredient


@router.post("/{ingredient_id}/restock", response_model=IngredientOut)
async def restock(
    ingredient_id: int,
    body: RestockIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    ingredient = await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    ingredient.current_stock += body.quantity
    await record_audit(
        session, actor="manager", entity="ingredient", entity_id=str(ingredient_id),
        action="restock", restaurant_id=restaurant.id, before=None,
        after={"quantity": str(body.quantity)},
    )
    await session.commit()
    await session.refresh(ingredient)
    return ingredient


@router.patch("/{ingredient_id}/cost", response_model=IngredientOut)
async def update_cost(
    ingredient_id: int,
    body: CostIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    ingredient = await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    before = str(ingredient.cost_per_unit_aed)
    ingredient.cost_per_unit_aed = body.cost_per_unit_aed
    await record_audit(
        session, actor="manager", entity="ingredient", entity_id=str(ingredient_id),
        action="cost_update", restaurant_id=restaurant.id,
        before={"cost_per_unit_aed": before}, after={"cost_per_unit_aed": str(body.cost_per_unit_aed)},
    )
    await session.commit()
    await session.refresh(ingredient)
    return ingredient


@router.post("/{ingredient_id}/stock-count", response_model=StockCountOut)
async def stock_count(
    ingredient_id: int,
    body: StockCountIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    result = await record_stock_count(
        session, restaurant_id=restaurant.id, ingredient_id=ingredient_id, counted_qty=body.counted_qty,
    )
    await session.commit()
    return result


@router.post("/{ingredient_id}/batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
async def create_batch(
    ingredient_id: int,
    body: BatchIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    batch = await add_batch(
        session, restaurant_id=restaurant.id, ingredient_id=ingredient_id,
        qty=body.qty, expiry_date=body.expiry_date,
    )
    await session.commit()
    await session.refresh(batch)
    return batch


@router.post("/{ingredient_id}/check-anomaly", response_model=AnomalyCheckOut | None)
async def check_anomaly(
    ingredient_id: int,
    body: AnomalyCheckIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    result = await flag_stock_anomaly(
        session, restaurant_id=restaurant.id, ingredient_id=ingredient_id,
        expected_qty=body.expected_qty, actual_qty=body.actual_qty,
        threshold_pct=body.threshold_pct,
    )
    await session.commit()
    return result


@router.post("/{ingredient_id}/substitutes", response_model=SubstituteOut, status_code=status.HTTP_201_CREATED)
async def create_substitute(
    ingredient_id: int,
    body: SubstituteIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    substitute = await add_substitute(
        session, restaurant_id=restaurant.id, ingredient_id=ingredient_id,
        substitute_ingredient_id=body.substitute_ingredient_id, notes=body.notes,
    )
    await session.commit()
    await session.refresh(substitute)
    return substitute


@router.get("/{ingredient_id}/substitutes", response_model=list[SubstituteOut])
async def get_substitutes(
    ingredient_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_ingredient(session, ingredient_id=ingredient_id, restaurant_id=restaurant.id)
    return await list_substitutes(session, restaurant_id=restaurant.id, ingredient_id=ingredient_id)
