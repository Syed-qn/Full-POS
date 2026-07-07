from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import DishIngredient, Ingredient, WasteLog
from app.ordering.models import OrderItem


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
