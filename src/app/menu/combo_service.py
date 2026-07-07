from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.menu.combos import Combo, ComboItem
from app.menu.models import Dish


async def create_combo(
    session: AsyncSession, *, restaurant_id: int, menu_id: int, name: str,
    price_aed: Decimal, dish_ids: list[int],
) -> Combo:
    combo = Combo(
        restaurant_id=restaurant_id, menu_id=menu_id, name=name,
        price_aed=price_aed, is_available=True,
    )
    for dish_id in dish_ids:
        combo.items.append(ComboItem(dish_id=dish_id, qty=1))
    session.add(combo)
    await session.flush()
    return combo


async def add_combo_item(
    session: AsyncSession, *, combo_id: int, dish_id: int, qty: int = 1,
) -> ComboItem:
    item = ComboItem(combo_id=combo_id, dish_id=dish_id, qty=qty)
    session.add(item)
    await session.flush()
    return item


async def list_combos(session: AsyncSession, *, restaurant_id: int) -> list[Combo]:
    rows = await session.scalars(
        select(Combo)
        .where(Combo.restaurant_id == restaurant_id)
        .options(selectinload(Combo.items))
    )
    return list(rows)


async def combo_component_value(session: AsyncSession, *, combo_id: int) -> Decimal:
    items = (await session.scalars(
        select(ComboItem).where(ComboItem.combo_id == combo_id)
    )).all()
    if not items:
        return Decimal("0.00")
    dish_ids = [item.dish_id for item in items]
    dishes = (await session.scalars(
        select(Dish).where(Dish.id.in_(dish_ids))
    )).all()
    price_by_dish_id = {dish.id: dish.price_aed for dish in dishes}
    total = Decimal("0.00")
    for item in items:
        total += price_by_dish_id[item.dish_id] * item.qty
    return total
