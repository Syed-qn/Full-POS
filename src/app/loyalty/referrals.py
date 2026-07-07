"""Referral rewards — a NEW, non-overlapping addition to the tier/earn loyalty
system in :mod:`app.loyalty.service`.

A customer gets a short shareable code (:class:`ReferralCode`). When a NEW
customer redeems it, ``Customer.referred_by_customer_id`` is set once (never
changed after) and BOTH the referrer and the new customer are credited a
fixed wallet bonus via :mod:`app.wallet.service` (reuses the existing wallet
ledger — no separate points counter).
"""
from __future__ import annotations

import secrets
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.loyalty.models import ReferralCode
from app.ordering.models import Customer

REFERRAL_BONUS_AED = Decimal("10.00")
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # unambiguous, matches coupons style
_CODE_LENGTH = 6
_MAX_ATTEMPTS = 10


class ReferralError(ValueError):
    """Raised on invalid redeem (unknown code, already-referred customer)."""


def _random_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


async def generate_referral_code(
    session: AsyncSession, *, restaurant_id: int, customer_id: int
) -> ReferralCode:
    """Mint a short unique-per-tenant referral code for a customer. Idempotent
    in spirit: if the customer already has a code, return it rather than
    minting a duplicate. Caller commits."""
    existing = await session.scalar(
        select(ReferralCode).where(
            ReferralCode.restaurant_id == restaurant_id,
            ReferralCode.customer_id == customer_id,
        )
    )
    if existing is not None:
        return existing

    code = _random_code()
    for _ in range(_MAX_ATTEMPTS):
        clash = await session.scalar(
            select(ReferralCode).where(
                ReferralCode.restaurant_id == restaurant_id, ReferralCode.code == code
            )
        )
        if clash is None:
            break
        code = _random_code()
    else:
        raise ReferralError("could not generate a unique referral code")

    row = ReferralCode(restaurant_id=restaurant_id, customer_id=customer_id, code=code)
    session.add(row)
    await session.flush()
    await record_audit(
        session, actor="system", restaurant_id=restaurant_id,
        entity="referral_code", entity_id=str(row.id), action="generated",
        before=None, after={"customer_id": customer_id, "code": code},
    )
    return row


async def redeem_referral(
    session: AsyncSession, *, restaurant_id: int, code: str, new_customer_id: int
) -> dict:
    """Validate + redeem a referral code for a new customer. Sets
    ``referred_by_customer_id`` once and credits both wallets. Raises
    ``ReferralError`` on an unknown code or an already-referred customer.
    Caller commits.
    """
    code_row = await session.scalar(
        select(ReferralCode).where(
            ReferralCode.restaurant_id == restaurant_id, ReferralCode.code == code
        )
    )
    if code_row is None:
        raise ReferralError(f"unknown referral code {code!r}")

    new_customer = await session.get(Customer, new_customer_id)
    if new_customer is None or new_customer.restaurant_id != restaurant_id:
        raise ReferralError(f"unknown customer {new_customer_id}")
    if code_row.customer_id == new_customer_id:
        raise ReferralError("a customer cannot redeem their own referral code")
    if new_customer.referred_by_customer_id is not None:
        raise ReferralError(f"customer {new_customer_id} has already been referred")

    new_customer.referred_by_customer_id = code_row.customer_id
    await session.flush()

    from app.wallet import service as wallet

    await wallet.credit(
        session, restaurant_id=restaurant_id, customer_id=code_row.customer_id,
        amount=REFERRAL_BONUS_AED,
        idempotency_key=f"referral:{code}:{new_customer_id}:referrer",
        type="promo_credit", reason_note=f"referral bonus (referred customer {new_customer_id})",
        created_by="system",
    )
    await wallet.credit(
        session, restaurant_id=restaurant_id, customer_id=new_customer_id,
        amount=REFERRAL_BONUS_AED,
        idempotency_key=f"referral:{code}:{new_customer_id}:new",
        type="promo_credit", reason_note=f"referral bonus (used code {code})",
        created_by="system",
    )
    await record_audit(
        session, actor="system", restaurant_id=restaurant_id,
        entity="customer", entity_id=str(new_customer_id), action="referral_redeemed",
        before={"referred_by_customer_id": None},
        after={"referred_by_customer_id": code_row.customer_id, "code": code},
    )
    return {
        "referrer_customer_id": code_row.customer_id,
        "new_customer_id": new_customer_id,
        "bonus_aed": REFERRAL_BONUS_AED,
    }
