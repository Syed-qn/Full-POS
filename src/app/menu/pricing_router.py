from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.menu.models import Dish
from app.menu.pricing import create_price_rule, resolve_dish_price
from app.menu.pricing_schemas import EffectivePriceOut, PriceRuleIn, PriceRuleOut

router = APIRouter(prefix="/api/v1", tags=["menu-pricing"])


async def _load_dish(dish_id: int, restaurant: Restaurant, session: AsyncSession) -> Dish:
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    return dish


@router.post(
    "/dishes/{dish_id}/price-rules",
    response_model=PriceRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_price_rule_endpoint(
    dish_id: int,
    body: PriceRuleIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _load_dish(dish_id, restaurant, session)
    rule = await create_price_rule(
        session,
        restaurant_id=restaurant.id,
        dish_id=dish_id,
        rule_type=body.rule_type,
        price_aed=body.price_aed,
        start_time=body.start_time,
        end_time=body.end_time,
        days_of_week=body.days_of_week,
        channel=body.channel,
    )
    await session.commit()
    return rule


@router.get("/dishes/{dish_id}/effective-price", response_model=EffectivePriceOut)
async def get_effective_price_endpoint(
    dish_id: int,
    channel: str | None = Query(default=None),
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _load_dish(dish_id, restaurant, session)
    price = await resolve_dish_price(
        session, dish_id=dish_id, at=datetime.now(timezone.utc), channel=channel
    )
    return EffectivePriceOut(dish_id=dish_id, price_aed=price, channel=channel)
