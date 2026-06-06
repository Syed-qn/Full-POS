# src/app/ordering/router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.ordering.models import Order
from app.ordering.schemas import OrderOut

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> Order:
    order = await session.scalar(
        select(Order).where(
            Order.id == order_id,
            Order.restaurant_id == restaurant.id,
        )
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: str | None = None,
    limit: int = 50,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[Order]:
    q = select(Order).where(Order.restaurant_id == restaurant.id)
    if status:
        q = q.where(Order.status == status)
    q = q.order_by(Order.created_at.desc()).limit(limit)
    return list((await session.scalars(q)).all())
