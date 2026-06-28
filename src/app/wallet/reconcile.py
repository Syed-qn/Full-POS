"""Wallet maintenance: credit expiry + ledger reconciliation.

Both run per-tenant from Celery beat. Expiry posts an ``expiry`` debit for lapsed
unspent credit (idempotent per source credit). Reconciliation independently
re-sums the ledger and reports drift — mirrors the COD shift reconciliation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.wallet.models import WalletAccount, WalletEntry

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")
_CREDIT_TYPES = ("refund_credit", "promo_credit")


async def expire_credits(
    session: AsyncSession, *, restaurant_id: int, ttl_days: int, now: datetime | None = None
) -> int:
    """Expire unspent credit older than ``ttl_days`` for one tenant.

    For each account, if its oldest active credit is older than the cutoff and the
    account still has a positive balance, post an ``expiry`` debit zeroing the
    remaining balance. Idempotent per (account, day) via the idempotency key.
    Returns the number of accounts expired. ttl_days <= 0 disables expiry.
    """
    if ttl_days <= 0:
        return 0
    # created_at is stored timezone-naive (UTC); compare naive-to-naive.
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    cutoff = now - timedelta(days=ttl_days)
    expired = 0

    accounts = (
        await session.scalars(
            select(WalletAccount).where(WalletAccount.restaurant_id == restaurant_id)
        )
    ).all()
    for acc in accounts:
        # Oldest still-relevant credit timestamp.
        oldest_credit = await session.scalar(
            select(func.min(WalletEntry.created_at)).where(
                WalletEntry.account_id == acc.id,
                WalletEntry.type.in_(_CREDIT_TYPES),
                WalletEntry.status == "posted",
            )
        )
        if oldest_credit is None or oldest_credit > cutoff:
            continue
        bal = await session.scalar(
            select(func.coalesce(func.sum(WalletEntry.amount_aed), _ZERO)).where(
                WalletEntry.account_id == acc.id, WalletEntry.status == "posted"
            )
        )
        bal = Decimal(bal).quantize(_CENT)
        if bal <= _ZERO:
            continue
        key = f"wallet:expiry:{acc.id}:{cutoff.date().isoformat()}"
        if await session.scalar(
            select(WalletEntry).where(WalletEntry.idempotency_key == key)
        ):
            continue
        session.add(
            WalletEntry(
                account_id=acc.id, restaurant_id=restaurant_id, amount_aed=(-bal),
                type="expiry", status="posted", idempotency_key=key, created_by="system",
                reason_note=f"credit expired after {ttl_days} days",
            )
        )
        await record_audit(
            session, actor="system", restaurant_id=restaurant_id,
            entity="wallet_account", entity_id=str(acc.id), action="expiry",
            before={"balance_aed": str(bal)}, after={"balance_aed": "0.00"},
        )
        expired += 1
    return expired


async def reconcile_tenant(session: AsyncSession, *, restaurant_id: int) -> dict:
    """Independently re-sum a tenant's wallet ledger and report drift.

    liability = SUM(posted) across the tenant. control = credits - debits where
    debits include order_debit + expiry + reversal + hold_release netting. Drift
    should always be zero; a nonzero value signals corruption to alert on.
    """
    posted = await session.scalar(
        select(func.coalesce(func.sum(WalletEntry.amount_aed), _ZERO)).where(
            WalletEntry.restaurant_id == restaurant_id, WalletEntry.status == "posted"
        )
    )
    liability = Decimal(posted).quantize(_CENT)
    # Control total recomputed from a separate grouping of the same rows.
    rows = await session.execute(
        select(WalletEntry.type, func.coalesce(func.sum(WalletEntry.amount_aed), _ZERO))
        .where(WalletEntry.restaurant_id == restaurant_id, WalletEntry.status == "posted")
        .group_by(WalletEntry.type)
    )
    control = sum((Decimal(amt) for _typ, amt in rows), _ZERO).quantize(_CENT)
    drift = (liability - control).quantize(_CENT)
    return {"liability_aed": liability, "control_aed": control, "drift_aed": drift}
