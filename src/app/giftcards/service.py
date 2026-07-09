"""Gift cards: wallet phone credit (legacy purchase) + code/PIN card entity."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.giftcards.models import GiftCard
from app.ordering.models import Customer
from app.payments.mock import MockPaymentProcessor
from app.payments.service import charge_tender
from app.wallet.service import balance, credit, get_or_create_account


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def _gen_code() -> str:
    return secrets.token_hex(4).upper()  # 8-char code


async def purchase_gift_card(
    session: AsyncSession,
    *,
    restaurant_id: int,
    recipient_phone: str,
    amount_aed: Decimal,
    purchase_reference: str,
    created_by: str,
):
    """Legacy path: credit recipient wallet (phone-based gift)."""
    from app.ordering.service import get_or_create_customer

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=recipient_phone
    )
    return await credit(
        session,
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        amount=amount_aed,
        idempotency_key=f"giftcard:{purchase_reference}",
        type="promo_credit",
        reason_note="gift card purchase",
        created_by=created_by,
    )


async def get_balance(session: AsyncSession, *, restaurant_id: int, phone: str) -> Decimal:
    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id, Customer.phone == phone
        )
    )
    if customer is None:
        return Decimal("0.00")
    account = await get_or_create_account(
        session, restaurant_id=restaurant_id, customer_id=customer.id
    )
    return await balance(session, account_id=account.id)


async def issue_gift_card(
    session: AsyncSession,
    *,
    restaurant_id: int,
    amount_aed: Decimal,
    pin: str,
    code: str | None = None,
    issued_by: str = "manager",
    expires_at: datetime | None = None,
    customer_id: int | None = None,
) -> GiftCard:
    if amount_aed <= 0:
        raise ValueError("amount must be positive")
    if not pin or len(pin) < 4:
        raise ValueError("pin must be at least 4 characters")
    card = GiftCard(
        restaurant_id=restaurant_id,
        code=(code or _gen_code()).upper(),
        pin_hash=_hash_pin(pin),
        initial_amount_aed=amount_aed,
        balance_aed=amount_aed,
        status="active",
        issued_by=issued_by,
        expires_at=expires_at,
        customer_id=customer_id,
    )
    session.add(card)
    await session.flush()
    return card


async def lookup_gift_card(
    session: AsyncSession, *, restaurant_id: int, code: str
) -> GiftCard | None:
    return await session.scalar(
        select(GiftCard).where(
            GiftCard.restaurant_id == restaurant_id,
            GiftCard.code == code.upper(),
        )
    )


async def redeem_gift_card(
    session: AsyncSession,
    *,
    restaurant_id: int,
    code: str,
    pin: str,
    order_id: int,
    amount_aed: Decimal,
) -> tuple[GiftCard, object]:
    """Redeem gift card against an order (creates gift_card tender)."""
    card = await lookup_gift_card(session, restaurant_id=restaurant_id, code=code)
    if card is None:
        raise ValueError("gift card not found")
    if card.status != "active":
        raise ValueError(f"gift card is {card.status}")
    if card.pin_hash != _hash_pin(pin):
        raise ValueError("invalid pin")
    if card.expires_at is not None:
        exp = card.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            card.status = "void"
            await session.flush()
            raise ValueError("gift card expired")
    if amount_aed <= 0:
        raise ValueError("amount must be positive")
    if amount_aed > card.balance_aed:
        raise ValueError(f"insufficient gift card balance ({card.balance_aed})")

    card.balance_aed = (card.balance_aed - amount_aed).quantize(Decimal("0.01"))
    if card.balance_aed <= 0:
        card.status = "exhausted"

    txn = await charge_tender(
        session,
        restaurant_id=restaurant_id,
        order_id=order_id,
        tender_type="gift_card",
        amount_aed=amount_aed,
        tip_aed=Decimal("0.00"),
        gateway=MockPaymentProcessor(),
        channel="till",
        reference_meta=card.code,
    )
    await session.flush()
    return card, txn


async def list_gift_cards(
    session: AsyncSession, *, restaurant_id: int, status: str | None = None
) -> list[GiftCard]:
    q = select(GiftCard).where(GiftCard.restaurant_id == restaurant_id)
    if status:
        q = q.where(GiftCard.status == status)
    return list((await session.scalars(q.order_by(GiftCard.id.desc()).limit(100))).all())
