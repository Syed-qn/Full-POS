from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.menu.categories import create_category, delete_category, list_categories, rename_category

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


class CategoryIn(BaseModel):
    name: str
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: str


class CategoryOut(BaseModel):
    id: int
    name: str
    sort_order: int

    model_config = {"from_attributes": True}


@router.post("", response_model=CategoryOut, status_code=201)
async def create_category_endpoint(
    body: CategoryIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        cat = await create_category(
            session, restaurant_id=restaurant.id, name=body.name, sort_order=body.sort_order
        )
        await session.commit()
        return cat
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("", response_model=list[CategoryOut])
async def list_categories_endpoint(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_categories(session, restaurant_id=restaurant.id)


@router.patch("/{category_id}", response_model=CategoryOut)
async def rename_category_endpoint(
    category_id: int,
    body: CategoryPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        cat = await rename_category(
            session, restaurant_id=restaurant.id, category_id=category_id, name=body.name
        )
        await session.commit()
        return cat
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{category_id}", status_code=204)
async def delete_category_endpoint(
    category_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        await delete_category(session, restaurant_id=restaurant.id, category_id=category_id)
        await session.commit()
        return Response(status_code=204)
    except ValueError as exc:
        code = status.HTTP_409_CONFLICT if "reference" in str(exc) else status.HTTP_404_NOT_FOUND
        raise HTTPException(code, str(exc)) from exc
