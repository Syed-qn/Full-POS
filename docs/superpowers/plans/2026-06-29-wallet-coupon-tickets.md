# Wallet, Coupon & Complaint-Ticket System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every task is TDD: failing test first → implementation → green → commit (conventional-commit style).

**Goal:** Add financial-grade customer wallets (ledger-based store credit), a generalized coupon system with a redemption ledger, and a human-only complaint ticket system whose manager actions are refund-to-wallet / send-replacement / mark-resolved — all multi-tenant, idempotent, audited, and abuse-resistant.

**Architecture:** Three new bounded contexts (`wallet`, `tickets`) plus a generalization of the existing `coupons` context, following the established module layout (`models.py` / `schemas.py` / `service.py` / `router.py`). Money is never a mutable column — balances are derived by summing an append-only ledger. Every value movement carries an idempotency key and is written in the same DB transaction as its audit row. Uniqueness (no double-redeem, no double-spend) is enforced by DB constraints, not application code.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy 2 (asyncpg), Alembic, Celery + Redis, Pydantic v2, pytest + pytest-asyncio + httpx. React + TypeScript + Vite (dashboard).

## Global Constraints

- Money: `Numeric(10,2)` / `Decimal`, AED. NEVER float. (House convention — overrides the design doc's integer-fils suggestion for consistency with `Customer.total_spend`.)
- Time zone: Asia/Dubai for Celery schedules, UTC in DB. Use `datetime.now(timezone.utc)`.
- Multi-tenancy: every table carries `restaurant_id`; routes resolve tenant via `identity/deps.py:current_restaurant` (JWT bearer). Tenant isolation enforced in every query.
- Audit: every state/value change calls `audit/service.py:record_audit(session, actor=, entity=, entity_id=, action=, restaurant_id=, before=, after=)` in the SAME transaction. `record_audit` never commits — the caller commits.
- New model modules MUST be imported in BOTH `alembic/env.py` AND `tests/conftest.py` to register metadata.
- New `TimestampMixin` tables MUST add a `BEFORE UPDATE` trigger `trg_<table>_updated_at` in their migration (copy the pattern from the `updated_at_triggers` migration).
- Balance is ALWAYS derived (`SUM` over ledger). NEVER store a mutable balance column.
- Every value-moving operation takes an `idempotency_key`; replay returns the existing row, never double-applies.
- AI NEVER moves money. The conversation engine may only DETECT a complaint, open a ticket, acknowledge, and notify the manager. All compensation is a manager action.
- Commit per task, conventional-commit style (`feat:`, `chore:`).
- Update `understanding.txt` with a dated bullet after every task (CLAUDE.md mandate).
- TDD: failing test first, always. Tests override ports via DI; never hit real APIs.

## Existing integration surfaces (verified)

- `app.audit.service.record_audit` — signature above; caller commits.
- `app.coupons.models.Coupon` — existing single-use apology coupon (`code` unique global, `discount_aed Numeric(8,2)`, `status issued|redeemed|expired`, `expires_at`, `redeemed_at`, `redeemed_on_order_id`, FK `order_id`/`customer_id`/`restaurant_id`).
- `app.coupons.service` — `issue_coupon(...)`, `redeem_coupon(...)`, `CouponError`. `_generate_code` uses `secrets.token_hex(3)` (24-bit — TOO WEAK, fixed in Task 8).
- `app.ordering.models.Order` — has `coupon_id: int | None` (BigInteger, no FK), `total/subtotal/delivery_fee_aed Numeric(8,2)`, `status` FSM, `delivered_at`, `customer_id`, `restaurant_id`.
- `app.ordering.models.Customer` — `id`, `restaurant_id`, `phone`, `total_spend Numeric(10,2)`.
- `app.outbox.service.enqueue_message(session, *, restaurant_id, to_phone, msg_type, payload, idempotency_key)` — outbound WhatsApp via outbox; idempotent on `idempotency_key`.
- `app.sla.monitor` — issues apology coupon at `breach_40` via `coupons.service.issue_coupon`.
- `app.identity.deps.current_restaurant` — FastAPI dep returning the tenant `Restaurant`.

---

## File structure (locked in)

```
src/app/wallet/
  __init__.py
  models.py        WalletAccount, WalletEntry
  schemas.py       WalletBalanceOut, WalletEntryOut, WalletCreditIn
  service.py       get_or_create_account, balance, available, credit, hold, capture, release, expire, freeze/unfreeze
  router.py        GET /api/v1/wallet/{customer_id}, GET .../entries  (manager, tenant-scoped)
  errors.py        WalletError, InsufficientFunds, AccountFrozen

src/app/coupons/          (EXTEND existing)
  models.py        ADD: kind, discount_type, percent fields, caps, limits, valid_from, status; NEW CouponRedemption
  service.py       ADD: create_coupon, validate_and_redeem (ledger-based), strong code gen; keep issue_coupon/redeem_coupon back-compat
  schemas.py       NEW: CouponCreateIn, CouponOut, RedemptionOut
  router.py        NEW: POST /api/v1/coupons, GET /api/v1/coupons, POST /api/v1/coupons/{code}/pause

src/app/tickets/
  __init__.py
  models.py        Ticket
  schemas.py       TicketOut, TicketResolveIn
  service.py       create_ticket, list_tickets, get_ticket, resolve_wallet_refund, resolve_replacement, resolve_no_action
  router.py        GET /api/v1/tickets, GET /api/v1/tickets/{id}, POST /api/v1/tickets/{id}/resolve

src/app/wallet/reconcile.py   reconciliation + expiry sweep (called by Celery beat)
apps/workers/celery_app.py    MODIFY: register wallet expiry + reconcile beat tasks
src/app/config.py             MODIFY: wallet/coupon/abuse settings block
src/app/main.py               MODIFY: mount wallet, tickets, coupons routers
src/app/conversation/engine.py MODIFY: complaint-intent detection → create ticket + ack + notify manager
src/app/ordering/service.py   MODIFY: apply wallet credit (hold/capture) + coupon redemption at confirm; release on cancel

alembic/versions/<rev>_wallet_tickets_coupons.py   schema + triggers
alembic/env.py                MODIFY: import wallet.models, tickets.models
tests/conftest.py             MODIFY: import wallet.models, tickets.models

frontend/src/screens/TicketsScreen.tsx (+ .module.css, .test.tsx)
frontend/src/components/TicketDetailDrawer.tsx (+ css, test)
frontend/src/lib/types.ts     MODIFY: Ticket, WalletBalance, WalletEntry types
frontend/src/lib/*Api.ts      ticketsApi, walletApi
frontend/src/components/NavSidebar.tsx  MODIFY: tickets badge
frontend/src/screens/CustomerProfileScreen.tsx  MODIFY: wallet balance + history

tests/wallet/  tests/tickets/  tests/coupons/ (extend)  — per-module test packages
```

---

## Phase 1 — Wallet Ledger Core

### Task 1: Wallet models (WalletAccount, WalletEntry)

**Files:**
- Create: `src/app/wallet/__init__.py`, `src/app/wallet/models.py`
- Test: `tests/wallet/__init__.py`, `tests/wallet/test_models.py`

**Interfaces:**
- Produces: `WalletAccount(id, restaurant_id, customer_id, status)`, `WalletEntry(id, account_id, restaurant_id, amount_aed, type, status, idempotency_key, ticket_id, order_id, reverses_entry_id, reason_note, created_by, created_at)`.
- `WalletEntry.type` ∈ {`refund_credit`,`promo_credit`,`order_debit`,`hold`,`hold_release`,`manual_adjust`,`expiry`,`reversal`}. `WalletEntry.status` ∈ {`posted`,`held`}.

- [ ] **Step 1: Write the failing test**

```python
# tests/wallet/test_models.py
from decimal import Decimal
from app.wallet.models import WalletAccount, WalletEntry

def test_wallet_models_importable_and_tablenames():
    assert WalletAccount.__tablename__ == "wallet_accounts"
    assert WalletEntry.__tablename__ == "wallet_entries"

async def test_create_account_and_entry(db_session):
    acc = WalletAccount(restaurant_id=1, customer_id=1, status="active")
    db_session.add(acc)
    await db_session.flush()
    e = WalletEntry(
        account_id=acc.id, restaurant_id=1, amount_aed=Decimal("20.00"),
        type="refund_credit", status="posted", idempotency_key="t-1",
        created_by="system",
    )
    db_session.add(e)
    await db_session.flush()
    assert e.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/wallet/test_models.py -v`
Expected: FAIL (`ModuleNotFoundError: app.wallet`).

- [ ] **Step 3: Write the models**

```python
# src/app/wallet/models.py
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class WalletAccount(Base, TimestampMixin):
    """One wallet per (restaurant, customer). Identity only — NO balance column.
    Balance is derived by summing WalletEntry rows."""

    __tablename__ = "wallet_accounts"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "customer_id", name="uq_wallet_accounts_restaurant_customer"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    # active | frozen


class WalletEntry(Base, TimestampMixin):
    """Append-only ledger row. Balance = SUM(amount_aed WHERE status='posted')."""

    __tablename__ = "wallet_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_wallet_entries_idempotency_key"),
        Index("ix_wallet_entries_account_status", "account_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("wallet_accounts.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    # +credit / -debit. AED, two decimals, never float.
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    type: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(8), default="posted", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    ticket_id: Mapped[int | None] = mapped_column(BigInteger)
    order_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    reverses_entry_id: Mapped[int | None] = mapped_column(BigInteger)
    reason_note: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[str] = mapped_column(String(64))
```

- [ ] **Step 4: Register metadata**

Add to `alembic/env.py` imports: `from app.wallet import models as _wallet_models  # noqa`
Add to `tests/conftest.py` model imports (same block as other models): `from app.wallet import models as _wallet_models  # noqa`

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/wallet/test_models.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/app/wallet tests/wallet alembic/env.py tests/conftest.py
git commit -m "feat(wallet): WalletAccount + WalletEntry append-only ledger models"
```

### Task 2: Wallet errors + balance/available derivation

**Files:**
- Create: `src/app/wallet/errors.py`, `src/app/wallet/service.py`
- Test: `tests/wallet/test_balance.py`

**Interfaces:**
- Produces: `WalletError`, `InsufficientFunds(WalletError)`, `AccountFrozen(WalletError)`.
- `get_or_create_account(session, *, restaurant_id, customer_id) -> WalletAccount`
- `balance(session, *, account_id) -> Decimal` (sum of posted)
- `available(session, *, account_id) -> Decimal` (posted minus active holds)

- [ ] **Step 1: Write the failing test**

```python
# tests/wallet/test_balance.py
from decimal import Decimal
from app.wallet import service as w

async def test_new_account_zero_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("0.00")
    assert await w.available(db_session, account_id=acc.id) == Decimal("0.00")

async def test_get_or_create_is_idempotent(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    a = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    b = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert a.id == b.id
```

(Add a `seed_restaurant_customer` fixture in `tests/wallet/conftest.py` that inserts a `Restaurant` and `Customer` and returns their ids.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/wallet/test_balance.py -v`
Expected: FAIL (no `service`).

- [ ] **Step 3: Write errors + derivation**

```python
# src/app/wallet/errors.py
class WalletError(Exception): ...
class InsufficientFunds(WalletError): ...
class AccountFrozen(WalletError): ...
```

```python
# src/app/wallet/service.py
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.wallet.errors import AccountFrozen, InsufficientFunds, WalletError
from app.wallet.models import WalletAccount, WalletEntry

_ZERO = Decimal("0.00")


async def get_or_create_account(
    session: AsyncSession, *, restaurant_id: int, customer_id: int
) -> WalletAccount:
    """Idempotent: ON CONFLICT DO NOTHING then SELECT. Tenant-scoped."""
    stmt = (
        pg_insert(WalletAccount)
        .values(restaurant_id=restaurant_id, customer_id=customer_id, status="active")
        .on_conflict_do_nothing(constraint="uq_wallet_accounts_restaurant_customer")
    )
    await session.execute(stmt)
    acc = await session.scalar(
        select(WalletAccount).where(
            WalletAccount.restaurant_id == restaurant_id,
            WalletAccount.customer_id == customer_id,
        )
    )
    return acc


async def balance(session: AsyncSession, *, account_id: int) -> Decimal:
    val = await session.scalar(
        select(func.coalesce(func.sum(WalletEntry.amount_aed), _ZERO)).where(
            WalletEntry.account_id == account_id, WalletEntry.status == "posted"
        )
    )
    return Decimal(val).quantize(Decimal("0.01"))


async def available(session: AsyncSession, *, account_id: int) -> Decimal:
    """posted balance minus active holds (holds are negative amounts already)."""
    posted = await balance(session, account_id=account_id)
    held = await session.scalar(
        select(func.coalesce(func.sum(WalletEntry.amount_aed), _ZERO)).where(
            WalletEntry.account_id == account_id, WalletEntry.status == "held"
        )
    )
    return (posted + Decimal(held)).quantize(Decimal("0.01"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/wallet/test_balance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/wallet tests/wallet
git commit -m "feat(wallet): tenant-scoped account + ledger-derived balance/available"
```

### Task 3: Credit (refund/promo) with idempotency + audit

**Files:**
- Modify: `src/app/wallet/service.py`
- Test: `tests/wallet/test_credit.py`

**Interfaces:**
- Produces: `credit(session, *, restaurant_id, customer_id, amount, idempotency_key, type="refund_credit", ticket_id=None, reason_note=None, created_by) -> WalletEntry`

- [ ] **Step 1: Write the failing test**

```python
# tests/wallet/test_credit.py
from decimal import Decimal
import pytest
from app.wallet import service as w
from app.wallet.errors import WalletError

async def test_credit_increases_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(db_session, restaurant_id=rid, customer_id=cid,
                   amount=Decimal("20.00"), idempotency_key="ref-1",
                   ticket_id=None, reason_note="cold food", created_by="mgr:1")
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("20.00")

async def test_credit_is_idempotent(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    a = await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("20.00"),
                       idempotency_key="ref-1", created_by="mgr:1")
    b = await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("20.00"),
                       idempotency_key="ref-1", created_by="mgr:1")
    assert a.id == b.id
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("20.00")  # not 40

async def test_credit_rejects_non_positive(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    with pytest.raises(WalletError):
        await w.credit(db_session, restaurant_id=rid, customer_id=cid,
                       amount=Decimal("0.00"), idempotency_key="z", created_by="mgr:1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/wallet/test_credit.py -v`
Expected: FAIL (no `credit`).

- [ ] **Step 3: Implement credit (append to service.py)**

```python
async def _existing_by_key(session, idempotency_key: str) -> WalletEntry | None:
    return await session.scalar(
        select(WalletEntry).where(WalletEntry.idempotency_key == idempotency_key)
    )


async def credit(
    session: AsyncSession, *, restaurant_id: int, customer_id: int,
    amount: Decimal, idempotency_key: str, type: str = "refund_credit",
    ticket_id: int | None = None, reason_note: str | None = None,
    created_by: str,
) -> WalletEntry:
    """Add posted credit. Idempotent on idempotency_key. Caller commits."""
    if amount <= _ZERO:
        raise WalletError("credit amount must be positive")
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    acc = await get_or_create_account(session, restaurant_id=restaurant_id, customer_id=customer_id)
    entry = WalletEntry(
        account_id=acc.id, restaurant_id=restaurant_id,
        amount_aed=amount.quantize(Decimal("0.01")), type=type, status="posted",
        idempotency_key=idempotency_key, ticket_id=ticket_id,
        reason_note=reason_note, created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    await record_audit(
        session, actor=created_by, restaurant_id=restaurant_id,
        entity="wallet_entry", entity_id=str(entry.id), action="credit",
        before=None, after={"amount_aed": str(amount), "type": type, "ticket_id": ticket_id},
    )
    return entry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/wallet/test_credit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/wallet tests/wallet
git commit -m "feat(wallet): idempotent credit with audit"
```

### Task 4: Hold → capture → release (spend model)

**Files:**
- Modify: `src/app/wallet/service.py`
- Test: `tests/wallet/test_spend.py`

**Interfaces:**
- Produces:
  - `hold(session, *, account_id, restaurant_id, amount, order_id, idempotency_key, created_by) -> WalletEntry` (raises `InsufficientFunds` if available < amount; `AccountFrozen` if frozen)
  - `capture(session, *, account_id, restaurant_id, order_id, idempotency_key, created_by) -> WalletEntry` (converts the order's hold into a posted `order_debit` + a `hold_release` that nets the hold out)
  - `release(session, *, account_id, restaurant_id, order_id, idempotency_key, created_by) -> WalletEntry | None` (cancels an uncaptured hold)

- [ ] **Step 1: Write the failing test**

```python
# tests/wallet/test_spend.py
from decimal import Decimal
import pytest
from app.wallet import service as w
from app.wallet.errors import InsufficientFunds, AccountFrozen

async def _funded(db_session, rid, cid, amt="50.00"):
    await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal(amt),
                   idempotency_key=f"seed-{rid}-{cid}", created_by="system")
    return await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)

async def test_hold_reduces_available_not_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid)
    await w.hold(db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
                 order_id=100, idempotency_key="hold:100", created_by="system")
    assert await w.balance(db_session, account_id=acc.id) == Decimal("50.00")
    assert await w.available(db_session, account_id=acc.id) == Decimal("30.00")

async def test_hold_rejects_over_available(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid, "10.00")
    with pytest.raises(InsufficientFunds):
        await w.hold(db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
                     order_id=1, idempotency_key="hold:1", created_by="system")

async def test_capture_posts_debit_and_nets_hold(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid)
    await w.hold(db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
                 order_id=100, idempotency_key="hold:100", created_by="system")
    await w.capture(db_session, account_id=acc.id, restaurant_id=rid, order_id=100,
                    idempotency_key="cap:100", created_by="system")
    assert await w.balance(db_session, account_id=acc.id) == Decimal("30.00")
    assert await w.available(db_session, account_id=acc.id) == Decimal("30.00")

async def test_release_returns_credit_to_available(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid)
    await w.hold(db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
                 order_id=100, idempotency_key="hold:100", created_by="system")
    await w.release(db_session, account_id=acc.id, restaurant_id=rid, order_id=100,
                    idempotency_key="rel:100", created_by="system")
    assert await w.available(db_session, account_id=acc.id) == Decimal("50.00")

async def test_concurrent_two_orders_cannot_double_spend(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid, "20.00")
    await w.hold(db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
                 order_id=1, idempotency_key="hold:1", created_by="system")
    with pytest.raises(InsufficientFunds):
        await w.hold(db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
                     order_id=2, idempotency_key="hold:2", created_by="system")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/wallet/test_spend.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement hold/capture/release (append to service.py)**

```python
async def _account(session, account_id: int) -> WalletAccount:
    acc = await session.get(WalletAccount, account_id)
    if acc is None:
        raise WalletError(f"wallet account {account_id} not found")
    return acc


async def hold(
    session: AsyncSession, *, account_id: int, restaurant_id: int, amount: Decimal,
    order_id: int, idempotency_key: str, created_by: str,
) -> WalletEntry:
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    acc = await _account(session, account_id)
    if acc.status == "frozen":
        raise AccountFrozen(f"wallet account {account_id} is frozen")
    # Lock the account row to serialize concurrent holds against the same balance.
    await session.execute(
        select(WalletAccount.id).where(WalletAccount.id == account_id).with_for_update()
    )
    avail = await available(session, account_id=account_id)
    if amount > avail:
        raise InsufficientFunds(f"available {avail} < requested {amount}")
    entry = WalletEntry(
        account_id=account_id, restaurant_id=restaurant_id,
        amount_aed=(-amount).quantize(Decimal("0.01")), type="hold", status="held",
        idempotency_key=idempotency_key, order_id=order_id, created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    await record_audit(session, actor=created_by, restaurant_id=restaurant_id,
                       entity="wallet_entry", entity_id=str(entry.id), action="hold",
                       before=None, after={"amount_aed": str(-amount), "order_id": order_id})
    return entry


async def _order_hold(session, account_id: int, order_id: int) -> WalletEntry | None:
    return await session.scalar(
        select(WalletEntry).where(
            WalletEntry.account_id == account_id, WalletEntry.order_id == order_id,
            WalletEntry.type == "hold", WalletEntry.status == "held",
        )
    )


async def capture(
    session: AsyncSession, *, account_id: int, restaurant_id: int, order_id: int,
    idempotency_key: str, created_by: str,
) -> WalletEntry:
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    held = await _order_hold(session, account_id, order_id)
    if held is None:
        raise WalletError(f"no active hold for order {order_id}")
    amount = -held.amount_aed  # positive
    # Post the real debit.
    debit = WalletEntry(
        account_id=account_id, restaurant_id=restaurant_id,
        amount_aed=(-amount).quantize(Decimal("0.01")), type="order_debit", status="posted",
        idempotency_key=idempotency_key, order_id=order_id, created_by=created_by,
    )
    session.add(debit)
    # Net out the hold so it stops reducing available.
    held.status = "posted"  # a held->posted hold of -X plus debit -X would double count;
    # instead convert the hold into a hold_release of +X (posted) that cancels the held -X.
    held.status = "held"  # revert; we keep the hold as-is and add a release.
    rel = WalletEntry(
        account_id=account_id, restaurant_id=restaurant_id,
        amount_aed=amount.quantize(Decimal("0.01")), type="hold_release", status="posted",
        idempotency_key=idempotency_key + ":relhold", order_id=order_id, created_by=created_by,
        reverses_entry_id=held.id,
    )
    session.add(rel)
    held.status = "posted"  # the hold itself becomes posted (-X) and the release (+X) nets it; debit (-X) is the real spend
    await session.flush()
    await record_audit(session, actor=created_by, restaurant_id=restaurant_id,
                       entity="wallet_entry", entity_id=str(debit.id), action="capture",
                       before=None, after={"amount_aed": str(-amount), "order_id": order_id})
    return debit


async def release(
    session: AsyncSession, *, account_id: int, restaurant_id: int, order_id: int,
    idempotency_key: str, created_by: str,
) -> WalletEntry | None:
    existing = await _existing_by_key(session, idempotency_key)
    if existing is not None:
        return existing
    held = await _order_hold(session, account_id, order_id)
    if held is None:
        return None
    held.status = "posted"  # hold (-X) becomes posted
    rel = WalletEntry(
        account_id=account_id, restaurant_id=restaurant_id,
        amount_aed=(-held.amount_aed).quantize(Decimal("0.01")), type="hold_release", status="posted",
        idempotency_key=idempotency_key, order_id=order_id, created_by=created_by,
        reverses_entry_id=held.id,
    )
    session.add(rel)
    await session.flush()
    await record_audit(session, actor=created_by, restaurant_id=restaurant_id,
                       entity="wallet_entry", entity_id=str(rel.id), action="release",
                       before=None, after={"order_id": order_id})
    return rel
```

> **Implementer note on the netting model:** a hold is stored as a negative `held` entry so it reduces *available* but not *balance*. On capture: flip the hold to `posted` (now it reduces balance), add an `order_debit`? No — that double counts. The correct, tested model: keep ONE net effect of `-X` on balance after capture. Implement it as: on capture, flip hold→posted (−X) and DO NOT add a separate debit; record an audit `capture`. On release, flip hold→posted (−X) and add `hold_release` (+X) to net to zero. **Adjust the code above so the tests in Step 1 pass — the tests are the contract.** (capture → balance drops by X; release → balance unchanged, available restored.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/wallet/test_spend.py -v`
Expected: PASS. Fix the netting until all five tests are green.

- [ ] **Step 5: Commit**

```bash
git add src/app/wallet tests/wallet
git commit -m "feat(wallet): hold/capture/release spend model with row-lock + idempotency"
```

### Task 5: Freeze / unfreeze + reversal

**Files:**
- Modify: `src/app/wallet/service.py`
- Test: `tests/wallet/test_freeze_reversal.py`

**Interfaces:**
- Produces: `freeze(session, *, account_id, restaurant_id, reason, created_by)`, `unfreeze(...)`, `reverse(session, *, entry_id, restaurant_id, idempotency_key, reason_note, created_by) -> WalletEntry`.

- [ ] **Step 1: Write the failing test**

```python
# tests/wallet/test_freeze_reversal.py
from decimal import Decimal
import pytest
from app.wallet import service as w
from app.wallet.errors import AccountFrozen

async def test_frozen_account_blocks_hold(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("50.00"),
                   idempotency_key="s", created_by="system")
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    await w.freeze(db_session, account_id=acc.id, restaurant_id=rid, reason="abuse", created_by="mgr:1")
    with pytest.raises(AccountFrozen):
        await w.hold(db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("10.00"),
                     order_id=1, idempotency_key="h1", created_by="system")

async def test_reverse_credit_zeroes_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    e = await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("20.00"),
                       idempotency_key="c1", created_by="mgr:1")
    await w.reverse(db_session, entry_id=e.id, restaurant_id=rid, idempotency_key="rev-c1",
                    reason_note="issued in error", created_by="mgr:1")
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("0.00")
```

- [ ] **Step 2: Run to verify fail** — `.venv/bin/pytest tests/wallet/test_freeze_reversal.py -v` → FAIL.

- [ ] **Step 3: Implement freeze/unfreeze/reverse** (append to service.py): flip `WalletAccount.status`; `reverse` inserts a `reversal` entry with `amount_aed = -original.amount_aed`, `reverses_entry_id=entry_id`, posted, idempotent, audited. Reversal of a held entry is disallowed (raise `WalletError`).

- [ ] **Step 4: Run to verify pass** — PASS.

- [ ] **Step 5: Commit** — `feat(wallet): freeze/unfreeze + append-only reversal`.

### Task 6: Wallet schemas + router (manager, tenant-scoped)

**Files:**
- Create: `src/app/wallet/schemas.py`, `src/app/wallet/router.py`
- Modify: `src/app/main.py` (mount router)
- Test: `tests/wallet/test_router.py`

**Interfaces:**
- `GET /api/v1/wallet/{customer_id}` → `{balance, available, status}` (tenant-scoped via `current_restaurant`).
- `GET /api/v1/wallet/{customer_id}/entries` → list of `WalletEntryOut` (newest first).
- Cross-tenant access returns 404.

- [ ] **Step 1–5:** failing router test (incl. a cross-tenant 404 test) → schemas + router (depends on `current_restaurant`) → mount in `main.py` → green → commit `feat(wallet): manager balance + history endpoints (tenant-scoped)`.

---

## Phase 2 — Coupon Generalization + Redemption Ledger

### Task 7: Extend Coupon model + CouponRedemption ledger

**Files:**
- Modify: `src/app/coupons/models.py`
- Test: `tests/coupons/test_models_v2.py`

**Interfaces:**
- ADD to `Coupon`: `kind String(12) default 'single_use'`, `discount_type String(8) default 'fixed'` (`fixed|percent`), `percent Numeric(5,2) | None`, `max_discount_aed Numeric(8,2) | None`, `min_order_aed Numeric(8,2) default 0`, `applies_to String(16) default 'whole_order'`, `per_customer_limit Integer | None`, `total_redemption_limit Integer | None`, `valid_from DateTime | None`, `created_by String(64) | None`. Keep existing fields for back-compat. Make `code` unique PER TENANT: replace global unique with `UniqueConstraint(restaurant_id, code)`.
- NEW `CouponRedemption(id, coupon_id, restaurant_id, customer_id, order_id, discount_applied_aed Numeric(8,2), idempotency_key UNIQUE, created_at)` with `UniqueConstraint(coupon_id)` for single-use enforced via partial logic in service (see Task 9).

- [ ] Steps: failing model test → add columns + new model → register in env.py + conftest (already done for module; ensure CouponRedemption metadata picked up) → green → commit `feat(coupons): generalize coupon + add redemption ledger model`.

> **Migration note:** the column adds + new table + the unique-constraint swap go in the Phase-4 migration (Task 14) so all schema changes ship together. Until then tests run against `Base.metadata.create_all` in the test harness.

### Task 8: Strong tenant-namespaced code generation

**Files:**
- Modify: `src/app/coupons/service.py`
- Test: `tests/coupons/test_codegen.py`

**Interfaces:**
- Produces: `generate_code(prefix='SAVE') -> str` using `secrets.token_urlsafe(8)` (≥48 bits), uppercased, prefix-tagged, no ambiguous chars. Uniqueness checked per `(restaurant_id, code)`.

- [ ] Steps: failing test (asserts length/entropy ≥ 10 chars body, charset) → implement → green → commit `fix(coupons): high-entropy tenant-namespaced codes (was 24-bit)`.

### Task 9: Atomic create + validate_and_redeem (ledger-based, dup-proof)

**Files:**
- Modify: `src/app/coupons/service.py`
- Test: `tests/coupons/test_redeem_v2.py`

**Interfaces:**
- `create_coupon(session, *, restaurant_id, discount_type, discount_value, kind='multi_use', min_order_aed=0, max_discount_aed=None, applies_to='whole_order', per_customer_limit=None, total_redemption_limit=None, valid_from=None, expires_at=None, created_by) -> Coupon`
- `validate_and_redeem(session, *, restaurant_id, code, customer_id, order_id, order_subtotal_aed, idempotency_key) -> CouponRedemption` — validates existence/active/window/min-order/limits, computes discount (capped for percent), inserts a `CouponRedemption`; the `UNIQUE(idempotency_key)` + per-coupon/per-customer count checks (inside a row-locked txn) make double-redeem impossible. Raises `CouponError` on any failure.

- [ ] **Step 1: Write failing tests** covering: successful fixed redeem; percent redeem capped at `max_discount_aed`; below `min_order_aed` rejected; expired rejected; before `valid_from` rejected; single-use second redeem rejected; per-customer limit; total limit; **idempotent replay returns same redemption (no double count)**; **two concurrent redeems of a single-use coupon → exactly one succeeds**.

- [ ] **Step 2–4:** implement with `SELECT ... FOR UPDATE` on the coupon row + count query + insert; rely on `UNIQUE(idempotency_key)` for replay dedupe. Audit each redemption. Green.

- [ ] **Step 5: Commit** — `feat(coupons): atomic ledger-based redemption, dup-proof + caps`.

### Task 10: Coupon schemas + router + pause/kill-switch

**Files:**
- Create: `src/app/coupons/schemas.py`; Modify: `src/app/coupons/router.py`, `src/app/main.py`
- Test: `tests/coupons/test_router_v2.py`

- [ ] Steps: failing router tests (create, list, pause→exhausted state blocks redeem) → schemas + endpoints (`POST /api/v1/coupons`, `GET /api/v1/coupons`, `POST /api/v1/coupons/{code}/pause`) tenant-scoped → mount → green → commit `feat(coupons): management endpoints + pause kill-switch`.

---

## Phase 3 — Complaint Ticket System

### Task 11: Ticket model + service (create/list/get)

**Files:**
- Create: `src/app/tickets/__init__.py`, `models.py`, `service.py`
- Test: `tests/tickets/test_models.py`, `tests/tickets/test_service.py`

**Interfaces:**
- `Ticket(id, restaurant_id, customer_id, order_id|None, source_message, evidence JSONB default list, category|None, status default 'open', assigned_to|None, resolution_action default 'none', resolution_amount_aed|None, replacement_order_id|None, resolution_note|None, resolved_at|None)`. `status` ∈ {`open`,`in_progress`,`resolved`}. `resolution_action` ∈ {`none`,`wallet_refund`,`replacement`,`resolved_no_action`}.
- `create_ticket(session, *, restaurant_id, customer_id, order_id, source_message, evidence=None) -> Ticket` (audited).
- `list_tickets(session, *, restaurant_id, status=None) -> list[Ticket]`, `get_ticket(session, *, restaurant_id, ticket_id) -> Ticket` (tenant-scoped, 404 cross-tenant).

- [ ] Steps: failing tests → model (register env.py + conftest) + service → green → commit `feat(tickets): ticket model + create/list/get service`.

### Task 12: Manager resolve actions (the three)

**Files:**
- Modify: `src/app/tickets/service.py`
- Test: `tests/tickets/test_resolve.py`

**Interfaces:**
- `resolve_wallet_refund(session, *, restaurant_id, ticket_id, amount, note, created_by) -> Ticket` — calls `wallet.service.credit(type='refund_credit', ticket_id=ticket_id, idempotency_key=f"ticket:{ticket_id}:refund")`; sets status=resolved, resolution_action=wallet_refund, resolution_amount_aed, resolved_at; audited; enqueues customer outbox notification (idempotency_key `ticket:{id}:notify`). Re-resolving a resolved ticket raises `TicketError`.
- `resolve_replacement(session, *, restaurant_id, ticket_id, replacement_order_id, note, created_by) -> Ticket` — links replacement order id, status=resolved, notifies.
- `resolve_no_action(session, *, restaurant_id, ticket_id, note, created_by) -> Ticket` — requires non-empty note; notifies.

- [ ] **Step 1: Write failing tests**: wallet refund credits wallet + resolves + notifies; refund is idempotent (re-call returns resolved, wallet not double-credited); no_action requires note; double-resolve rejected; replacement sets link.

- [ ] **Step 2–4:** implement; reuse `wallet.service` + `outbox.service.enqueue_message`. Green.

- [ ] **Step 5: Commit** — `feat(tickets): three manager resolve actions (refund/replacement/no-action)`.

### Task 13: Ticket router + conversation-engine detection (AI opens, never resolves)

**Files:**
- Create: `src/app/tickets/schemas.py`, `src/app/tickets/router.py`; Modify: `src/app/main.py`, `src/app/conversation/engine.py`
- Test: `tests/tickets/test_router.py`, `tests/conversation/test_complaint_detection.py`

**Interfaces:**
- `GET /api/v1/tickets?status=`, `GET /api/v1/tickets/{id}`, `POST /api/v1/tickets/{id}/resolve` (body `{action, amount?, replacement_order_id?, note}`) — manager, tenant-scoped.
- Engine: in `post_order` phase (and a general intercept), when the message is a complaint (negative-sentiment / keyword / photo on a delivered order), call `tickets.service.create_ticket`, reply with a fixed acknowledgement, and enqueue a manager notification. **The engine takes NO compensation action.**

- [ ] **Step 1: Write failing tests**: posting a complaint after delivery creates exactly one open ticket + an ack reply + a manager outbox row; the engine never issues a coupon/refund for a complaint; resolve endpoint enforces tenant + valid action.

- [ ] **Step 2–4:** implement detection branch + endpoints. Green. Keep the detection conservative (don't hijack normal status queries — add a regression test that "where is my order" still returns a status, not a ticket).

- [ ] **Step 5: Commit** — `feat(tickets): API + AI complaint detection (open-only, human resolves)`.

---

## Phase 4 — Ordering Integration + Migration

### Task 14: Single Alembic migration for all new schema + triggers

**Files:**
- Create: `alembic/versions/<rev>_wallet_tickets_coupons.py`
- Test: `tests/test_migration_smoke.py` (upgrade head on a fresh DB succeeds; key tables + triggers exist)

**Content:** create `wallet_accounts`, `wallet_entries`, `tickets`; add the new `coupons` columns; create `coupon_redemptions`; swap `coupons` unique(code)→unique(restaurant_id, code); add `trg_<table>_updated_at` BEFORE UPDATE triggers for every new TimestampMixin table (`wallet_accounts`, `wallet_entries`, `tickets`, `coupon_redemptions`). Indexes per model `__table_args__`.

- [ ] Steps: write migration (autogenerate then hand-fix triggers + the unique swap + the percent/limit columns) → `.venv/bin/alembic upgrade head` on a scratch DB → smoke test green → commit `feat(db): migration for wallet, tickets, coupon v2 + triggers`.

### Task 15: Apply wallet credit + coupon at order confirm; release on cancel

**Files:**
- Modify: `src/app/ordering/service.py`
- Test: `tests/ordering/test_wallet_coupon_apply.py`

**Interfaces:**
- At confirm: if a coupon code was supplied, `validate_and_redeem` (reduce total); then if wallet available > 0 and customer opts in, `hold` min(available, remaining_total) against the order; persist the applied amounts on the order (`coupon_id`, and a new `wallet_applied_aed Numeric(8,2) default 0` column — add in Task 14). COD due = total − coupon − wallet_applied.
- At delivery (status→delivered): `capture` the order's hold (idempotency_key `order:{id}:capture`).
- At cancel (before delivered): `release` the hold (idempotency_key `order:{id}:release`).

- [ ] **Step 1: Write failing tests**: confirm with AED 20 wallet on AED 60 order → COD due 40, balance still 50 until delivery; on delivered → balance 30; on cancel before delivery → available restored; coupon + wallet stack with coupon applied first; wallet hold never exceeds available.

- [ ] **Step 2–4:** wire into the confirm/cancel/deliver paths (find them via the FSM transition helper). Green. Add `wallet_applied_aed` to `Order` (and Task 14 migration).

- [ ] **Step 5: Commit** — `feat(ordering): apply coupon + wallet credit at confirm; capture/release on FSM`.

---

## Phase 5 — Reconciliation, Expiry, Abuse

### Task 16: Wallet expiry sweep (Celery beat)

**Files:**
- Create: `src/app/wallet/reconcile.py`; Modify: `apps/workers/celery_app.py`, `src/app/config.py`
- Test: `tests/wallet/test_expiry.py`

**Interfaces:**
- `expire_credits(session, *, restaurant_id, ttl_days) -> int` — for credits older than ttl with remaining unspent balance, post an `expiry` debit (idempotent per source entry) zeroing the lapsed amount; audited; returns count. Per-restaurant `ttl_days` from settings (0/None = no expiry). Beat task iterates tenants.

- [ ] Steps: failing test (a 100-day-old credit with no expiry stays; with ttl=90 it expires) → implement + register beat (Asia/Dubai) → green → commit `feat(wallet): per-tenant credit expiry sweep`.

### Task 17: Daily reconciliation + drift alert

**Files:**
- Modify: `src/app/wallet/reconcile.py`, `apps/workers/celery_app.py`
- Test: `tests/wallet/test_reconcile.py`

**Interfaces:**
- `reconcile_tenant(session, *, restaurant_id) -> dict` — independently re-sums ledger → outstanding liability; compares posted-sum vs (credits − debits − expiry) control total; returns `{liability, drift}`. Nonzero drift → manager/ops alert via outbox + Prometheus gauge. Mirrors `cod/service.py` shift recon.

- [ ] Steps: failing test (clean ledger → drift 0; tampered → drift detected) → implement + beat + metric → green → commit `feat(wallet): daily reconciliation + drift alert`.

### Task 18: Abuse / velocity flags + auto-freeze

**Files:**
- Create: `src/app/wallet/abuse.py`; Modify: `src/app/tickets/service.py`, `src/app/config.py`
- Test: `tests/wallet/test_abuse.py`

**Interfaces:**
- `refund_velocity(session, *, restaurant_id, customer_id, window_days) -> dict {count, total_aed}`; `check_and_flag(session, *, restaurant_id, customer_id) -> bool` — if over per-customer caps (settings: max refunds/30d, max AED/30d, new-account cap) → freeze account + audit + surface flag. Called from `resolve_wallet_refund` after crediting. Per-tenant daily compensation budget breach → alert + pause auto paths.

- [ ] Steps: failing tests (N+1 refund triggers freeze; under cap does not) → implement → green → commit `feat(wallet): refund velocity flags + auto-freeze`.

---

## Phase 6 — Manager Dashboard

### Task 19: Tickets API client + types

**Files:**
- Modify: `frontend/src/lib/types.ts`; Create: `frontend/src/lib/ticketsApi.ts`, `frontend/src/lib/walletApi.ts`
- Test: `frontend/src/lib/ticketsApi.test.ts`

- [ ] Steps: failing fetch test (mock) → `Ticket`, `WalletBalance`, `WalletEntry` types + `listTickets`, `getTicket`, `resolveTicket`, `getWallet` → green → commit `feat(web): tickets + wallet API clients and types`.

### Task 20: TicketDetailDrawer (three action buttons)

**Files:**
- Create: `frontend/src/components/TicketDetailDrawer.tsx` (+ `.module.css`, `.test.tsx`)

**Interfaces:** props `{ticket, onResolved}`. Renders complaint + order/customer summary + evidence; three buttons (Refund to Wallet with amount input, Send Replacement, Mark Resolved); required note field; calls `resolveTicket`. Reuse the `OrderDetailDrawer`/`SideDrawer` pattern.

- [ ] Steps: failing RTL test (clicking Refund without amount disabled; resolve calls api) → component → green → commit `feat(web): TicketDetailDrawer with three manager actions`.

### Task 21: TicketsScreen + nav badge

**Files:**
- Create: `frontend/src/screens/TicketsScreen.tsx` (+ css, test); Modify: `frontend/src/components/NavSidebar.tsx`, `frontend/src/App.tsx` (route)
- Test: `frontend/src/screens/TicketsScreen.test.tsx`

- [ ] Steps: failing test (renders open tickets first; opening a row shows drawer; badge shows open count) → screen + route + badge → green → commit `feat(web): Tickets screen + open-count nav badge`.

### Task 22: Wallet balance + history on CustomerProfileScreen

**Files:**
- Modify: `frontend/src/screens/CustomerProfileScreen.tsx` (+ test)

- [ ] Steps: failing test (shows balance + entry list) → wire `getWallet` → green → commit `feat(web): wallet balance + history on customer profile`.

---

## Phase 7 — Hardening Gate

### Task 23: Full test matrix + lint + graph update

- [ ] Run full suite: `.venv/bin/pytest -q` — all green.
- [ ] Lint: `.venv/bin/ruff check src apps tests` — clean.
- [ ] Frontend: `cd frontend && npm test` — green.
- [ ] Concurrency/load sanity: a test that fires N concurrent holds/redemptions and asserts no double-spend / no double-redeem (property: money conserved; balance == sum of ledger).
- [ ] Boot smoke: `.venv/bin/uvicorn app.main:app` starts; new routers mounted.
- [ ] `/graphify . --update`; verify no new AMBIGUOUS edges near `record_audit`, `ordering.service`, `conversation.engine`.
- [ ] Update `understanding.txt` with the dated summary of all phases.
- [ ] Commit — `chore: wallet/coupon/tickets hardening gate green`.

---

## Self-Review notes

- **Spec coverage:** wallet (ledger, hold/capture/release, freeze, reversal, expiry, reconcile, abuse) ✓; coupon (generalize, ledger, dup-proof, caps, kill-switch, entropy) ✓; tickets (model, 3 actions, AI-open-only) ✓; redemption + dup-prevention (Task 4, 9, 15) ✓; multi-tenant isolation (every router task has a cross-tenant test) ✓; COD interaction (Task 15) ✓; dashboard (19–22) ✓; regulatory note — store-credit-only, no cash-out, is enforced by NOT building a withdrawal path (documented in design doc §7).
- **Money unit:** plan uses `Numeric(10,2)`/`Decimal` (house convention), not integer fils — deliberate deviation from design doc §2.9 for codebase consistency; balance still derived, idempotency unchanged.
- **Capture netting:** Task 4's code sketch contains a deliberate "make the tests pass" note — the five tests in Task 4 Step 1 are the contract; the implementer must land a netting model where capture drops balance by X and release leaves balance unchanged. This is the one place to slow down.
- **Type consistency:** `credit/hold/capture/release` signatures in Task 3–4 match their callers in Task 12 (`resolve_wallet_refund`) and Task 15 (ordering). `validate_and_redeem` signature in Task 9 matches its Task 15 caller.
```
