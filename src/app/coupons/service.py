"""Late-delivery apology coupon service (spec §4.5).

``issue_coupon`` mints a single-use coupon with a unique code, a 30-day default
expiry, ``status="issued"``, linked to the order/customer that caused it.
``redeem_coupon`` validates the code is issued + unredeemed + unexpired and marks
it ``redeemed`` with the redeeming order. Every mint/redeem is audited in the
caller's transaction (caller commits).
"""

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.coupons.models import Coupon, CouponRedemption

DEFAULT_VALIDITY_DAYS = 30
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")

# Codes a customer must type — drop visually ambiguous chars (0/O, 1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class CouponError(ValueError):
    """Raised on invalid issue/redeem (unknown, expired, already redeemed)."""


def _generate_code(restaurant_id: int) -> str:
    return f"SORRY-{restaurant_id}-{secrets.token_hex(3).upper()}"


def generate_code(prefix: str = "SAVE", length: int = 10) -> str:
    """High-entropy, human-typeable coupon code. ``length`` random chars from a
    31-symbol unambiguous alphabet (~5 bits each → ~50 bits at length 10).
    Uniqueness is enforced per tenant by the caller against (restaurant_id, code).
    """
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))
    return f"{prefix}-{body}"


async def issue_coupon(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    order_id: int,
    discount_aed: Decimal,
    validity_days: int = DEFAULT_VALIDITY_DAYS,
) -> Coupon:
    """Mint a single-use apology coupon with a unique code. Caller commits."""
    code = _generate_code(restaurant_id)
    while (
        await session.scalar(select(Coupon).where(Coupon.code == code)) is not None
    ):
        code = _generate_code(restaurant_id)
    coupon = Coupon(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_id=order_id,
        code=code,
        discount_aed=discount_aed,
        status="issued",
        expires_at=datetime.now(timezone.utc) + timedelta(days=validity_days),
    )
    session.add(coupon)
    await session.flush()
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="coupon",
        entity_id=str(coupon.id),
        action="issued",
        before=None,
        after={"code": code, "discount_aed": str(discount_aed)},
    )
    return coupon


async def redeem_coupon(
    session: AsyncSession, *, restaurant_id: int, code: str, order_id: int
) -> Coupon:
    """Validate + redeem a coupon. Raises CouponError on unknown/expired/already-redeemed."""
    coupon = await session.scalar(
        select(Coupon).where(
            Coupon.restaurant_id == restaurant_id, Coupon.code == code
        )
    )
    if coupon is None:
        raise CouponError(f"unknown coupon {code}")
    if coupon.status != "issued":
        raise CouponError(f"coupon {code} is {coupon.status}, not redeemable")
    now = datetime.now(timezone.utc)
    if coupon.expires_at is not None and coupon.expires_at < now:
        coupon.status = "expired"
        raise CouponError(f"coupon {code} expired")
    coupon.status = "redeemed"
    coupon.redeemed_at = now
    coupon.redeemed_on_order_id = order_id
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="coupon",
        entity_id=str(coupon.id),
        action="redeemed",
        before={"status": "issued"},
        after={"status": "redeemed", "order_id": order_id},
    )
    return coupon


_REDEEMABLE_STATUSES = {"active", "issued"}


async def create_coupon(
    session: AsyncSession,
    *,
    restaurant_id: int,
    discount_type: str = "fixed",
    discount_value: Decimal,
    kind: str = "multi_use",
    min_order_aed: Decimal = _ZERO,
    max_discount_aed: Decimal | None = None,
    applies_to: str = "whole_order",
    per_customer_limit: int | None = None,
    total_redemption_limit: int | None = None,
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
    code: str | None = None,
    created_by: str,
) -> Coupon:
    """Create a campaign coupon with a unique (per-tenant) code. Caller commits."""
    if discount_type not in ("fixed", "percent"):
        raise CouponError(f"invalid discount_type {discount_type!r}")
    if discount_value <= _ZERO:
        raise CouponError("discount_value must be positive")
    if discount_type == "percent" and discount_value > Decimal("100"):
        raise CouponError("percent discount cannot exceed 100")

    code = code or generate_code()
    while await session.scalar(
        select(Coupon).where(Coupon.restaurant_id == restaurant_id, Coupon.code == code)
    ) is not None:
        code = generate_code()

    coupon = Coupon(
        restaurant_id=restaurant_id,
        code=code,
        kind=kind,
        discount_type=discount_type,
        discount_aed=discount_value.quantize(_CENT) if discount_type == "fixed" else None,
        percent=discount_value.quantize(_CENT) if discount_type == "percent" else None,
        max_discount_aed=max_discount_aed,
        min_order_aed=min_order_aed.quantize(_CENT),
        applies_to=applies_to,
        per_customer_limit=per_customer_limit,
        total_redemption_limit=total_redemption_limit,
        status="active",
        valid_from=valid_from,
        expires_at=expires_at,
        created_by=created_by,
    )
    session.add(coupon)
    await session.flush()
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="coupon",
        entity_id=str(coupon.id),
        action="created",
        before=None,
        after={"code": code, "discount_type": discount_type, "value": str(discount_value)},
    )
    return coupon


