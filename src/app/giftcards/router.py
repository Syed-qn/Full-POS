from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.giftcards.schemas import GiftCardIssueIn, GiftCardPurchaseIn, GiftCardRedeemIn
from app.giftcards.service import (
    get_balance,
    issue_gift_card,
    list_gift_cards,
    lookup_gift_card,
    purchase_gift_card,
    redeem_gift_card,
)
from app.identity.deps import current_restaurant
from app.payments.service import DuplicateChargeError, PaymentFailedError

router = APIRouter(prefix="/api/v1/gift-cards", tags=["gift-cards"])


@router.post("/purchase", status_code=status.HTTP_201_CREATED)
async def purchase(
    body: GiftCardPurchaseIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    entry = await purchase_gift_card(
        session,
        restaurant_id=restaurant.id,
        recipient_phone=body.recipient_phone,
        amount_aed=body.amount_aed,
        purchase_reference=body.purchase_reference,
        created_by="manager",
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


@router.post("/issue", status_code=status.HTTP_201_CREATED)
async def issue(
    body: GiftCardIssueIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        card = await issue_gift_card(
            session,
            restaurant_id=restaurant.id,
            amount_aed=body.amount_aed,
            pin=body.pin,
            code=body.code,
            customer_id=body.customer_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": card.id,
        "code": card.code,
        "balance_aed": str(card.balance_aed),
        "status": card.status,
    }


@router.get("")
async def list_cards(
    status_filter: str | None = Query(default=None, alias="status"),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_gift_cards(
        session, restaurant_id=restaurant.id, status=status_filter
    )
    return [
        {
            "id": r.id,
            "code": r.code,
            "balance_aed": str(r.balance_aed),
            "initial_amount_aed": str(r.initial_amount_aed),
            "status": r.status,
        }
        for r in rows
    ]


@router.get("/{code}")
async def get_card(
    code: str,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    card = await lookup_gift_card(session, restaurant_id=restaurant.id, code=code)
    if card is None:
        raise HTTPException(status_code=404, detail="gift card not found")
    return {
        "id": card.id,
        "code": card.code,
        "balance_aed": str(card.balance_aed),
        "status": card.status,
    }


@router.post("/redeem", status_code=status.HTTP_201_CREATED)
async def redeem(
    body: GiftCardRedeemIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        card, txn = await redeem_gift_card(
            session,
            restaurant_id=restaurant.id,
            code=body.code,
            pin=body.pin,
            order_id=body.order_id,
            amount_aed=body.amount_aed,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg else 422
        raise HTTPException(status_code=code, detail=msg) from exc
    except DuplicateChargeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    await session.commit()
    return {
        "gift_card_id": card.id,
        "code": card.code,
        "balance_aed": str(card.balance_aed),
        "status": card.status,
        "transaction_id": txn.id,
        "amount_aed": str(txn.amount_aed),
    }
