from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.modifiers import Modifier, ModifierGroup


async def create_group(
    session: AsyncSession, *, restaurant_id: int, dish_id: int, name: str,
    min_select: int, max_select: int, required: bool,
) -> ModifierGroup:
    group = ModifierGroup(
        restaurant_id=restaurant_id, dish_id=dish_id, name=name,
        min_select=min_select, max_select=max_select, required=required,
    )
    session.add(group)
    await session.flush()
    return group


async def create_modifier(
    session: AsyncSession, *, group_id: int, name: str, price_delta_aed: Decimal,
) -> Modifier:
    modifier = Modifier(group_id=group_id, name=name, price_delta_aed=price_delta_aed)
    session.add(modifier)
    await session.flush()
    return modifier


async def list_groups_for_dish(session: AsyncSession, *, dish_id: int) -> list[ModifierGroup]:
    rows = await session.scalars(
        select(ModifierGroup).where(ModifierGroup.dish_id == dish_id)
    )
    return list(rows)


async def compute_selection_total(
    session: AsyncSession, *, base_price_aed: Decimal, modifier_ids: list[int],
) -> Decimal:
    if not modifier_ids:
        return base_price_aed
    modifiers = (await session.scalars(
        select(Modifier).where(Modifier.id.in_(modifier_ids))
    )).all()
    return base_price_aed + sum((m.price_delta_aed for m in modifiers), Decimal("0.00"))
