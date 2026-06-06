from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.llm.factory import get_menu_extractor
from app.llm.port import MenuExtractor, UploadedFile
from app.menu import service
from app.menu.models import Dish, Menu
from app.menu.schemas import DishIn, DishOut, DishPatch, MenuOut
from app.menu.service import MenuIncompleteError

router = APIRouter(prefix="/api/v1", tags=["menu"])


async def _load_menu(
    menu_id: int,
    restaurant: Restaurant,
    session: AsyncSession,
) -> Menu:
    menu = await session.get(Menu, menu_id)
    if menu is None or menu.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "menu not found")
    return menu


@router.post("/menus", response_model=MenuOut, status_code=201)
async def upload_menu(
    files: list[UploadFile],
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
    extractor: MenuExtractor = Depends(get_menu_extractor),
):
    uploaded = [
        UploadedFile(
            filename=f.filename or "file",
            content=await f.read(),
            mime=f.content_type or "application/octet-stream",
        )
        for f in files
    ]
    try:
        return await service.create_menu_from_upload(
            session, restaurant_id=restaurant.id, files=uploaded, extractor=extractor
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"menu extraction failed: {exc}")


@router.get("/menus/{menu_id}", response_model=MenuOut)
async def get_menu(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await _load_menu(menu_id, restaurant, session)


@router.post("/menus/{menu_id}/dishes", response_model=DishOut, status_code=201)
async def add_dish(
    menu_id: int,
    body: DishIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dup = await session.scalar(
        select(Dish).where(Dish.menu_id == menu.id, Dish.dish_number == body.dish_number)
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "dish number already in menu")
    dish = Dish(menu_id=menu.id, restaurant_id=restaurant.id, **body.model_dump())
    session.add(dish)
    await session.flush()
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="added", after=body.model_dump(mode="json"),
    )
    await session.commit()
    await session.refresh(dish)
    return dish


@router.patch("/menus/{menu_id}/dishes/{dish_id}", response_model=DishOut)
async def patch_dish(
    menu_id: int,
    dish_id: int,
    body: DishPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.menu_id != menu.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    changes = body.model_dump(exclude_unset=True)
    if "dish_number" in changes:
        dup = await session.scalar(
            select(Dish).where(
                Dish.menu_id == menu.id,
                Dish.dish_number == changes["dish_number"],
                Dish.id != dish.id,
            )
        )
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "dish number already in menu")
    before = {k: str(getattr(dish, k)) for k in changes}
    for key, value in changes.items():
        setattr(dish, key, value)
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="edited", before=before,
        after={k: str(v) for k, v in changes.items()},
    )
    await session.commit()
    await session.refresh(dish)
    return dish


@router.delete("/menus/{menu_id}/dishes/{dish_id}", status_code=204)
async def delete_dish(
    menu_id: int,
    dish_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.menu_id != menu.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="removed",
        before={"dish_number": dish.dish_number, "name": dish.name},
    )
    await session.delete(dish)
    await session.commit()
    session.expire_all()


@router.post("/menus/{menu_id}/activate", response_model=MenuOut)
async def activate_menu(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    try:
        return await service.activate_menu(session, menu)
    except MenuIncompleteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
