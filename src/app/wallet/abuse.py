"""Refund-abuse velocity checks + auto-freeze.

Called after a complaint refund is credited. If a customer exceeds the per-window
refund caps, their wallet is frozen for manager review (blocks further spend).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.wallet import service as wallet
from app.wallet.models import WalletAccount, WalletEntry

_ZERO = Decimal("0.00")


async def refund_velocity(
    session: AsyncSession, *, account_id: int, window_days: int, now: datetime | None = None
) -> dict:
    """Count + sum refund credits to an account within the rolling window."""
    # created_at is stored timezone-naive (UTC); compare naive-to-naive.
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    since = now - timedelta(days=window_days)
    row = (
        await session.execute(
            select(
                func.count(WalletEntry.id),
                func.coalesce(func.sum(WalletEntry.amount_aed), _ZERO),
            ).where(
                WalletEntry.account_id == account_id,
                WalletEntry.type == "refund_credit",
                WalletEntry.created_at >= since,
            )
        )
    ).one()
    return {"count": int(row[0]), "total_aed": Decimal(row[1])}


async def check_and_flag(
    session: AsyncSession, *, restaurant_id: int, customer_id: int, created_by: str = "system"
) -> bool:
    """Freeze the customer's wallet if refund velocity exceeds configured caps.

    Returns True if the account was frozen. No-op if caps are disabled (0) or the
    account is already frozen. Caller commits.
    """
    s = get_settings()
    window = s.wallet_refund_window_days
    max_count = s.wallet_refund_max_count
    max_aed = Decimal(str(s.wallet_refund_max_aed))
    if window <= 0 or (max_count <= 0 and max_aed <= _ZERO):
        return False

    acc = await session.scalar(
        select(WalletAccount).where(
            WalletAccount.restaurant_id == restaurant_id,
            WalletAccount.customer_id == customer_id,
        )
    )
    if acc is None or acc.status == "frozen":
        return False

    v = await refund_velocity(session, account_id=acc.id, window_days=window)
    over = (max_count > 0 and v["count"] > max_count) or (
        max_aed > _ZERO and v["total_aed"] > max_aed
    )
    if not over:
        return False
    await wallet.freeze(
        session, account_id=acc.id, restaurant_id=restaurant_id,
        reason=f"refund velocity: {v['count']} refunds / AED {v['total_aed']} in {window}d",
        created_by=created_by,
    )
    return True
