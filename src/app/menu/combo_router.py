from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.menu.combo_schemas import ComboIn, ComboOut
from app.menu.combo_service import create_combo, list_combos
from app.menu.service import get_active_menu

router = APIRouter(prefix="/api/v1", tags=["menu-combos"])


@router.post("/combos", response_model=ComboOut, status_code=status.HTTP_201_CREATED)
async def create_combo_endpoint(
    body: ComboIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await get_active_menu(session, restaurant.id)
    if menu is None:
        raise HTTPException(status_code=400, detail="restaurant has no active menu")
    combo = await create_combo(
        session, restaurant_id=restaurant.id, menu_id=menu.id, name=body.name,
        price_aed=body.price_aed, dish_ids=body.dish_ids,
    )
    await session.commit()
    return ComboOut.from_combo(combo)


@router.get("/combos", response_model=list[ComboOut])
async def list_combos_endpoint(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    combos = await list_combos(session, restaurant_id=restaurant.id)
    return [ComboOut.from_combo(combo) for combo in combos]
