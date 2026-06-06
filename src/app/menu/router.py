from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.llm.factory import get_menu_extractor
from app.llm.port import MenuExtractor, UploadedFile
from app.menu import service
from app.menu.models import Menu
from app.menu.schemas import MenuOut

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
