"""Coupon management endpoints (manager JWT, tenant-scoped).

Campaign coupon CRUD-lite: create, list, pause (kill-switch). Redemption happens
inside the order flow (see ordering.service), not here.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coupons import service as coupon_service
from app.coupons.models import Coupon
from app.coupons.schemas import CouponCreateIn, CouponOut
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant

router = APIRouter(prefix="/api/v1/coupons", tags=["coupons"])


@router.post("", response_model=CouponOut, status_code=201)
async def create_coupon(
    body: CouponCreateIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CouponOut:
    try:
        coupon = await coupon_service.create_coupon(
            session,
            restaurant_id=restaurant.id,
            discount_type=body.discount_type,
            discount_value=body.discount_value,
            kind=body.kind,
            min_order_aed=body.min_order_aed,
            max_discount_aed=body.max_discount_aed,
            applies_to=body.applies_to,
            per_customer_limit=body.per_customer_limit,
            total_redemption_limit=body.total_redemption_limit,
            valid_from=body.valid_from,
            expires_at=body.expires_at,
            code=body.code,
            created_by=f"mgr:{restaurant.id}",
        )
    except coupon_service.CouponError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await session.commit()
    return CouponOut.model_validate(coupon)


@router.get("", response_model=list[CouponOut])
async def list_coupons(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[CouponOut]:
    rows = await session.scalars(
        select(Coupon)
        .where(Coupon.restaurant_id == restaurant.id, Coupon.kind == "multi_use")
        .order_by(Coupon.id.desc())
    )
    return [CouponOut.model_validate(r) for r in rows]


@router.post("/{code}/pause", response_model=CouponOut)
async def pause_coupon(
    code: str,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CouponOut:
    try:
        coupon = await coupon_service.pause_coupon(
            session, restaurant_id=restaurant.id, code=code, created_by=f"mgr:{restaurant.id}"
        )
    except coupon_service.CouponError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await session.commit()
    return CouponOut.model_validate(coupon)
