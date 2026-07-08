from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.payments.credentials import clear_credentials, get_credentials_status, set_credentials
from app.payments.factory import get_payment_port
from app.payments.models import PaymentTransaction
from app.payments.schemas import (
    ChargeIn,
    CreditNoteIn,
    CredentialsIn,
    DepositIn,
    HouseAccountChargeIn,
    HouseAccountSettleIn,
    RefundIn,
)
from app.payments.service import (
    DuplicateChargeError,
    InsufficientPaymentError,
    PaymentFailedError,
    charge_deposit,
    charge_tender,
    charge_to_house_account,
    enable_house_account,
    issue_credit_note,
    refund_transaction,
    settle_house_account,
    total_paid,
)
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])
# House-account endpoints live under /api/v1/customers (customer-scoped) and
# /api/v1/orders (order-scoped charge) rather than /api/v1/payments, so they
# sit next to the rest of the customer/order surface area the spec calls for.
customers_router = APIRouter(prefix="/api/v1/customers", tags=["payments"])
orders_router = APIRouter(prefix="/api/v1/orders", tags=["payments"])


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
    except DuplicateChargeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@router.post("/{transaction_id}/credit-note", status_code=status.HTTP_201_CREATED)
async def create_credit_note(
    transaction_id: int,
    body: CreditNoteIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    txn = await session.get(PaymentTransaction, transaction_id)
    if txn is None or txn.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail=f"transaction {transaction_id} not found")

    try:
        note = await issue_credit_note(
            session, restaurant_id=restaurant.id, order_id=txn.order_id, transaction_id=txn.id,
            amount_aed=body.amount_aed, reason=body.reason,
        )
    except PaymentFailedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": note.id,
        "credit_note_number": note.credit_note_number,
        "order_id": note.order_id,
        "transaction_id": note.transaction_id,
        "amount_aed": str(note.amount_aed),
        "reason": note.reason,
        "issued_at": note.issued_at.isoformat(),
    }


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


@orders_router.post("/{order_id}/deposit", status_code=status.HTTP_201_CREATED)
async def deposit(
    order_id: int,
    body: DepositIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    gateway = get_payment_port(restaurant)
    try:
        txn = await charge_deposit(
            session, restaurant_id=restaurant.id, order_id=order_id,
            amount_aed=body.amount_aed, gateway=gateway,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateChargeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    await session.commit()
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    return {
        "id": txn.id,
        "status": txn.status,
        "amount_aed": str(txn.amount_aed),
        "deposit_paid_aed": str(order.deposit_paid_aed),
    }


@orders_router.post("/{order_id}/charge-to-house-account")
async def charge_order_to_house_account(
    order_id: int,
    body: HouseAccountChargeIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")

    try:
        balance = await charge_to_house_account(
            session, restaurant_id=restaurant.id, customer_id=order.customer_id,
            order_id=order_id, amount_aed=body.amount_aed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return {"customer_id": order.customer_id, "house_account_balance_aed": str(balance)}


@customers_router.post("/{customer_id}/house-account/enable")
async def enable_house_account_endpoint(
    customer_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        customer = await enable_house_account(
            session, restaurant_id=restaurant.id, customer_id=customer_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"customer_id": customer.id, "house_account_enabled": customer.house_account_enabled}


@customers_router.post("/{customer_id}/house-account/settle")
async def settle_house_account_endpoint(
    customer_id: int,
    body: HouseAccountSettleIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        balance = await settle_house_account(
            session, restaurant_id=restaurant.id, customer_id=customer_id,
            amount_aed=body.amount_aed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"customer_id": customer_id, "house_account_balance_aed": str(balance)}
