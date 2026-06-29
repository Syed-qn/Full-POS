"""Coupon management endpoints (manager JWT, tenant-scoped).

Campaign coupon CRUD-lite: create, list, pause (kill-switch). Redemption happens
inside the order flow (see ordering.service), not here.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.coupons import service as coupon_service
from app.coupons.models import Coupon
from app.coupons.schemas import CouponCreateIn, CouponIssueIn, CouponOut
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.ordering.models import Customer

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


@router.post("/issue", response_model=CouponOut, status_code=201)
async def issue_coupon_to_customer(
    body: CouponIssueIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CouponOut:
    """Issue a single-use coupon to a specific customer (e.g. from the chat).
    Returns the coupon incl. its code so the manager can share it."""
    cust = await session.scalar(
        select(Customer).where(
            Customer.id == body.customer_id, Customer.restaurant_id == restaurant.id
        )
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="customer not found")
    coupon = await coupon_service.issue_coupon(
        session,
        restaurant_id=restaurant.id,
        customer_id=body.customer_id,
        order_id=None,
        discount_aed=body.discount_aed,
        validity_days=body.validity_days,
    )
    # Notify the customer (window-aware: session text inside 24h, else template).
    from app.whatsapp.templates import notify_customer

    await notify_customer(
        session,
        restaurant_id=restaurant.id,
        phone=cust.phone,
        session_text=(
            f"Here's a coupon for you: {coupon.code} — AED {body.discount_aed} "
            f"off your next order. 🎁"
        ),
        template_key="coupon_issued",
        variables=[restaurant.name, coupon.code, str(body.discount_aed)],
        idempotency_key=f"coupon:{coupon.id}:issued",
    )
    await session.commit()
    return CouponOut.model_validate(coupon)


@router.get("", response_model=list[CouponOut])
async def list_coupons(
    phone: str | None = None,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[CouponOut]:
    """List coupons. No phone → campaign (multi-use) coupons. With phone → coupons
    issued to the customer(s) matching that phone (e.g. apology/targeted)."""
    if phone:
        cust_ids = (
            await session.scalars(
                select(Customer.id).where(
                    Customer.restaurant_id == restaurant.id,
                    Customer.phone.ilike(f"%{phone.strip()}%"),
                )
            )
        ).all()
        if not cust_ids:
            return []
        rows = await session.scalars(
            select(Coupon)
            .where(
                Coupon.restaurant_id == restaurant.id,
                Coupon.customer_id.in_(cust_ids),
            )
            .order_by(Coupon.id.desc())
        )
    else:
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
