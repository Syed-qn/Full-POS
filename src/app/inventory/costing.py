from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import DishIngredient, Ingredient


async def dish_cost(session: AsyncSession, *, dish_id: int) -> Decimal:
    recipe_rows = (await session.scalars(
        select(DishIngredient).where(DishIngredient.dish_id == dish_id)
    )).all()
    if not recipe_rows:
        return Decimal("0.0000")

    ingredient_ids = [r.ingredient_id for r in recipe_rows]
    ingredients = (await session.scalars(
        select(Ingredient).where(Ingredient.id.in_(ingredient_ids))
    )).all()
    cost_by_id = {i.id: i.cost_per_unit_aed for i in ingredients}

    total = Decimal("0.0000")
    for recipe in recipe_rows:
        total += recipe.quantity_per_dish * cost_by_id.get(recipe.ingredient_id, Decimal("0.0000"))
    return total
