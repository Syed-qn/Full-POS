from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.modifiers import Modifier, ModifierGroup


class ForcedModifierError(ValueError):
    """Raised when a required modifier group is not satisfied."""


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


async def validate_forced_modifiers(
    session: AsyncSession,
    *,
    dish_id: int,
    selected_modifier_ids: list[int] | None,
) -> None:
    """Enforce required / min_select / max_select on modifier groups for a dish.

    ``selected_modifier_ids`` is the list of chosen Modifier.id values.
    Raises ForcedModifierError with a human-readable message on violation.
    """
    groups = await list_groups_for_dish(session, dish_id=dish_id)
    if not groups:
        return
    selected = set(selected_modifier_ids or [])
    # Load all modifiers for these groups
    group_ids = [g.id for g in groups]
    mods = (
        await session.scalars(select(Modifier).where(Modifier.group_id.in_(group_ids)))
    ).all()
    by_group: dict[int, list[Modifier]] = {}
    for m in mods:
        by_group.setdefault(m.group_id, []).append(m)

    for group in groups:
        group_mod_ids = {m.id for m in by_group.get(group.id, [])}
        chosen = selected & group_mod_ids
        min_req = group.min_select
        if group.required and min_req < 1:
            min_req = 1
        if len(chosen) < min_req:
            raise ForcedModifierError(
                f"modifier group '{group.name}' requires at least {min_req} selection(s)"
            )
        if group.max_select is not None and len(chosen) > group.max_select:
            raise ForcedModifierError(
                f"modifier group '{group.name}' allows at most {group.max_select} selection(s)"
            )
