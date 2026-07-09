from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import DishIngredient, Ingredient


async def dish_cost(session: AsyncSession, *, dish_id: int) -> Decimal:
    """Theoretical food cost for one dish portion, adjusting for recipe yield.

    If yield_pct is 90, raw usage is quantity_per_dish / 0.90 so cost is higher.
    """
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
        yield_pct = getattr(recipe, "yield_pct", None) or Decimal("100")
        if yield_pct <= 0:
            yield_pct = Decimal("100")
        raw_qty = recipe.quantity_per_dish * (Decimal("100") / yield_pct)
        total += raw_qty * cost_by_id.get(recipe.ingredient_id, Decimal("0.0000"))
    return total
