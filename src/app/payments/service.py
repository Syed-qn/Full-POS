from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.models import PaymentTransaction
from app.payments.port import PaymentPort

_GATEWAY_TENDERS = {"card", "apple_pay", "google_pay"}


class InsufficientPaymentError(Exception):
    pass


class PaymentFailedError(Exception):
    pass


async def charge_tender(
    session: AsyncSession, *, restaurant_id: int, order_id: int, tender_type: str,
    amount_aed: Decimal, tip_aed: Decimal, gateway: PaymentPort,
) -> PaymentTransaction:
    txn = PaymentTransaction(
        restaurant_id=restaurant_id, order_id=order_id, tender_type=tender_type,
        amount_aed=amount_aed, tip_aed=tip_aed, status="pending",
    )
    if tender_type in _GATEWAY_TENDERS:
        result = await gateway.charge(
            amount_aed=amount_aed + tip_aed, tender_type=tender_type, reference=f"order:{order_id}",
        )
        txn.provider = "stripe" if type(gateway).__name__ != "MockPaymentProcessor" else "mock"
        if not result.success:
            txn.status = "failed"
            session.add(txn)
            await session.flush()
            raise PaymentFailedError(result.error or "payment failed")
        txn.provider_charge_id = result.provider_charge_id
        txn.status = "succeeded"
    else:
        # cash / wallet — no external gateway call, settled immediately.
        txn.provider = tender_type
        txn.status = "succeeded"
    session.add(txn)
    await session.flush()
    return txn


async def total_paid(session: AsyncSession, *, order_id: int) -> Decimal:
    val = await session.scalar(
        select(func.coalesce(func.sum(PaymentTransaction.amount_aed - PaymentTransaction.refunded_amount_aed), Decimal("0.00")))
        .where(PaymentTransaction.order_id == order_id, PaymentTransaction.status.in_(("succeeded", "refunded")))
    )
    return Decimal(val)


async def refund_transaction(
    session: AsyncSession, *, transaction_id: int, restaurant_id: int, amount_aed: Decimal, gateway: PaymentPort,
) -> PaymentTransaction:
    txn = await session.get(PaymentTransaction, transaction_id)
    if txn is None or txn.restaurant_id != restaurant_id:
        raise ValueError(f"transaction {transaction_id} not found")
    remaining = txn.amount_aed - txn.refunded_amount_aed
    if amount_aed > remaining:
        raise InsufficientPaymentError(f"cannot refund {amount_aed}, only {remaining} available")

    if txn.tender_type in _GATEWAY_TENDERS and txn.provider_charge_id:
        result = await gateway.refund(provider_charge_id=txn.provider_charge_id, amount_aed=amount_aed)
        if not result.success:
            raise PaymentFailedError(result.error or "refund failed")

    txn.refunded_amount_aed += amount_aed
    txn.status = "refunded" if txn.refunded_amount_aed >= txn.amount_aed else "partially_refunded"
    await session.flush()
    return txn