async def pause_coupon(
    session: AsyncSession, *, restaurant_id: int, code: str, created_by: str
) -> Coupon:
    """Kill-switch: pause a coupon so it can no longer be redeemed. Caller commits."""
    coupon = await session.scalar(
        select(Coupon).where(Coupon.restaurant_id == restaurant_id, Coupon.code == code)
    )
    if coupon is None:
        raise CouponError(f"unknown coupon {code}")
    before = {"status": coupon.status}
    coupon.status = "paused"
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="coupon",
        entity_id=str(coupon.id),
        action="paused",
        before=before,
        after={"status": "paused"},
    )
    return coupon


def _compute_discount(coupon: Coupon, order_subtotal_aed: Decimal) -> Decimal:
    if coupon.discount_type == "percent":
        raw = (order_subtotal_aed * (coupon.percent or _ZERO) / Decimal("100")).quantize(_CENT)
        if coupon.max_discount_aed is not None:
            raw = min(raw, coupon.max_discount_aed)
    else:
        raw = coupon.discount_aed or _ZERO
    # Never discount more than the order is worth.
    return min(raw, order_subtotal_aed).quantize(_CENT)


async def validate_and_redeem(
    session: AsyncSession,
    *,
    restaurant_id: int,
    code: str,
    customer_id: int,
    order_id: int,
    order_subtotal_aed: Decimal,
    idempotency_key: str,
) -> CouponRedemption:
    """Validate + atomically redeem a campaign coupon. Idempotent + dup-proof.

    The redemption row's UNIQUE(idempotency_key) plus the FOR UPDATE row-lock and
    count checks make concurrent/replayed double-redemption impossible.
    Raises CouponError on any validation failure. Caller commits.
    """
    existing = await session.scalar(
        select(CouponRedemption).where(
            CouponRedemption.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return existing

    coupon = await session.scalar(
        select(Coupon)
        .where(Coupon.restaurant_id == restaurant_id, Coupon.code == code)
        .with_for_update()
    )
    if coupon is None:
        raise CouponError(f"unknown coupon {code}")
    if coupon.status not in _REDEEMABLE_STATUSES:
        raise CouponError(f"coupon {code} is {coupon.status}, not redeemable")

    now = datetime.now(timezone.utc)
    if coupon.valid_from is not None and now < coupon.valid_from:
        raise CouponError(f"coupon {code} is not yet valid")
    if coupon.expires_at is not None and now > coupon.expires_at:
        coupon.status = "expired"
        raise CouponError(f"coupon {code} expired")
    if order_subtotal_aed < coupon.min_order_aed:
        raise CouponError(
            f"order subtotal {order_subtotal_aed} below minimum {coupon.min_order_aed}"
        )

    total_used = await session.scalar(
        select(func.count(CouponRedemption.id)).where(
            CouponRedemption.coupon_id == coupon.id
        )
    )
    if coupon.kind == "single_use" and total_used >= 1:
        raise CouponError(f"coupon {code} already used")
    if coupon.total_redemption_limit is not None and total_used >= coupon.total_redemption_limit:
        coupon.status = "exhausted"
        raise CouponError(f"coupon {code} redemption limit reached")
    if coupon.per_customer_limit is not None:
        used_by_customer = await session.scalar(
            select(func.count(CouponRedemption.id)).where(
                CouponRedemption.coupon_id == coupon.id,
                CouponRedemption.customer_id == customer_id,
            )
        )
        if used_by_customer >= coupon.per_customer_limit:
            raise CouponError(f"coupon {code} per-customer limit reached")

    discount = _compute_discount(coupon, order_subtotal_aed)
    redemption = CouponRedemption(
        coupon_id=coupon.id,
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_id=order_id,
        discount_applied_aed=discount,
        idempotency_key=idempotency_key,
    )
    session.add(redemption)
    if coupon.kind == "single_use":
        # The CouponRedemption ledger row is the source of truth for which order
        # used this coupon; the legacy redeemed_on_order_id FK is left for the
        # apology flow only (avoids an orders FK dependency here).
        coupon.status = "redeemed"
        coupon.redeemed_at = now
    elif coupon.total_redemption_limit is not None and (total_used + 1) >= coupon.total_redemption_limit:
        coupon.status = "exhausted"
    await session.flush()
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="coupon_redemption",
        entity_id=str(redemption.id),
        action="redeemed",
        before=None,
        after={"code": code, "discount_aed": str(discount), "order_id": order_id},
    )
    return redemption
