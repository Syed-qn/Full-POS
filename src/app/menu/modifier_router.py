from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.menu.modifier_schemas import ModifierGroupIn, ModifierGroupOut, ModifierIn, ModifierOut
from app.menu.modifier_service import create_group, create_modifier, list_groups_for_dish
from app.menu.modifiers import ModifierGroup

router = APIRouter(prefix="/api/v1", tags=["menu-modifiers"])


@router.post("/dishes/{dish_id}/modifier-groups", response_model=ModifierGroupOut, status_code=status.HTTP_201_CREATED)
async def create_modifier_group(
    dish_id: int,
    body: ModifierGroupIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    group = await create_group(
        session, restaurant_id=restaurant.id, dish_id=dish_id, name=body.name,
        min_select=body.min_select, max_select=body.max_select, required=body.required,
    )
    await session.commit()
    return group


@router.get("/dishes/{dish_id}/modifier-groups", response_model=list[ModifierGroupOut])
async def list_modifier_groups(
    dish_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_groups_for_dish(session, dish_id=dish_id)


@router.post("/modifier-groups/{group_id}/modifiers", response_model=ModifierOut, status_code=status.HTTP_201_CREATED)
async def create_modifier_endpoint(
    group_id: int,
    body: ModifierIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    group = await session.get(ModifierGroup, group_id)
    if group is None or group.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="modifier group not found")
    modifier = await create_modifier(session, group_id=group_id, name=body.name, price_delta_aed=body.price_delta_aed)
    await session.commit()
    return modifier
