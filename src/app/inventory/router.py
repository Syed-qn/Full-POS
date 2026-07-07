from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.inventory.models import DishIngredient, Ingredient
from app.inventory.schemas import (
    BatchIn,
    BatchOut,
    CostIn,
    IngredientIn,
    IngredientOut,
    RecipeLinkIn,
    RestockIn,
    StockCountIn,
    StockCountOut,
    WasteIn,
)
from app.inventory.service import add_batch, list_expiring_soon, list_low_stock, record_stock_count, record_waste

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
