"""Wallet service — the ONLY place wallet value moves.

All balances are derived from the append-only ``WalletEntry`` ledger. Every
value-moving call is idempotent on its ``idempotency_key`` and writes an audit
row in the caller's transaction (the caller commits — this module never commits).

Spend model (bank authorize/capture):
- ``hold``    : a negative ``held`` entry. Reduces *available*, not *balance*.
- ``capture`` : flips the order's hold to a posted ``order_debit`` (balance drops).
- ``release`` : flips the hold to posted and adds a ``+`` hold_release that nets it
                to zero (balance unchanged, available restored).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.wallet.errors import AccountFrozen, InsufficientFunds, WalletError
from app.wallet.models import WalletAccount, WalletEntry

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")


def _q(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(_CENT)


async def get_or_create_account(
    session: AsyncSession, *, restaurant_id: int, customer_id: int
) -> WalletAccount:
    """Idempotent: ON CONFLICT DO NOTHING then SELECT. Tenant-scoped by construction."""
    stmt = (
        pg_insert(WalletAccount)
        .values(restaurant_id=restaurant_id, customer_id=customer_id, status="active")
        .on_conflict_do_nothing(constraint="uq_wallet_accounts_restaurant_customer")
    )
    await session.execute(stmt)
    return await session.scalar(
        select(WalletAccount).where(
            WalletAccount.restaurant_id == restaurant_id,
            WalletAccount.customer_id == customer_id,
        )
    )


async def balance(session: AsyncSession, *, account_id: int) -> Decimal:
    """Posted balance = SUM(amount_aed WHERE status='posted')."""
    val = await session.scalar(
        select(func.coalesce(func.sum(WalletEntry.amount_aed), _ZERO)).where(
            WalletEntry.account_id == account_id, WalletEntry.status == "posted"
        )
    )
    return _q(val)


async def available(session: AsyncSession, *, account_id: int) -> Decimal:
    """Available = posted balance + active holds (holds are stored negative)."""
    held = await session.scalar(
        select(func.coalesce(func.sum(WalletEntry.amount_aed), _ZERO)).where(
            WalletEntry.account_id == account_id, WalletEntry.status == "held"
        )
    )
    return _q(await balance(session, account_id=account_id) + Decimal(held))


async def _existing_by_key(
    session: AsyncSession, idempotency_key: str
) -> WalletEntry | None:
    return await session.scalar(
        select(WalletEntry).where(WalletEntry.idempotency_key == idempotency_key)
    )


async def _account(session: AsyncSession, account_id: int) -> WalletAccount:
    acc = await session.get(WalletAccount, account_id)
    if acc is None:
        raise WalletError(f"wallet account {account_id} not found")
    return acc


async def _order_hold(
    session: AsyncSession, account_id: int, order_id: int
) -> WalletEntry | None:
    return await session.scalar(
        select(WalletEntry).where(
            WalletEntry.account_id == account_id,
            WalletEntry.order_id == order_id,
            WalletEntry.type == "hold",
            WalletEntry.status == "held",
        )
    )


async def credit(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    amount: Decimal,
    idempotency_key: str,
    type: str = "refund_credit",
    ticket_id: int | None = None,
    reason_note: str | None = None,
    created_by: str,
) -> WalletEntry:
    """Add posted credit (refund/promo). Idempotent. Caller commits."""
    if amount <= _ZERO:
        raise WalletError("credit amount must be positive")
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    acc = await get_or_create_account(
        session, restaurant_id=restaurant_id, customer_id=customer_id
    )
    entry = WalletEntry(
        account_id=acc.id,
        restaurant_id=restaurant_id,
        amount_aed=_q(amount),
        type=type,
        status="posted",
        idempotency_key=idempotency_key,
        ticket_id=ticket_id,
        reason_note=reason_note,
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="wallet_entry",
        entity_id=str(entry.id),
        action="credit",
        before=None,
        after={"amount_aed": str(_q(amount)), "type": type, "ticket_id": ticket_id},
    )
    return entry


async def hold(
    session: AsyncSession,
    *,
    account_id: int,
    restaurant_id: int,
    amount: Decimal,
    order_id: int,
    idempotency_key: str,
    created_by: str,
) -> WalletEntry:
    """Authorize a spend: reserve ``amount`` against the order. Idempotent.

    Raises InsufficientFunds if available < amount, AccountFrozen if frozen.
    """
    if amount <= _ZERO:
        raise WalletError("hold amount must be positive")
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    acc = await _account(session, account_id)
    if acc.status == "frozen":
        raise AccountFrozen(f"wallet account {account_id} is frozen")
    # Serialize concurrent holds against the same balance.
    await session.execute(
        select(WalletAccount.id).where(WalletAccount.id == account_id).with_for_update()
    )
    avail = await available(session, account_id=account_id)
    if amount > avail:
        raise InsufficientFunds(f"available {avail} < requested {amount}")
    entry = WalletEntry(
        account_id=account_id,
        restaurant_id=restaurant_id,
        amount_aed=_q(-amount),
        type="hold",
        status="held",
        idempotency_key=idempotency_key,
        order_id=order_id,
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="wallet_entry",
        entity_id=str(entry.id),
        action="hold",
        before=None,
        after={"amount_aed": str(_q(-amount)), "order_id": order_id},
    )
    return entry


async def capture(
    session: AsyncSession,
    *,
    account_id: int,
    restaurant_id: int,
    order_id: int,
    idempotency_key: str,
    created_by: str,
) -> WalletEntry:
    """Settle the order's hold into a posted debit (balance drops by the held amount)."""
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    held = await _order_hold(session, account_id, order_id)
    if held is None:
        raise WalletError(f"no active hold for order {order_id}")
    # Flip the single hold entry into the real posted debit. One entry, no double count.
    held.type = "order_debit"
    held.status = "posted"
    held.idempotency_key = idempotency_key
    await session.flush()
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="wallet_entry",
        entity_id=str(held.id),
        action="capture",
        before={"status": "held", "type": "hold"},
        after={"status": "posted", "type": "order_debit", "order_id": order_id},
    )
    return held


