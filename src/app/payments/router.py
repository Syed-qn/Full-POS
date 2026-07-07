from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.payments.credentials import clear_credentials, get_credentials_status, set_credentials
from app.payments.factory import get_payment_port
from app.payments.schemas import ChargeIn, CredentialsIn, RefundIn
from app.payments.service import (
    InsufficientPaymentError,
    PaymentFailedError,
    charge_tender,
    refund_transaction,
    total_paid,
)
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.post("/charge", status_code=status.HTTP_201_CREATED)
async def charge(
    body: ChargeIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    gateway = get_payment_port(restaurant)
    try:
        txn = await charge_tender(
            session, restaurant_id=restaurant.id, order_id=body.order_id, tender_type=body.tender_type,
            amount_aed=body.amount_aed, tip_aed=body.tip_aed, gateway=gateway,
        )
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    await session.commit()
    total = await total_paid(session, order_id=body.order_id)
    return {
        "id": txn.id, "status": txn.status, "provider": txn.provider,
        "amount_aed": str(txn.amount_aed), "tip_aed": str(txn.tip_aed),
        "order_total_paid_aed": str(total),
    }


@router.post("/{transaction_id}/refund")
async def refund(
    transaction_id: int,
    body: RefundIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    gateway = get_payment_port(restaurant)
    try:
        txn = await refund_transaction(
            session, transaction_id=transaction_id, restaurant_id=restaurant.id,
            amount_aed=body.amount_aed, gateway=gateway,
        )
    except InsufficientPaymentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"id": txn.id, "status": txn.status, "refunded_amount_aed": str(txn.refunded_amount_aed)}


@router.get("/credentials")
async def get_credentials(restaurant=Depends(current_restaurant)):
    return get_credentials_status(restaurant)


@router.put("/credentials")
async def put_credentials(
    body: CredentialsIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await set_credentials(session, restaurant=restaurant, provider=body.provider, secret_key=body.secret_key)
    await session.commit()
    return get_credentials_status(restaurant)


@router.delete("/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credentials(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await clear_credentials(session, restaurant=restaurant)
    await session.commit()
