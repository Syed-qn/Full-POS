"""Order payment composition — coupon + wallet credit against an order's COD.

Kept separate from ordering.service so the order FSM stays untouched: these are
guarded hooks (no-op when no coupon/wallet is involved), each idempotent on
order-scoped keys so FSM replays/retries never double-apply.

Flow:
  confirm   -> apply_at_confirm: redeem coupon (cuts total), hold wallet credit.
  delivered -> capture_on_deliver: settle the wallet hold into a real debit.
  cancelled -> release_on_cancel: return the held wallet credit.

COD due at the door = order.total - order.wallet_applied_aed.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from app.coupons import service as coupons
from app.coupons.service import CouponError
from app.wallet import service as wallet

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.ordering.models import Order

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")


def cod_due_aed(order: "Order") -> Decimal:
    """Cash the rider collects at the door = order total minus wallet credit applied.

    The wallet portion is settled separately (capture on delivery), so collecting
    only the remainder in cash prevents double-charging the customer.
    """
    due = (Decimal(order.total) - Decimal(order.wallet_applied_aed or _ZERO)).quantize(_CENT)
    return max(due, _ZERO)


async def apply_at_confirm(
    session: "AsyncSession",
    *,
    order: "Order",
    coupon_code: str | None = None,
    use_wallet: bool = False,
    created_by: str = "customer",
) -> dict:
    """Apply an optional coupon then optional wallet credit to ``order``.

    Coupon is applied first (reduces the order total). Wallet then covers up to
    the remaining total. Persists ``order.coupon_id`` / ``order.wallet_applied_aed``
    and recomputes ``order.total``. Idempotent per order. Caller commits.

    Returns {"coupon_discount_aed", "wallet_applied_aed", "cod_due_aed"}.
    """
    coupon_discount = _ZERO
    if coupon_code:
        try:
            redemption = await coupons.validate_and_redeem(
                session,
                restaurant_id=order.restaurant_id,
                code=coupon_code,
                customer_id=order.customer_id,
                order_id=order.id,
                order_subtotal_aed=order.subtotal,
                idempotency_key=f"order:{order.id}:coupon",
            )
            coupon_discount = redemption.discount_applied_aed
            # Reduce the order total by the coupon (never below the delivery fee).
            new_total = (order.total - coupon_discount)
            order.total = max(new_total, order.delivery_fee_aed).quantize(_CENT)
        except CouponError:
            # Re-raise so the caller can surface the reason to the customer.
            raise

    if use_wallet and order.wallet_applied_aed <= _ZERO:
        acc = await wallet.get_or_create_account(
            session, restaurant_id=order.restaurant_id, customer_id=order.customer_id
        )
        avail = await wallet.available(session, account_id=acc.id)
        to_apply = min(avail, order.total).quantize(_CENT)
        if to_apply > _ZERO:
            await wallet.hold(
                session,
                account_id=acc.id,
                restaurant_id=order.restaurant_id,
                amount=to_apply,
                order_id=order.id,
                idempotency_key=f"order:{order.id}:wallethold",
                created_by=created_by,
            )
            order.wallet_applied_aed = to_apply

    await session.flush()
    cod_due = (order.total - order.wallet_applied_aed).quantize(_CENT)
    return {
        "coupon_discount_aed": coupon_discount,
        "wallet_applied_aed": order.wallet_applied_aed,
        "cod_due_aed": cod_due,
    }


async def capture_on_deliver(
    session: "AsyncSession", *, order: "Order", created_by: str = "system"
) -> None:
    """Settle the order's wallet hold on delivery. No-op if no wallet was applied."""
    if order.wallet_applied_aed <= _ZERO:
        return
    acc = await wallet.get_or_create_account(
        session, restaurant_id=order.restaurant_id, customer_id=order.customer_id
    )
    await wallet.capture(
        session,
        account_id=acc.id,
        restaurant_id=order.restaurant_id,
        order_id=order.id,
        idempotency_key=f"order:{order.id}:walletcapture",
        created_by=created_by,
    )


async def release_on_cancel(
    session: "AsyncSession", *, order: "Order", created_by: str = "system"
) -> None:
    """Return the held wallet credit on cancellation. No-op if no wallet applied."""
    if order.wallet_applied_aed <= _ZERO:
        return
    acc = await wallet.get_or_create_account(
        session, restaurant_id=order.restaurant_id, customer_id=order.customer_id
    )
    await wallet.release(
        session,
        account_id=acc.id,
        restaurant_id=order.restaurant_id,
        order_id=order.id,
        idempotency_key=f"order:{order.id}:walletrelease",
        created_by=created_by,
    )
    order.wallet_applied_aed = _ZERO
