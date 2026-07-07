"""Referral rewards endpoints (manager JWT, tenant-scoped)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.loyalty import referrals as referral_service
from app.loyalty.referrals import ReferralError
from app.loyalty.schemas import ReferralCodeOut, ReferralRedeemIn, ReferralRedeemOut
from app.ordering.models import Customer

router = APIRouter(prefix="/api/v1", tags=["referrals"])


async def _tenant_customer(session: AsyncSession, restaurant_id: int, customer_id: int) -> Customer:
    cust = await session.scalar(
        select(Customer).where(
            Customer.id == customer_id, Customer.restaurant_id == restaurant_id
        )
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return cust


@router.post("/customers/{customer_id}/referral-code", response_model=ReferralCodeOut, status_code=201)
async def create_referral_code(
    customer_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> ReferralCodeOut:
    await _tenant_customer(session, restaurant.id, customer_id)
    code_row = await referral_service.generate_referral_code(
        session, restaurant_id=restaurant.id, customer_id=customer_id
    )
    await session.commit()
    return ReferralCodeOut(customer_id=code_row.customer_id, code=code_row.code)


@router.post("/referrals/redeem", response_model=ReferralRedeemOut)
async def redeem_referral_code(
    body: ReferralRedeemIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> ReferralRedeemOut:
    try:
        result = await referral_service.redeem_referral(
            session, restaurant_id=restaurant.id, code=body.code,
            new_customer_id=body.new_customer_id,
        )
    except ReferralError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await session.commit()
    return ReferralRedeemOut(**result)
