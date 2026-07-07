from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.giftcards.schemas import GiftCardPurchaseIn
from app.giftcards.service import get_balance, purchase_gift_card
from app.identity.deps import current_restaurant

router = APIRouter(prefix="/api/v1/gift-cards", tags=["gift-cards"])


@router.post("/purchase", status_code=status.HTTP_201_CREATED)
async def purchase(
    body: GiftCardPurchaseIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    entry = await purchase_gift_card(
        session, restaurant_id=restaurant.id, recipient_phone=body.recipient_phone,
        amount_aed=body.amount_aed, purchase_reference=body.purchase_reference, created_by="manager",
    )
    await session.commit()
    return {"id": entry.id, "amount_aed": str(entry.amount_aed)}


@router.get("/balance/{phone}")
async def balance_endpoint(
    phone: str,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    bal = await get_balance(session, restaurant_id=restaurant.id, phone=phone)
    return {"phone": phone, "balance_aed": str(bal)}