async def release(
    session: AsyncSession,
    *,
    account_id: int,
    restaurant_id: int,
    order_id: int,
    idempotency_key: str,
    created_by: str,
) -> WalletEntry | None:
    """Cancel an uncaptured hold — credit returns to available. Idempotent."""
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    held = await _order_hold(session, account_id, order_id)
    if held is None:
        return None
    amount = -held.amount_aed  # positive
    held.status = "posted"  # the hold (-X) now counts in balance...
    rel = WalletEntry(
        account_id=account_id,
        restaurant_id=restaurant_id,
        amount_aed=_q(amount),  # ...and this (+X) nets it back to zero
        type="hold_release",
        status="posted",
        idempotency_key=idempotency_key,
        order_id=order_id,
        reverses_entry_id=held.id,
        created_by=created_by,
    )
    session.add(rel)
    await session.flush()
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="wallet_entry",
        entity_id=str(rel.id),
        action="release",
        before=None,
        after={"order_id": order_id, "amount_aed": str(_q(amount))},
    )
    return rel


async def freeze(
    session: AsyncSession,
    *,
    account_id: int,
    restaurant_id: int,
    reason: str,
    created_by: str,
) -> WalletAccount:
    """Freeze an account (abuse hold) — blocks spend. Audited."""
    acc = await _account(session, account_id)
    before = {"status": acc.status}
    acc.status = "frozen"
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="wallet_account",
        entity_id=str(acc.id),
        action="freeze",
        before=before,
        after={"status": "frozen", "reason": reason},
    )
    return acc


async def unfreeze(
    session: AsyncSession,
    *,
    account_id: int,
    restaurant_id: int,
    created_by: str,
) -> WalletAccount:
    """Reactivate a frozen account. Audited."""
    acc = await _account(session, account_id)
    before = {"status": acc.status}
    acc.status = "active"
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="wallet_account",
        entity_id=str(acc.id),
        action="unfreeze",
        before=before,
        after={"status": "active"},
    )
    return acc


async def reverse(
    session: AsyncSession,
    *,
    entry_id: int,
    restaurant_id: int,
    idempotency_key: str,
    reason_note: str,
    created_by: str,
) -> WalletEntry:
    """Append a reversing entry that negates a posted entry. Idempotent.

    Held entries cannot be reversed (release them instead).
    """
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    original = await session.get(WalletEntry, entry_id)
    if original is None:
        raise WalletError(f"wallet entry {entry_id} not found")
    if original.status == "held":
        raise WalletError("cannot reverse a held entry — release it instead")
    rev = WalletEntry(
        account_id=original.account_id,
        restaurant_id=restaurant_id,
        amount_aed=_q(-original.amount_aed),
        type="reversal",
        status="posted",
        idempotency_key=idempotency_key,
        reverses_entry_id=original.id,
        reason_note=reason_note,
        created_by=created_by,
    )
    session.add(rev)
    await session.flush()
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="wallet_entry",
        entity_id=str(rev.id),
        action="reversal",
        before={"reverses_entry_id": original.id},
        after={"amount_aed": str(_q(-original.amount_aed)), "reason": reason_note},
    )
    return rev
