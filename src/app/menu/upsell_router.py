"""Upsell / combo-suggestion REST API — market-basket co-purchase recommendations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.menu.upsell import compute_co_purchase_scores

router = APIRouter(prefix="/api/v1/menu", tags=["menu"])


@router.get("/upsell")
async def get_upsell_suggestions(
    dish_ids: str = Query(..., description="Comma-separated dish IDs currently in the cart"),
    limit: int = 3,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    parsed_ids = [int(part) for part in dish_ids.split(",") if part.strip()]
    return await compute_co_purchase_scores(
        session, restaurant_id=restaurant.id, dish_ids=parsed_ids, limit=limit,
    )
