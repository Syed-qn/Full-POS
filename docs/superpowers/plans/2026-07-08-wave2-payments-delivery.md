# Wave 2: Payments + Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the payments/billing gaps (WS-PAY, Category 5) and delivery-management gaps (WS-DELIVERY, Category 7) identified in `docs/POS_100_FEATURE_AUDIT_2026-07-08.md`, per the scope locked in `docs/superpowers/plans/2026-07-08-pos-100pct-roadmap.md`.

**Architecture:** Two independent workstreams, run by 2 parallel agents. WS-PAY is scoped entirely inside `src/app/payments/` plus new frontend files — it does **not** modify `src/app/ordering/models.py` (checkout charges are recorded in a new `CheckoutCharge` table inside `payments/models.py`, not new `Order` columns, specifically so the two tracks never touch the same backend model file). WS-DELIVERY touches `src/app/ordering/*` (address `floor` field), `src/app/cod/service.py`, `src/app/dispatch/*`, `src/app/reports/*`, and `rider-app/`. **Backend files are fully disjoint between the two tracks** — verified below.

**Tech Stack:** FastAPI + SQLAlchemy 2 async (backend), React + TypeScript + Vitest/Testing Library (manager dashboard frontend), Expo/React Native (rider-app, no test harness — see Task WD-3), pytest + anyio (backend tests), Celery (`apps/workers/celery_app.py`) for the WS-PAY reconciliation job.

## Global Constraints

- Money: `Decimal`/`Numeric(8,2)`, AED. Times: UTC in DB, Asia/Dubai for Celery beat schedules (existing `celery_app.conf.update(timezone="Asia/Dubai")`).
- Routers never touch other modules' models — call services.
- Every mutating backend action that changes state must call `app.audit.service.record_audit` in the same transaction where the action is a first-class business event (credit note issuance, deposit charge) — informational/no-op-adjacent actions (checkout-charge calc) do not require it, matching existing conventions (e.g. `charge_tender` itself has no audit call today).
- Tests use `Base.metadata.create_all` (see `tests/conftest.py`), **not** real alembic migrations — a new model in an already-imported module (e.g. `app.payments.models`, `app.ordering.models`) needs **no** new import added to `tests/conftest.py` or `alembic/env.py`. Only add a migration for production parity (Task WP-3, WD-1) using the exact pattern in `alembic/versions/040d78934696_cash_drawer_tables.py`.
- Frontend: reuse `apiClient` (`frontend/src/lib/apiClient.ts` — `.get<T>()`, `.post<T>()`, `.put<T>()`, `.delete<T>()`), `PageHeader`, `Button`, `Toaster`/`toast()` components. Match `StaffScreen.tsx` structure (load state, error state, empty state, form, table) — the closest already-merged example of this exact pattern.
- Commit per task, conventional-commit style (`feat:`, `fix:`, `chore:`).
- Test commands: backend `.venv/bin/pytest tests/payments/ -v` / `.venv/bin/pytest tests/dispatch/ tests/cod/ tests/ordering/ tests/reports/ -v` (requires docker db up, `docker compose up -d`); frontend `cd frontend && npm test -- CashDrawerScreen` / `npm test -- DriverPerformanceScreen` / `npm test -- NewOrderScreen`.

## Coordination points (read before starting either track)

1. **Backend files are fully disjoint** — WS-PAY only touches files under `src/app/payments/`, `alembic/versions/`, `apps/workers/celery_app.py`, `tests/payments/`. WS-DELIVERY only touches `src/app/ordering/{models,schemas,service,router}.py`, `src/app/cod/service.py`, `src/app/dispatch/{rider_app_router.py,delivery_proof_storage.py}`, `src/app/reports/{analytics,router}.py`, `rider-app/`, `tests/{ordering,cod,dispatch,reports}/`. No file overlap — **both tracks can run fully in parallel with no worktree needed for the backend.**
2. **Frontend shares 3 files, exactly like Wave 1's `types.ts` collision** — `frontend/src/App.tsx`, `frontend/src/components/NavSidebar.tsx`, and `frontend/src/lib/types.ts` are each edited by one task in *both* tracks (WP-7 and WD-4). Whichever track's frontend task lands second must rebase past the first's edits (both edits are pure appends to a route list / nav array / type-file tail, so conflicts are mechanical, not semantic — same situation Wave 1 resolved with a worktree). **Recommendation: run WS-PAY's frontend task (WP-7) and WS-DELIVERY's frontend task (WD-4) in a separate git worktree for whichever one starts second**, per `superpowers:using-git-worktrees`.
3. **`docs/superpowers/plans/2026-07-08-wave1-staff-reports-frontend.md` (Task 7) also adds a Z-report section to a `ReportsScreen.tsx`.** As of this plan being written, `frontend/src/screens/ReportsScreen.tsx` does **not** exist on `main` yet (verified: no such file, `NavSidebar.tsx`'s "Reports" nav item still points at `/analytics`) — Wave 1 is still in review. WP-7 below creates a **separate** `CashDrawerScreen.tsx` (drawer session open/cash-in/cash-out/close + a same-day Z-report readout) that does not depend on `ReportsScreen.tsx` existing. If Wave 1's `ReportsScreen.tsx` merges before or during Wave 2, the two Z-report UIs are complementary, not duplicates (`CashDrawerScreen` adds the session actions Wave 1's read-only panel doesn't have) — no rework needed, but consider merging them into one screen as a follow-up cleanup.
4. **Open question for a human before executing (found during ground-truth verification, not present in the audit doc):** several git worktrees under `.claude/worktrees/` contain **uncommitted, unmerged** implementations that overlap this plan's scope:
   - `.claude/worktrees/agent-ade2386b3fdc70ec4` (branch `worktree-agent-ade2386b3fdc70ec4`) has an uncommitted `CreditNote` model, deposit tender, house-account charge/enable/settle, and duplicate-charge detection in `src/app/payments/{models,service,router,schemas}.py`, with matching tests in `tests/payments/test_{credit_note,deposit,duplicate_detection,house_account}.py`.
   - `.claude/worktrees/agent-a9d68565326ba6802` (branch `worktree-agent-a9d68565326ba6802`) has an uncommitted `driver_performance_report` in `src/app/reports/analytics.py` + `/api/v1/reports/driver-performance` endpoint, plus an unrelated `mark_delivery_failed`/`delivery-failed` endpoint (that item is already audited FULL — out of scope here), with matching tests in `tests/reports/test_driver_performance.py` and `tests/dispatch/test_delivery_failure*.py`.

   Neither branch is committed or merged to `main`. **Decide before dispatching agents**: (a) review and merge one or both branches first (likely faster — the code looked complete with tests, though untested for actually passing here), in which case skip the overlapping steps below (WP-3 credit note, WP-4 deposit, WD-4's driver-performance backend half) and only run the remaining steps; or (b) treat those branches as reference-only/abandoned and let this plan's tasks re-implement from scratch on `main` as written (this plan's credit-note design is intentionally simpler — no advisory-lock number allocation — so it is **not** a byte-for-byte match with that branch; do not cherry-pick code from it without reading it fresh, it may not match the schema this plan builds). This plan is written assuming (b) — every task below is self-contained against current `main` and does not require either branch.

---

# WS-PAY

## Task WP-1: Tap-to-pay flag on `PaymentTransaction`

**Files:**
- Modify: `src/app/payments/models.py`
- Modify: `src/app/payments/schemas.py`
- Modify: `src/app/payments/service.py`
- Modify: `src/app/payments/router.py`
- Test: `tests/payments/test_service.py`
- Test: `tests/payments/test_router.py`

**Interfaces:**
- Consumes: existing `charge_tender(session, *, restaurant_id, order_id, tender_type, amount_aed, tip_aed, gateway)` (`src/app/payments/service.py`).
- Produces: `charge_tender(..., is_tap_to_pay: bool = False)`, `PaymentTransaction.is_tap_to_pay: bool`, `ChargeIn.is_tap_to_pay: bool = False`.

- [ ] **Step 1: Write the failing test**

Append to `tests/payments/test_service.py`:

```python
@pytest.mark.anyio
async def test_charge_tender_records_tap_to_pay_flag(db_session, restaurant):
    from decimal import Decimal as D

    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000601", name="Tap Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="PAY-0601",
        status="confirmed", subtotal=D("30.00"), total=D("30.00"),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    txn = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="card", amount_aed=Decimal("30.00"), tip_aed=Decimal("0.00"),
        gateway=MockPaymentProcessor(), is_tap_to_pay=True,
    )
    await db_session.commit()
    assert txn.is_tap_to_pay is True
```

Append to `tests/payments/test_router.py`:

```python
@pytest.mark.anyio
async def test_charge_router_records_tap_to_pay_flag(client, auth_headers, db_session):
    from decimal import Decimal

    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order
    from app.payments.models import PaymentTransaction

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000602", name="Tap Router")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="RTR-0602",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.commit()

    charge = await client.post(
        "/api/v1/payments/charge",
        json={"order_id": order.id, "tender_type": "card", "amount_aed": "20.00", "is_tap_to_pay": True},
        headers=auth_headers,
    )
    assert charge.status_code == 201
    txn = await db_session.get(PaymentTransaction, charge.json()["id"])
    assert txn.is_tap_to_pay is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/payments/test_service.py tests/payments/test_router.py -v -k tap_to_pay`
Expected: FAIL — `TypeError: charge_tender() got an unexpected keyword argument 'is_tap_to_pay'`.

- [ ] **Step 3: Add the column**

In `src/app/payments/models.py`, add after `provider_charge_id`:

```python
    is_tap_to_pay: Mapped[bool] = mapped_column(default=False)
```

(Import `Boolean` is not required — SQLAlchemy 2's `Mapped[bool]` infers the column type without an explicit `Boolean()`; every other model in this codebase that does this, e.g. `identity/models.py:Rider.on_duty`, imports `Boolean` explicitly for `server_default=text(...)` cases only. This column needs no server default, so leave the import list unchanged.)

- [ ] **Step 4: Thread the flag through `service.py`**

In `src/app/payments/service.py`, change the `charge_tender` signature and body:

```python
async def charge_tender(
    session: AsyncSession, *, restaurant_id: int, order_id: int, tender_type: str,
    amount_aed: Decimal, tip_aed: Decimal, gateway: PaymentPort, is_tap_to_pay: bool = False,
) -> PaymentTransaction:
    txn = PaymentTransaction(
        restaurant_id=restaurant_id, order_id=order_id, tender_type=tender_type,
        amount_aed=amount_aed, tip_aed=tip_aed, status="pending", is_tap_to_pay=is_tap_to_pay,
    )
```

(Only the `PaymentTransaction(...)` constructor call and the signature line change — the rest of the function body is unchanged.)

- [ ] **Step 5: Wire the flag through the schema and router**

In `src/app/payments/schemas.py`, add to `ChargeIn`:

```python
class ChargeIn(BaseModel):
    order_id: int
    tender_type: str  # cash | card | apple_pay | google_pay | wallet | deposit
    amount_aed: Decimal
    tip_aed: Decimal = Decimal("0.00")
    is_tap_to_pay: bool = False
```

In `src/app/payments/router.py`, add `is_tap_to_pay=body.is_tap_to_pay` to the `charge_tender(...)` call inside `charge()`:

```python
        txn = await charge_tender(
            session, restaurant_id=restaurant.id, order_id=body.order_id, tender_type=body.tender_type,
            amount_aed=body.amount_aed, tip_aed=body.tip_aed, gateway=gateway,
            is_tap_to_pay=body.is_tap_to_pay,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/payments/test_service.py tests/payments/test_router.py -v`
Expected: PASS (all tests, including pre-existing ones).

- [ ] **Step 7: Commit**

```bash
git add src/app/payments/models.py src/app/payments/schemas.py src/app/payments/service.py src/app/payments/router.py tests/payments/test_service.py tests/payments/test_router.py
git commit -m "feat(payments): add tap-to-pay flag to PaymentTransaction"
```

---

## Task WP-2: Service charge, packaging fee, minimum-order fee

**Files:**
- Modify: `src/app/payments/models.py`
- Create: `src/app/payments/charges.py`
- Modify: `src/app/payments/router.py`
- Test: `tests/payments/test_charges.py`

**Interfaces:**
- Consumes: `Restaurant.settings` dict (existing JSON column, same pattern as `payments/credentials.py`), `app.ordering.models.Order` (read/increment `.total`, `.subtotal` — read only, never adds a column to it), `app.ordering.models.OrderItem` (read `.qty`/`.cancelled` to count items).
- Produces: `CheckoutCharge` model (`restaurant_id`, `order_id`, `charge_type`, `amount_aed`); `compute_service_charge(subtotal_aed, restaurant) -> Decimal`, `compute_packaging_fee(item_count, restaurant) -> Decimal`, `compute_minimum_order_fee(subtotal_aed, restaurant) -> Decimal`, `apply_checkout_charges(session, *, restaurant, order) -> list[CheckoutCharge]` (all in `charges.py`); `POST /api/v1/payments/orders/{order_id}/apply-charges`.

- [ ] **Step 1: Write the failing test**

Create `tests/payments/test_charges.py`:

```python
from decimal import Decimal

import pytest

from app.payments.charges import (
    apply_checkout_charges,
    compute_minimum_order_fee,
    compute_packaging_fee,
    compute_service_charge,
)


def _restaurant_with_settings(restaurant, **settings):
    restaurant.settings = {**restaurant.settings, **settings}
    return restaurant


@pytest.mark.anyio
async def test_compute_service_charge_applies_percentage(db_session, restaurant):
    r = _restaurant_with_settings(restaurant, service_charge_pct=10)
    assert compute_service_charge(Decimal("100.00"), r) == Decimal("10.00")


@pytest.mark.anyio
async def test_compute_service_charge_zero_when_unset(db_session, restaurant):
    assert compute_service_charge(Decimal("100.00"), restaurant) == Decimal("0.00")


@pytest.mark.anyio
async def test_compute_packaging_fee_per_item(db_session, restaurant):
    r = _restaurant_with_settings(restaurant, packaging_fee_per_item_aed="1.50")
    assert compute_packaging_fee(3, r) == Decimal("4.50")


@pytest.mark.anyio
async def test_compute_minimum_order_fee_below_threshold(db_session, restaurant):
    r = _restaurant_with_settings(
        restaurant, minimum_order_threshold_aed="30.00", minimum_order_fee_aed="5.00",
    )
    assert compute_minimum_order_fee(Decimal("20.00"), r) == Decimal("5.00")


@pytest.mark.anyio
async def test_compute_minimum_order_fee_waived_at_or_above_threshold(db_session, restaurant):
    r = _restaurant_with_settings(
        restaurant, minimum_order_threshold_aed="30.00", minimum_order_fee_aed="5.00",
    )
    assert compute_minimum_order_fee(Decimal("30.00"), r) == Decimal("0.00")


@pytest.mark.anyio
async def test_apply_checkout_charges_adds_to_order_total_and_is_idempotent(db_session, restaurant):
    from app.ordering.models import Customer, Order, OrderItem

    r = _restaurant_with_settings(
        restaurant, service_charge_pct=10, packaging_fee_per_item_aed="1.00",
    )
    cust = Customer(restaurant_id=r.id, phone="+971500000701", name="Charges Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=r.id, customer_id=cust.id, order_number="CHG-0001",
        status="confirmed", subtotal=Decimal("100.00"), total=Decimal("100.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=1, dish_number=1, dish_name="Test Dish",
        price_aed=Decimal("50.00"), qty=2,
    ))
    await db_session.commit()

    charges = await apply_checkout_charges(db_session, restaurant=r, order=order)
    await db_session.commit()
    assert {c.charge_type for c in charges} == {"service_charge", "packaging_fee"}
    assert order.total == Decimal("112.00")  # 100 + 10 (10%) + 2 (2 items * 1.00)

    # Re-applying (e.g. order re-priced before payment) must not double-count.
    charges_again = await apply_checkout_charges(db_session, restaurant=r, order=order)
    await db_session.commit()
    assert order.total == Decimal("112.00")
    assert len(charges_again) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/payments/test_charges.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.payments.charges'`.

- [ ] **Step 3: Add `CheckoutCharge` model**

In `src/app/payments/models.py`, add at the end of the file:

```python
class CheckoutCharge(Base, TimestampMixin):
    """A till-checkout charge (service charge / packaging fee / minimum-order
    fee) applied to an order. Kept in its own table rather than new Order
    columns so app.payments never needs to modify app.ordering.models —
    order.total is still the single source of truth for what's owed; this
    table is the itemised breakdown of what makes it up beyond food + delivery.
    """

    __tablename__ = "checkout_charges"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    charge_type: Mapped[str] = mapped_column(String(24))  # service_charge | packaging_fee | minimum_order_fee
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
```

- [ ] **Step 4: Implement `charges.py`**

Create `src/app/payments/charges.py`:

```python
"""Till-checkout charges: service charge, packaging fee, minimum-order fee.

Configured per-restaurant via Restaurant.settings (same JSON-settings pattern
as app.payments.credentials) so each tenant opts in/out and sets its own
rates without a schema change. Amounts are recorded as CheckoutCharge rows
(one per charge type actually applied) and added onto the existing
Order.total column — app.ordering.models.Order is read/updated here but
never altered (no new column), so this module stays fully self-contained
inside app.payments.
"""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.payments.models import CheckoutCharge


def compute_service_charge(subtotal_aed: Decimal, restaurant: Restaurant) -> Decimal:
    pct = Decimal(str(restaurant.settings.get("service_charge_pct", 0)))
    if pct <= 0:
        return Decimal("0.00")
    return (subtotal_aed * pct / Decimal("100")).quantize(Decimal("0.01"))


def compute_packaging_fee(item_count: int, restaurant: Restaurant) -> Decimal:
    per_item = Decimal(str(restaurant.settings.get("packaging_fee_per_item_aed", 0)))
    if per_item <= 0 or item_count <= 0:
        return Decimal("0.00")
    return (per_item * item_count).quantize(Decimal("0.01"))


def compute_minimum_order_fee(subtotal_aed: Decimal, restaurant: Restaurant) -> Decimal:
    threshold = Decimal(str(restaurant.settings.get("minimum_order_threshold_aed", 0)))
    fee = Decimal(str(restaurant.settings.get("minimum_order_fee_aed", 0)))
    if threshold <= 0 or fee <= 0 or subtotal_aed >= threshold:
        return Decimal("0.00")
    return fee.quantize(Decimal("0.01"))


async def _item_count(session: AsyncSession, *, order_id: int) -> int:
    from app.ordering.models import OrderItem

    total = await session.scalar(
        select(func.coalesce(func.sum(OrderItem.qty), 0)).where(
            OrderItem.order_id == order_id, OrderItem.cancelled.is_(False),
        )
    )
    return int(total)


async def apply_checkout_charges(
    session: AsyncSession, *, restaurant: Restaurant, order,
) -> list[CheckoutCharge]:
    """Compute + persist checkout charges for `order`, adding them onto
    order.total. Idempotent per order: re-running clears any previously
    applied charges for this order first (e.g. the order was modified and
    re-priced before payment), so total never double-counts. Caller commits.
    """
    existing = (await session.scalars(
        select(CheckoutCharge).where(CheckoutCharge.order_id == order.id)
    )).all()
    previous_total = sum((c.amount_aed for c in existing), Decimal("0.00"))
    for c in existing:
        await session.delete(c)
    order.total -= previous_total

    item_count = await _item_count(session, order_id=order.id)
    candidates = {
        "service_charge": compute_service_charge(order.subtotal, restaurant),
        "packaging_fee": compute_packaging_fee(item_count, restaurant),
        "minimum_order_fee": compute_minimum_order_fee(order.subtotal, restaurant),
    }
    charges = [
        CheckoutCharge(restaurant_id=restaurant.id, order_id=order.id, charge_type=t, amount_aed=amt)
        for t, amt in candidates.items() if amt > 0
    ]
    for c in charges:
        session.add(c)
    order.total += sum((c.amount_aed for c in charges), Decimal("0.00"))
    await session.flush()
    return charges
```

- [ ] **Step 5: Add the router endpoint**

In `src/app/payments/router.py`, add the import and endpoint:

```python
from app.payments.charges import apply_checkout_charges
```

```python
@router.post("/orders/{order_id}/apply-charges")
async def apply_charges(
    order_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")
    charges = await apply_checkout_charges(session, restaurant=restaurant, order=order)
    await session.commit()
    return {
        "order_id": order.id,
        "order_total_aed": str(order.total),
        "charges": [{"charge_type": c.charge_type, "amount_aed": str(c.amount_aed)} for c in charges],
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/payments/test_charges.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/app/payments/models.py src/app/payments/charges.py src/app/payments/router.py tests/payments/test_charges.py
git commit -m "feat(payments): add service charge, packaging fee, and minimum-order fee"
```

---

## Task WP-3: Credit note

**Files:**
- Modify: `src/app/payments/models.py`
- Modify: `src/app/payments/schemas.py`
- Create: `src/app/payments/credit_notes.py`
- Modify: `src/app/payments/router.py`
- Test: `tests/payments/test_credit_notes.py`

**Interfaces:**
- Consumes: `PaymentTransaction` (existing), `app.audit.service.record_audit`.
- Produces: `CreditNote` model; `CreditNoteExceedsRefundError`, `TransactionNotFoundError` (both `Exception` subclasses); `issue_credit_note(session, *, restaurant_id, transaction_id, amount_aed, reason=None) -> CreditNote`; `POST /api/v1/payments/{transaction_id}/credit-note`.

- [ ] **Step 1: Write the failing test**

Create `tests/payments/test_credit_notes.py`:

```python
from decimal import Decimal

import pytest

from app.payments.credit_notes import (
    CreditNoteExceedsRefundError,
    TransactionNotFoundError,
    issue_credit_note,
)
from app.payments.mock import MockPaymentProcessor
from app.payments.service import charge_tender, refund_transaction


async def _seed_refunded_txn(db_session, restaurant, amount=Decimal("50.00"), refund=Decimal("50.00")):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000801", name="Credit Note Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="CN-0001",
        status="confirmed", subtotal=amount, total=amount,
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    gw = MockPaymentProcessor()
    txn = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="card", amount_aed=amount, tip_aed=Decimal("0.00"), gateway=gw,
    )
    await db_session.commit()
    await refund_transaction(
        db_session, transaction_id=txn.id, restaurant_id=restaurant.id, amount_aed=refund, gateway=gw,
    )
    await db_session.commit()
    return order, txn


@pytest.mark.anyio
async def test_issue_credit_note_for_refunded_amount(db_session, restaurant):
    order, txn = await _seed_refunded_txn(db_session, restaurant)
    note = await issue_credit_note(
        db_session, restaurant_id=restaurant.id, transaction_id=txn.id,
        amount_aed=Decimal("50.00"), reason="Customer complaint",
    )
    await db_session.commit()
    assert note.order_id == order.id
    assert note.transaction_id == txn.id
    assert note.credit_note_number.startswith(f"CN-{restaurant.id}-")
    assert note.reason == "Customer complaint"


@pytest.mark.anyio
async def test_issue_credit_note_exceeding_refund_rejected(db_session, restaurant):
    order, txn = await _seed_refunded_txn(db_session, restaurant, amount=Decimal("50.00"), refund=Decimal("20.00"))
    with pytest.raises(CreditNoteExceedsRefundError):
        await issue_credit_note(
            db_session, restaurant_id=restaurant.id, transaction_id=txn.id, amount_aed=Decimal("30.00"),
        )


@pytest.mark.anyio
async def test_issue_credit_note_unknown_transaction_rejected(db_session, restaurant):
    with pytest.raises(TransactionNotFoundError):
        await issue_credit_note(
            db_session, restaurant_id=restaurant.id, transaction_id=999999, amount_aed=Decimal("10.00"),
        )


@pytest.mark.anyio
async def test_credit_note_router_endpoint(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    order, txn = await _seed_refunded_txn(db_session, restaurant)

    resp = await client.post(
        f"/api/v1/payments/{txn.id}/credit-note",
        json={"amount_aed": "50.00", "reason": "Refund documentation"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["credit_note_number"].startswith(f"CN-{restaurant.id}-")
    assert body["order_id"] == order.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/payments/test_credit_notes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.payments.credit_notes'`.

- [ ] **Step 3: Add the `CreditNote` model**

In `src/app/payments/models.py`, add `datetime` to imports and add the model at the end:

```python
from datetime import datetime
```

```python
class CreditNote(Base, TimestampMixin):
    """A formal credit-note artifact documenting an already-issued refund
    (UAE compliance / accounting requirement — a refund transaction alone
    isn't a customer-facing document). ``amount_aed`` may not exceed the
    linked transaction's ``refunded_amount_aed`` — a credit note can only
    document money that was actually returned.
    """

    __tablename__ = "credit_notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("payment_transactions.id"), index=True)
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    reason: Mapped[str | None] = mapped_column(String(256))
    credit_note_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Add `DateTime` to the `sqlalchemy` import line at the top of the file (it currently reads `from sqlalchemy import BigInteger, ForeignKey, Numeric, String` — extend it):

```python
from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
```

- [ ] **Step 4: Implement `credit_notes.py`**

Create `src/app/payments/credit_notes.py`:

```python
"""Credit notes: a formal document issued against an already-refunded
PaymentTransaction (UAE compliance — a refund alone isn't a customer-facing
accounting artifact). Number allocation is a simple id-derived scheme
(``CN-{restaurant_id}-{note.id:06d}``) — the note row's own primary key is
already unique per flush, so no advisory-lock/retry dance is needed (unlike
``Order.order_number``, which must be predictable/gap-free for VAT invoice
sequencing before the row exists — a credit note number has no such
pre-allocation requirement).
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.models import CreditNote, PaymentTransaction


class TransactionNotFoundError(Exception):
    pass


class CreditNoteExceedsRefundError(Exception):
    pass


async def issue_credit_note(
    session: AsyncSession, *, restaurant_id: int, transaction_id: int,
    amount_aed: Decimal, reason: str | None = None,
) -> CreditNote:
    txn = await session.get(PaymentTransaction, transaction_id)
    if txn is None or txn.restaurant_id != restaurant_id:
        raise TransactionNotFoundError(f"transaction {transaction_id} not found")
    if amount_aed > txn.refunded_amount_aed:
        raise CreditNoteExceedsRefundError(
            f"cannot issue a {amount_aed} AED credit note against only "
            f"{txn.refunded_amount_aed} AED refunded"
        )

    note = CreditNote(
        restaurant_id=restaurant_id,
        order_id=txn.order_id,
        transaction_id=txn.id,
        amount_aed=amount_aed,
        reason=reason,
        credit_note_number="",  # placeholder until flush assigns note.id
        issued_at=datetime.now(timezone.utc),
    )
    session.add(note)
    await session.flush()
    note.credit_note_number = f"CN-{restaurant_id}-{note.id:06d}"
    await session.flush()
    return note
```

- [ ] **Step 5: Add the schema and router endpoint**

In `src/app/payments/schemas.py`, add:

```python
class CreditNoteIn(BaseModel):
    amount_aed: Decimal
    reason: str | None = None
```

In `src/app/payments/router.py`, add imports and endpoint:

```python
from app.payments.credit_notes import CreditNoteExceedsRefundError, TransactionNotFoundError, issue_credit_note
from app.payments.schemas import ChargeIn, CreditNoteIn, CredentialsIn, RefundIn
```

```python
@router.post("/{transaction_id}/credit-note", status_code=status.HTTP_201_CREATED)
async def create_credit_note(
    transaction_id: int,
    body: CreditNoteIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        note = await issue_credit_note(
            session, restaurant_id=restaurant.id, transaction_id=transaction_id,
            amount_aed=body.amount_aed, reason=body.reason,
        )
    except TransactionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CreditNoteExceedsRefundError as exc:
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/payments/test_credit_notes.py -v`
Expected: PASS.

- [ ] **Step 7: Add the migration**

Create `alembic/versions/` migration (autogenerate then hand-verify against the `040d78934696_cash_drawer_tables.py` pattern for the `updated_at` trigger):

```bash
.venv/bin/alembic revision --autogenerate -m "credit notes and checkout charges"
```

Open the generated file and confirm it creates `credit_notes` and `checkout_charges` tables with the exact columns above; then add, right before `def downgrade():`, matching the cash-drawer migration's trigger pattern:

```python
    for tbl in ('credit_notes', 'checkout_charges'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )
```

And inside `def downgrade():`, before the `op.drop_table(...)` calls:

```python
    for tbl in ('credit_notes', 'checkout_charges'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")
```

Run: `.venv/bin/alembic upgrade head`
Expected: migration applies cleanly against the dev DB.

- [ ] **Step 8: Commit**

```bash
git add src/app/payments/models.py src/app/payments/schemas.py src/app/payments/credit_notes.py src/app/payments/router.py tests/payments/test_credit_notes.py alembic/versions/
git commit -m "feat(payments): add credit notes"
```

---

## Task WP-4: Deposit / advance payment tender type

**Files:**
- Modify: `src/app/payments/router.py`
- Test: `tests/payments/test_deposit.py`

**Interfaces:**
- Consumes: `charge_tender(...)` (Task WP-1's signature), `total_paid(session, *, order_id) -> Decimal` (both already exist in `service.py` unchanged).
- Produces: `POST /api/v1/payments/orders/{order_id}/deposit`. No new tender-type enum enforcement needed — `charge_tender`'s `tender_type` is a free-form `String(16)` column already; `"deposit"` is simply a new value routed through the existing cash/wallet branch (not in `_GATEWAY_TENDERS`, so it settles immediately with no PSP call, same as cash).

- [ ] **Step 1: Write the failing test**

Create `tests/payments/test_deposit.py`:

```python
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_deposit_router_records_transaction_and_counts_toward_total_paid(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000901", name="Deposit Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="DEP-0001",
        status="pending_confirmation", subtotal=Decimal("200.00"), total=Decimal("200.00"),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/payments/orders/{order.id}/deposit",
        json={"amount_aed": "50.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["amount_aed"] == "50.00"

    from app.payments.service import total_paid

    paid = await total_paid(db_session, order_id=order.id)
    assert paid == Decimal("50.00")


@pytest.mark.anyio
async def test_deposit_router_404_unknown_order(client, auth_headers):
    resp = await client.post(
        "/api/v1/payments/orders/999999/deposit",
        json={"amount_aed": "10.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/payments/test_deposit.py -v`
Expected: FAIL — 404 route not found (`/api/v1/payments/orders/{order_id}/deposit` doesn't exist yet).

- [ ] **Step 3: Add the schema and router endpoint**

In `src/app/payments/schemas.py`, add:

```python
class DepositIn(BaseModel):
    amount_aed: Decimal
```

In `src/app/payments/router.py`, add the endpoint:

```python
@router.post("/orders/{order_id}/deposit", status_code=status.HTTP_201_CREATED)
async def deposit(
    order_id: int,
    body: DepositIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail=f"order {order_id} not found")

    gateway = get_payment_port(restaurant)
    try:
        txn = await charge_tender(
            session, restaurant_id=restaurant.id, order_id=order_id, tender_type="deposit",
            amount_aed=body.amount_aed, tip_aed=Decimal("0.00"), gateway=gateway,
        )
    except PaymentFailedError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    await session.commit()
    return {"id": txn.id, "status": txn.status, "amount_aed": str(txn.amount_aed)}
```

Add `Decimal` to the top-of-file imports if not already present (`payments/router.py` currently has no `from decimal import Decimal` — add it) and add `DepositIn` to the `from app.payments.schemas import ...` line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/payments/test_deposit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/payments/schemas.py src/app/payments/router.py tests/payments/test_deposit.py
git commit -m "feat(payments): add deposit/advance payment endpoint"
```

---

## Task WP-5: Confirm duplicate-payment idempotency-key wiring on `/payments/charge`

**Files:**
- Test: `tests/payments/test_idempotency.py`

**Interfaces:**
- Consumes: existing `app.idempotency.middleware.IdempotencyMiddleware` (already mounted globally in `src/app/main.py:161`, `app.add_middleware(IdempotencyMiddleware)`) — **no production code changes**, this task is a confirming test only, per the roadmap's exact wording ("duplicate-payment idempotency-key wiring **confirmed** on `/payments/charge`").

- [ ] **Step 1: Write the test**

Create `tests/payments/test_idempotency.py`:

```python
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_repeated_charge_with_same_idempotency_key_is_not_double_applied(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500001001", name="Idempotency Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="IDEM-0001",
        status="confirmed", subtotal=Decimal("40.00"), total=Decimal("40.00"),
    )
    db_session.add(order)
    await db_session.commit()

    headers = {**auth_headers, "Idempotency-Key": "till-charge-retry-001"}
    payload = {"order_id": order.id, "tender_type": "cash", "amount_aed": "40.00"}

    first = await client.post("/api/v1/payments/charge", json=payload, headers=headers)
    assert first.status_code == 201
    second = await client.post("/api/v1/payments/charge", json=payload, headers=headers)
    assert second.status_code == 201
    # Same transaction id both times — the second call never re-hit charge_tender.
    assert first.json()["id"] == second.json()["id"]

    from app.payments.service import total_paid

    paid = await total_paid(db_session, order_id=order.id)
    assert paid == Decimal("40.00")  # not 80.00 — proves it wasn't double-charged


@pytest.mark.anyio
async def test_charge_without_idempotency_key_is_not_deduped(client, auth_headers, db_session):
    """Sanity check: two genuinely separate charges (no key) both apply —
    proves the dedup above is driven by the header, not accidental caching."""
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500001002", name="No Key Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="IDEM-0002",
        status="confirmed", subtotal=Decimal("40.00"), total=Decimal("40.00"),
    )
    db_session.add(order)
    await db_session.commit()

    payload = {"order_id": order.id, "tender_type": "cash", "amount_aed": "20.00"}
    first = await client.post("/api/v1/payments/charge", json=payload, headers=auth_headers)
    second = await client.post("/api/v1/payments/charge", json=payload, headers=auth_headers)
    assert first.json()["id"] != second.json()["id"]

    from app.payments.service import total_paid

    paid = await total_paid(db_session, order_id=order.id)
    assert paid == Decimal("40.00")  # both 20.00 charges applied
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/pytest tests/payments/test_idempotency.py -v`
Expected: PASS immediately — this confirms existing behavior. **If either test fails**, that is a real bug in `IdempotencyMiddleware` or the `/payments/charge` route (not expected per the code read during planning — `IdempotencyMiddleware` is method+path+key+restaurant scoped and mounted globally) — stop and investigate via `superpowers:systematic-debugging` rather than patching around it.

- [ ] **Step 3: Commit**

```bash
git add tests/payments/test_idempotency.py
git commit -m "test(payments): confirm idempotency-key dedup on /payments/charge"
```

---

## Task WP-6: PSP ↔ `PaymentTransaction` reconciliation job

**Files:**
- Modify: `src/app/payments/port.py`
- Modify: `src/app/payments/mock.py`
- Modify: `src/app/payments/stripe_gateway.py`
- Create: `src/app/payments/reconcile.py`
- Create: `src/app/payments/worker.py`
- Modify: `apps/workers/celery_app.py`
- Test: `tests/payments/test_reconcile.py`

**Interfaces:**
- Consumes: `PaymentTransaction` (existing), `PaymentPort` protocol (existing, extended below), `app.payments.factory.get_payment_port(restaurant)`.
- Produces: `PaymentPort.get_charge_status(*, provider_charge_id) -> str` (new protocol method); `reconcile_transactions(session, *, restaurant_id, gateway, lookback_days=7) -> list[dict]`; Celery task `payments.reconcile_all_tenants`.

- [ ] **Step 1: Write the failing test**

Create `tests/payments/test_reconcile.py`:

```python
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.payments.mock import MockPaymentProcessor
from app.payments.reconcile import reconcile_transactions
from app.payments.service import charge_tender


@dataclass
class _FakeGateway:
    """MockPaymentProcessor that also implements get_charge_status, returning
    a caller-configured status per provider_charge_id (defaults to succeeded
    for anything not explicitly overridden)."""

    overrides: dict = field(default_factory=dict)

    async def charge(self, *, amount_aed, tender_type, reference):
        return await MockPaymentProcessor().charge(amount_aed=amount_aed, tender_type=tender_type, reference=reference)

    async def refund(self, *, provider_charge_id, amount_aed):
        return await MockPaymentProcessor().refund(provider_charge_id=provider_charge_id, amount_aed=amount_aed)

    async def get_charge_status(self, *, provider_charge_id: str) -> str:
        return self.overrides.get(provider_charge_id, "succeeded")


async def _seed_txn(db_session, restaurant, gateway):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone="+971500001101", name="Reconcile Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="REC-0001",
        status="confirmed", subtotal=Decimal("60.00"), total=Decimal("60.00"),
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    txn = await charge_tender(
        db_session, restaurant_id=restaurant.id, order_id=order.id,
        tender_type="card", amount_aed=Decimal("60.00"), tip_aed=Decimal("0.00"), gateway=gateway,
    )
    await db_session.commit()
    return txn


@pytest.mark.anyio
async def test_reconcile_finds_no_mismatch_when_psp_agrees(db_session, restaurant):
    gw = _FakeGateway()
    await _seed_txn(db_session, restaurant, gw)
    mismatches = await reconcile_transactions(db_session, restaurant_id=restaurant.id, gateway=gw)
    assert mismatches == []


@pytest.mark.anyio
async def test_reconcile_flags_mismatch_when_psp_disagrees(db_session, restaurant):
    txn = await _seed_txn(db_session, restaurant, _FakeGateway())
    drifting_gw = _FakeGateway(overrides={txn.provider_charge_id: "failed"})
    mismatches = await reconcile_transactions(db_session, restaurant_id=restaurant.id, gateway=drifting_gw)
    assert len(mismatches) == 1
    assert mismatches[0]["transaction_id"] == txn.id
    assert mismatches[0]["psp_status"] == "failed"


@pytest.mark.anyio
async def test_mock_gateway_get_charge_status_always_succeeded():
    result = await MockPaymentProcessor().get_charge_status(provider_charge_id="mock_ch_anything")
    assert result == "succeeded"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/payments/test_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.payments.reconcile'`.

- [ ] **Step 3: Extend the port protocol and both implementations**

In `src/app/payments/port.py`, add to the `PaymentPort` protocol:

```python
class PaymentPort(Protocol):
    async def charge(
        self, *, amount_aed: Decimal, tender_type: str, reference: str
    ) -> ChargeResult: ...

    async def refund(
        self, *, provider_charge_id: str, amount_aed: Decimal
    ) -> RefundResult: ...

    async def get_charge_status(self, *, provider_charge_id: str) -> str: ...
```

In `src/app/payments/mock.py`, add:

```python
    async def get_charge_status(self, *, provider_charge_id: str) -> str:
        return "succeeded"
```

(inside the `MockPaymentProcessor` class, after `refund`).

In `src/app/payments/stripe_gateway.py`, add after `refund`:

```python
    async def get_charge_status(self, *, provider_charge_id: str) -> str:
        try:
            resp = await self._client.get(
                f"/payment_intents/{provider_charge_id}", auth=(self._secret_key, ""),
            )
        except httpx.HTTPError:
            return "unknown"
        if resp.status_code >= 400:
            return "unknown"
        stripe_status = resp.json().get("status")
        return {
            "succeeded": "succeeded",
            "canceled": "failed",
            "requires_payment_method": "failed",
        }.get(stripe_status, "unknown")
```

- [ ] **Step 4: Implement `reconcile.py`**

Create `src/app/payments/reconcile.py`:

```python
"""Nightly PSP <-> PaymentTransaction reconciliation (WS-PAY).

Cross-checks each gateway-tender (card/apple_pay/google_pay) succeeded
transaction against the PSP's own record of that charge. A mismatch means
the local ledger drifted from the PSP's source of truth (e.g. a chargeback
applied on the PSP side that never round-tripped back to us) — logged as an
ERROR for ops to investigate, never auto-corrected (money-affecting drift
needs a human, same posture as app.wallet.reconcile.reconcile_tenant).
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.models import PaymentTransaction
from app.payments.port import PaymentPort

logger = logging.getLogger(__name__)

_GATEWAY_TENDERS = {"card", "apple_pay", "google_pay"}


async def reconcile_transactions(
    session: AsyncSession, *, restaurant_id: int, gateway: PaymentPort, lookback_days: int = 7,
) -> list[dict]:
    """Returns a list of {transaction_id, local_status, psp_status} for every
    mismatch found in the lookback window. Read-only against the local ledger
    (never mutates PaymentTransaction) — caller does not need to commit."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = (await session.scalars(
        select(PaymentTransaction).where(
            PaymentTransaction.restaurant_id == restaurant_id,
            PaymentTransaction.tender_type.in_(_GATEWAY_TENDERS),
            PaymentTransaction.status == "succeeded",
            PaymentTransaction.provider_charge_id.isnot(None),
            PaymentTransaction.created_at >= cutoff,
        )
    )).all()
    mismatches = []
    for txn in rows:
        psp_status = await gateway.get_charge_status(provider_charge_id=txn.provider_charge_id)
        if psp_status != "succeeded":
            mismatches.append(
                {"transaction_id": txn.id, "local_status": txn.status, "psp_status": psp_status}
            )
            logger.error(
                "PAYMENT RECONCILE MISMATCH restaurant=%s transaction=%s local=%s psp=%s",
                restaurant_id, txn.id, txn.status, psp_status,
            )
    return mismatches
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/payments/test_reconcile.py -v`
Expected: PASS.

- [ ] **Step 6: Wire the nightly Celery task**

Create `src/app/payments/worker.py`:

```python
"""Celery beat task: nightly PSP <-> PaymentTransaction reconciliation."""
import asyncio
import logging

from celery import shared_task
from sqlalchemy import select

from app.db import async_session_factory
from app.identity.models import Restaurant
from app.payments.factory import get_payment_port
from app.payments.reconcile import reconcile_transactions

logger = logging.getLogger(__name__)


@shared_task(name="payments.reconcile_all_tenants", bind=True, max_retries=0)
def reconcile_all_tenants(self) -> int:  # type: ignore[override]
    return asyncio.run(_run_reconcile())


async def _run_reconcile() -> int:
    total_mismatches = 0
    async with async_session_factory() as session:
        restaurants = (await session.scalars(select(Restaurant))).all()
        for restaurant in restaurants:
            gateway = get_payment_port(restaurant)
            mismatches = await reconcile_transactions(
                session, restaurant_id=restaurant.id, gateway=gateway,
            )
            total_mismatches += len(mismatches)
    if total_mismatches:
        logger.error("payments reconciliation: %d mismatch(es) across all tenants", total_mismatches)
    return total_mismatches
```

In `apps/workers/celery_app.py`:

1. Add to the model-registration import block (after `import app.partner.models`):

```python
import app.payments.models  # noqa: F401,E402  (payments reconciliation reads PaymentTransaction)
```

2. Add to `task_routes` (after `"partner.*": {"queue": "maintenance"},`):

```python
        "payments.*": {"queue": "maintenance"},
```

3. Add to `beat_schedule` (after the `"loyalty-recompute-tiers"` entry):

```python
        "payments-reconcile-psp": {
            "task": "payments.reconcile_all_tenants",
            "schedule": crontab(hour=5, minute=0),  # 5am Asia/Dubai (after wallet/loyalty)
        },
```

4. Add `"app.payments"` to the `celery_app.autodiscover_tasks([...])` list at the bottom of the file.

- [ ] **Step 7: Run tests to verify nothing broke**

Run: `.venv/bin/pytest tests/payments/ -v`
Expected: PASS (all payments tests).

- [ ] **Step 8: Commit**

```bash
git add src/app/payments/port.py src/app/payments/mock.py src/app/payments/stripe_gateway.py src/app/payments/reconcile.py src/app/payments/worker.py apps/workers/celery_app.py tests/payments/test_reconcile.py
git commit -m "feat(payments): add nightly PSP reconciliation job"
```

---

## Task WP-7: Cash-drawer + Z-report frontend screen

**Files:**
- Create: `frontend/src/lib/cashDrawerApi.ts`
- Create: `frontend/src/lib/cashDrawerApi.test.ts`
- Modify: `frontend/src/lib/types.ts` *(shared file — see Coordination point 2)*
- Create: `frontend/src/screens/CashDrawerScreen.tsx`
- Create: `frontend/src/screens/CashDrawerScreen.module.css`
- Create: `frontend/src/screens/CashDrawerScreen.test.tsx`
- Modify: `frontend/src/App.tsx` *(shared file)*
- Modify: `frontend/src/components/NavSidebar.tsx` *(shared file)*

**Interfaces:**
- Consumes: `GET/POST /api/v1/cash-drawer/sessions*` (existing, `src/app/cashdrawer/router.py`), `GET /api/v1/reports/z-report?target_date=` (existing, `src/app/reports/router.py`).
- Produces: `getCurrentSession()`, `openSession(openingFloatAed)`, `addDrawerEvent(sessionId, type, amountAed, reason?)`, `closeSession(sessionId, closingCountAed)`, `getZReport(targetDate)` in `cashDrawerApi.ts`; `CashDrawerSession`, `CashDrawerEventOut`, `ZReportOut` types.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/cashDrawerApi.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { addDrawerEvent, closeSession, getCurrentSession, getZReport, openSession } from "./cashDrawerApi";

describe("cashDrawerApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (String(url).includes("/z-report")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ gross_sales_aed: "500.00", total_discounts_aed: "0.00", cod_collected_aed: "500.00", drawer_sessions: [] }),
              { status: 200 },
            ),
          );
        }
        if (String(url).includes("/close")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ id: 1, opened_by: "manager", opening_float_aed: "100.00", closed_by: "manager", closing_count_aed: "120.00", variance_aed: "0.00", status: "closed" }),
              { status: 200 },
            ),
          );
        }
        if (String(url).includes("/events")) {
          return Promise.resolve(new Response(JSON.stringify({ id: 1, type: "cash_in", amount_aed: "20.00" }), { status: 201 }));
        }
        if (init?.method === "POST") {
          return Promise.resolve(
            new Response(
              JSON.stringify({ id: 1, opened_by: "manager", opening_float_aed: "100.00", closed_by: null, closing_count_aed: null, variance_aed: null, status: "open" }),
              { status: 201 },
            ),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({ id: 1, opened_by: "manager", opening_float_aed: "100.00", closed_by: null, closing_count_aed: null, variance_aed: null, status: "open" }),
            { status: 200 },
          ),
        );
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("gets the current session", async () => {
    const session = await getCurrentSession();
    expect(session.status).toBe("open");
  });

  it("opens a session", async () => {
    const session = await openSession("100.00");
    expect(session.opening_float_aed).toBe("100.00");
  });

  it("adds a drawer event", async () => {
    const event = await addDrawerEvent(1, "cash_in", "20.00", "float top-up");
    expect(event.type).toBe("cash_in");
  });

  it("closes a session", async () => {
    const session = await closeSession(1, "120.00");
    expect(session.status).toBe("closed");
  });

  it("gets a z-report", async () => {
    const report = await getZReport("2026-07-08");
    expect(report.gross_sales_aed).toBe("500.00");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- cashDrawerApi`
Expected: FAIL — `Cannot find module './cashDrawerApi'`.

- [ ] **Step 3: Add types to `types.ts`**

Append to `frontend/src/lib/types.ts`:

```typescript
export interface CashDrawerSession {
  id: number;
  opened_by: string;
  opening_float_aed: string;
  closed_by: string | null;
  closing_count_aed: string | null;
  variance_aed: string | null;
  status: string;
}

export interface CashDrawerEventOut {
  id: number;
  type: string;
  amount_aed: string;
}

export interface DrawerSessionSummaryOut {
  id: number;
  opening_float_aed: string;
  closing_count_aed: string | null;
  variance_aed: string | null;
  status: string;
}

export interface ZReportOut {
  date: string;
  order_count: number;
  delivered_order_count: number;
  gross_sales_aed: string;
  total_discounts_aed: string;
  cod_collected_aed: string;
  drawer_sessions: DrawerSessionSummaryOut[];
}
```

- [ ] **Step 4: Implement `cashDrawerApi.ts`**

Create `frontend/src/lib/cashDrawerApi.ts`:

```typescript
import { apiClient } from "./apiClient";
import type { CashDrawerEventOut, CashDrawerSession, ZReportOut } from "./types";

export async function getCurrentSession(): Promise<CashDrawerSession> {
  return apiClient.get<CashDrawerSession>("/api/v1/cash-drawer/sessions/current");
}

export async function openSession(openingFloatAed: string): Promise<CashDrawerSession> {
  return apiClient.post<CashDrawerSession>("/api/v1/cash-drawer/sessions", {
    opening_float_aed: openingFloatAed,
  });
}

export async function addDrawerEvent(
  sessionId: number,
  type: "cash_in" | "cash_out",
  amountAed: string,
  reason?: string,
): Promise<CashDrawerEventOut> {
  return apiClient.post<CashDrawerEventOut>(`/api/v1/cash-drawer/sessions/${sessionId}/events`, {
    type, amount_aed: amountAed, reason: reason ?? null,
  });
}

export async function closeSession(sessionId: number, closingCountAed: string): Promise<CashDrawerSession> {
  return apiClient.post<CashDrawerSession>(`/api/v1/cash-drawer/sessions/${sessionId}/close`, {
    closing_count_aed: closingCountAed,
  });
}

export async function getZReport(targetDate: string): Promise<ZReportOut> {
  return apiClient.get<ZReportOut>(`/api/v1/reports/z-report?target_date=${targetDate}`);
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- cashDrawerApi`
Expected: PASS.

- [ ] **Step 6: Write the failing `CashDrawerScreen` test**

Create `frontend/src/screens/CashDrawerScreen.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CashDrawerScreen } from "./CashDrawerScreen";

describe("CashDrawerScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (String(url).includes("/sessions/current")) {
          return Promise.resolve(new Response("", { status: 404 }));
        }
        if (String(url).includes("/z-report")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ date: "2026-07-08", order_count: 5, delivered_order_count: 4, gross_sales_aed: "500.00", total_discounts_aed: "0.00", cod_collected_aed: "500.00", drawer_sessions: [] }),
              { status: 200 },
            ),
          );
        }
        if (init?.method === "POST") {
          return Promise.resolve(
            new Response(
              JSON.stringify({ id: 1, opened_by: "manager", opening_float_aed: "100.00", closed_by: null, closing_count_aed: null, variance_aed: null, status: "open" }),
              { status: 201 },
            ),
          );
        }
        return Promise.resolve(new Response("", { status: 404 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("opens a new drawer session", async () => {
    render(<CashDrawerScreen />);
    await waitFor(() => expect(screen.getByLabelText(/opening float/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/opening float/i), { target: { value: "100.00" } });
    fireEvent.click(screen.getByText(/open drawer/i));
    await waitFor(() => expect(screen.getByText(/drawer open/i)).toBeInTheDocument());
  });

  it("loads the z-report for a chosen date", async () => {
    render(<CashDrawerScreen />);
    fireEvent.click(screen.getByText(/load z-report/i));
    await waitFor(() => expect(screen.getByText(/gross sales: AED 500.00/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd frontend && npm test -- CashDrawerScreen`
Expected: FAIL — `Cannot find module './CashDrawerScreen'`.

- [ ] **Step 8: Implement `CashDrawerScreen.module.css`**

Create `frontend/src/screens/CashDrawerScreen.module.css`:

```css
.root { padding: 24px; }
.card { background: var(--surface, #fff); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.cardTitle { margin: 0 0 12px; font-size: 15px; }
.form { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; margin-bottom: 12px; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.status { font-weight: 600; margin-bottom: 8px; }
```

- [ ] **Step 9: Implement `CashDrawerScreen.tsx`**

Create `frontend/src/screens/CashDrawerScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  addDrawerEvent,
  closeSession,
  getCurrentSession,
  getZReport,
  openSession,
} from "../lib/cashDrawerApi";
import type { CashDrawerSession, ZReportOut } from "../lib/types";
import s from "./CashDrawerScreen.module.css";

export function CashDrawerScreen() {
  const [session, setSession] = useState<CashDrawerSession | null>(null);
  const [openingFloat, setOpeningFloat] = useState("");
  const [eventAmount, setEventAmount] = useState("");
  const [eventReason, setEventReason] = useState("");
  const [closingCount, setClosingCount] = useState("");
  const [zDate, setZDate] = useState(new Date().toISOString().slice(0, 10));
  const [zReport, setZReport] = useState<ZReportOut | null>(null);

  useEffect(() => {
    getCurrentSession()
      .then(setSession)
      .catch(() => setSession(null));
  }, []);

  async function doOpen() {
    if (!openingFloat.trim()) {
      toast("Enter an opening float amount.", "error");
      return;
    }
    try {
      const s2 = await openSession(openingFloat);
      setSession(s2);
      toast("Drawer opened.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not open drawer.", "error");
    }
  }

  async function doCashEvent(type: "cash_in" | "cash_out") {
    if (!session || !eventAmount.trim()) {
      toast("Enter an amount.", "error");
      return;
    }
    try {
      await addDrawerEvent(session.id, type, eventAmount, eventReason || undefined);
      setEventAmount("");
      setEventReason("");
      toast(`${type === "cash_in" ? "Cash in" : "Cash out"} recorded.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not record event.", "error");
    }
  }

  async function doClose() {
    if (!session || !closingCount.trim()) {
      toast("Enter the closing cash count.", "error");
      return;
    }
    try {
      const closed = await closeSession(session.id, closingCount);
      setSession(closed);
      toast(`Drawer closed. Variance: AED ${closed.variance_aed}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not close drawer.", "error");
    }
  }

  async function loadZReport() {
    try {
      const report = await getZReport(zDate);
      setZReport(report);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load Z-report.", "error");
    }
  }

  return (
    <div className={s.root}>
      <PageHeader title="Cash Drawer" subtitle="Open/close the till and view daily cash closing" />

      <section className={s.card}>
        <h3 className={s.cardTitle}>Drawer session</h3>
        {session && session.status === "open" ? (
          <>
            <p className={s.status}>Drawer open — opening float AED {session.opening_float_aed}</p>
            <div className={s.form}>
              <label className={s.field}>
                <span>Amount</span>
                <input aria-label="Event amount" value={eventAmount} onChange={(e) => setEventAmount(e.target.value)} />
              </label>
              <label className={s.field}>
                <span>Reason</span>
                <input aria-label="Event reason" value={eventReason} onChange={(e) => setEventReason(e.target.value)} />
              </label>
              <Button type="button" variant="ghost" onClick={() => void doCashEvent("cash_in")}>Cash in</Button>
              <Button type="button" variant="ghost" onClick={() => void doCashEvent("cash_out")}>Cash out</Button>
            </div>
            <div className={s.form}>
              <label className={s.field}>
                <span>Closing cash count</span>
                <input aria-label="Closing cash count" value={closingCount} onChange={(e) => setClosingCount(e.target.value)} />
              </label>
              <Button type="button" onClick={() => void doClose()}>Close drawer</Button>
            </div>
          </>
        ) : (
          <div className={s.form}>
            <label className={s.field}>
              <span>Opening float (AED)</span>
              <input aria-label="Opening float" value={openingFloat} onChange={(e) => setOpeningFloat(e.target.value)} />
            </label>
            <Button type="button" onClick={() => void doOpen()}>Open drawer</Button>
          </div>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Z-report</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Date</span>
            <input aria-label="Z-report date" type="date" value={zDate} onChange={(e) => setZDate(e.target.value)} />
          </label>
          <Button type="button" variant="ghost" onClick={() => void loadZReport()}>Load Z-report</Button>
        </div>
        {zReport && (
          <ul>
            <li>Gross sales: AED {Number(zReport.gross_sales_aed).toFixed(2)}</li>
            <li>Discounts: AED {Number(zReport.total_discounts_aed).toFixed(2)}</li>
            <li>COD collected: AED {Number(zReport.cod_collected_aed).toFixed(2)}</li>
          </ul>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 10: Wire route and nav entry**

Read the current `frontend/src/App.tsx` and `frontend/src/components/NavSidebar.tsx` before editing — if WD-4 (WS-DELIVERY) landed first, its edits to these two files are already present; add these lines alongside them, don't overwrite.

In `frontend/src/App.tsx`, add import:

```typescript
import { CashDrawerScreen } from "./screens/CashDrawerScreen";
```

Add route (after `/staff`):

```tsx
      <Route path="/cash-drawer" element={<Guarded><CashDrawerScreen /></Guarded>} />
```

In `frontend/src/components/NavSidebar.tsx`, add to `ITEMS` (after `/staff`):

```typescript
  { to: "/cash-drawer", label: "Cash Drawer", icon: "💰" },
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `cd frontend && npm test -- CashDrawerScreen`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/lib/cashDrawerApi.ts frontend/src/lib/cashDrawerApi.test.ts frontend/src/lib/types.ts frontend/src/screens/CashDrawerScreen.tsx frontend/src/screens/CashDrawerScreen.module.css frontend/src/screens/CashDrawerScreen.test.tsx frontend/src/App.tsx frontend/src/components/NavSidebar.tsx
git commit -m "feat(frontend): add Cash Drawer screen with Z-report"
```

---

# WS-DELIVERY

## Task WD-1: `floor` field on delivery address

**Files:**
- Modify: `src/app/ordering/models.py`
- Modify: `src/app/ordering/schemas.py`
- Modify: `src/app/ordering/service.py`
- Modify: `src/app/ordering/router.py`
- Modify: `frontend/src/lib/manualOrderApi.ts`
- Modify: `frontend/src/screens/NewOrderScreen.tsx`
- Test: `tests/ordering/test_manual_order.py` (append; if this file doesn't exist, check `tests/ordering/` for the file that already covers `create_manual_order` / `POST /api/v1/orders/manual` and append there instead)
- Test: `frontend/src/screens/NewOrderScreen.test.tsx` (append)

**Interfaces:**
- Consumes: existing `CustomerAddress` model, `upsert_address(...)`, `create_manual_order(...)` (all `src/app/ordering/service.py`).
- Produces: `CustomerAddress.floor: str | None`; `upsert_address(..., floor: str | None = None)`; `create_manual_order(..., floor: str | None = None)`; `ManualOrderAddressIn.floor`, `AddressOut.floor` (both `schemas.py`).

- [ ] **Step 1: Write the failing backend test**

First run `grep -rn "create_manual_order\b" tests/ordering/*.py` to find the existing test file that seeds a manual order (per the ground-truth check during planning, `create_manual_order` and `POST /api/v1/orders/manual` already have test coverage somewhere under `tests/ordering/`). Append this test to that file:

```python
@pytest.mark.anyio
async def test_manual_order_persists_floor(client, auth_headers):
    resp = await client.post(
        "/api/v1/orders/manual",
        json={
            "customer_phone": "+971500002001",
            "customer_name": "Floor Test",
            "items": [{"dish_id": 1, "qty": 1, "notes": None}],
            "address": {
                "apt_room": "12",
                "building": "Marina Tower",
                "floor": "14",
                "receiver_name": "Floor Test",
                "notes": None,
                "latitude": 25.20,
                "longitude": 55.27,
            },
            "delivery_fee_aed": "0.00",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    lookup = await client.get(
        "/api/v1/orders/manual/customer-lookup?phone=%2B971500002001", headers=auth_headers,
    )
    assert lookup.json()["last_address"]["floor"] == "14"
```

(This test assumes a seeded active menu with dish id 1 and a `restaurant`/`auth_headers` fixture already present in that test file — match whatever fixture pattern the surrounding tests in the same file already use for `dish_id`; if the file seeds its own dish with a different id, use that id instead of `1`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ordering/ -v -k floor`
Expected: FAIL — `pydantic.ValidationError` / `TypeError` on the unexpected `floor` field, or a 422 from the schema rejecting the extra key.

- [ ] **Step 3: Add the column**

In `src/app/ordering/models.py`, in `CustomerAddress`, add after `building`:

```python
    floor: Mapped[str | None] = mapped_column(String(32))
```

- [ ] **Step 4: Thread `floor` through `service.py`**

In `src/app/ordering/service.py`, update `upsert_address`'s signature and body:

```python
async def upsert_address(
    session: "AsyncSession",
    *,
    customer_id: int,
    latitude: float | None,
    longitude: float | None,
    room_apartment: str,
    building: str,
    floor: str | None = None,
    receiver_name: str | None = None,
    additional_details: str | None = None,
    confirmed: bool = False,
) -> CustomerAddress:
```

and add `addr.floor = floor` alongside the other field assignments:

```python
    addr.latitude = latitude
    addr.longitude = longitude
    addr.room_apartment = room_apartment
    addr.building = building
    addr.floor = floor
    addr.receiver_name = receiver_name
```

Update `create_manual_order`'s signature (add `floor: str | None = None,` after `building: str,`) and its `upsert_address(...)` call (add `floor=floor,` after `building=building,`).

- [ ] **Step 5: Thread `floor` through `schemas.py` and `router.py`**

In `src/app/ordering/schemas.py`:

```python
class ManualOrderAddressIn(BaseModel):
    apt_room: str = Field(min_length=1)
    building: str = Field(min_length=1)
    floor: str | None = None
    receiver_name: str = Field(min_length=1)
    notes: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class AddressOut(BaseModel):
    apt_room: str
    building: str
    floor: str | None = None
    receiver_name: str
    notes: str | None
```

In `src/app/ordering/router.py`, in `customer_lookup`, add `floor=last_addr.floor,` to the `AddressOut(...)` construction:

```python
        address_out = AddressOut(
            apt_room=last_addr.room_apartment or "",
            building=last_addr.building or "",
            floor=last_addr.floor,
            receiver_name=last_addr.receiver_name or "",
            notes=last_addr.additional_details,
        )
```

In `create_manual_order_endpoint`, add `floor=body.address.floor,` to the `create_manual_order(...)` call:

```python
        order = await create_manual_order(
            session,
            restaurant_id=restaurant.id,
            customer_phone=body.customer_phone,
            customer_name=body.customer_name,
            items=[i.model_dump() for i in body.items],
            apt_room=body.address.apt_room,
            building=body.address.building,
            floor=body.address.floor,
            receiver_name=body.address.receiver_name,
            address_notes=body.address.notes,
            delivery_fee_aed=body.delivery_fee_aed,
            latitude=body.address.latitude,
            longitude=body.address.longitude,
            scheduled_for=body.scheduled_for,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ordering/ -v -k floor`
Expected: PASS.

- [ ] **Step 7: Wire the frontend**

In `frontend/src/lib/manualOrderApi.ts`, add `floor: string | null;` to `AddressOut` and `floor?: string;` to `ManualOrderAddressIn`.

In `frontend/src/screens/NewOrderScreen.tsx`, add state (alongside `building`):

```typescript
  const [floor, setFloor] = useState("");
```

Add the input in the "Delivery Address" section, right after the Building field:

```tsx
            <div className={s.field}>
              <label className={s.label}>Floor (optional)</label>
              <input
                className={s.input}
                value={floor}
                onChange={(e) => setFloor(e.target.value)}
                placeholder="14th floor"
              />
            </div>
```

Add `floor: floor.trim() || undefined,` to the `address: {...}` object inside `onSubmit`'s `createManualOrder(...)` call.

If the customer-lookup prefill effect (around line 104, `setBuilding(result.last_address.building)`) exists, add `setFloor(result.last_address.floor ?? "")` alongside it.

- [ ] **Step 8: Add the frontend test and run it**

Append to `frontend/src/screens/NewOrderScreen.test.tsx` (read the existing file first to match its exact mock/fixture setup for `fetchActiveMenu`/`createManualOrder` before writing this):

```typescript
it("includes the floor field in the manual order payload", async () => {
  // Follow this file's existing pattern: fill phone/name/building/apt fields,
  // select an item, then fill the floor input and submit — assert the fetch
  // call to /api/v1/orders/manual carries "floor" in its JSON body.
});
```

Run: `cd frontend && npm test -- NewOrderScreen`
Expected: PASS. (Fill in the test body using the exact mock/fixture conventions already present in this file — read it before writing the assertion, since its `fetchActiveMenu`/menu-seeding mock shape isn't reproduced here to avoid guessing it wrong.)

- [ ] **Step 9: Add the migration**

```bash
.venv/bin/alembic revision --autogenerate -m "add floor to customer_addresses"
.venv/bin/alembic upgrade head
```

Verify the generated migration only adds the single `floor` column to `customer_addresses` (no other unrelated drift) before applying.

- [ ] **Step 10: Commit**

```bash
git add src/app/ordering/models.py src/app/ordering/schemas.py src/app/ordering/service.py src/app/ordering/router.py frontend/src/lib/manualOrderApi.ts frontend/src/screens/NewOrderScreen.tsx tests/ordering/ frontend/src/screens/NewOrderScreen.test.tsx alembic/versions/
git commit -m "feat(ordering): add floor field to delivery address"
```

---

## Task WD-2: Fix `reconcile_shift` expected-total bug

**Files:**
- Modify: `src/app/cod/service.py`
- Test: `tests/cod/test_cod.py`

**Interfaces:**
- Consumes: `app.ordering.models.Order` (read `total`, `status`, `delivered_at`, `rider_id`).
- Produces: `reconcile_shift(...)` unchanged signature, corrected body — `expected_total_aed` is now the sum of `Order.total` for the rider's delivered orders on `shift_date`, not a copy of `collected`.

- [ ] **Step 1: Write the failing test**

Append to `tests/cod/test_cod.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal


async def test_reconcile_shift_flags_real_variance(db_session):
    r, rider, c = await _seed(db_session)
    # Rider delivered an order worth 40.00 but only turned in 25.00 cash —
    # a real shortfall the old `expected = collected` bug could never detect.
    o = await _order(db_session, r, rider, c, "O4", Decimal("40.00"))
    await record_collection(
        db_session, restaurant_id=r.id, order_id=o.id, rider_id=rider.id, amount=Decimal("25.00")
    )
    await db_session.commit()

    rec = await reconcile_shift(
        db_session, restaurant_id=r.id, rider_id=rider.id,
        shift_date=datetime.now(timezone.utc).date(),
    )
    await db_session.commit()
    assert rec.expected_total_aed == Decimal("40.00")
    assert rec.collected_total_aed == Decimal("25.00")
    assert rec.variance_aed == Decimal("-15.00")
    assert rec.status == "variance"


async def test_reconcile_shift_only_counts_delivered_orders_for_that_rider(db_session):
    r, rider, c = await _seed(db_session)
    delivered = await _order(db_session, r, rider, c, "O5", Decimal("30.00"))
    await record_collection(
        db_session, restaurant_id=r.id, order_id=delivered.id, rider_id=rider.id, amount=Decimal("30.00")
    )
    await db_session.commit()
    from app.ordering.models import Order

    not_delivered = Order(
        restaurant_id=r.id, customer_id=c.id, order_number="O6", status="assigned",
        priority="normal", weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("99.00"), total=Decimal("99.00"), rider_id=rider.id,
    )
    db_session.add(not_delivered)
    await db_session.commit()

    rec = await reconcile_shift(
        db_session, restaurant_id=r.id, rider_id=rider.id,
        shift_date=datetime.now(timezone.utc).date(),
    )
    await db_session.commit()
    assert rec.expected_total_aed == Decimal("30.00")  # the 99.00 not-yet-delivered order is excluded
    assert rec.status == "balanced"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/cod/test_cod.py -v -k reconcile_shift_flags_real_variance`
Expected: FAIL — `assert Decimal('25.00') == Decimal('40.00')` (the current `expected = collected` bug makes `expected_total_aed` always equal `collected_total_aed`).

- [ ] **Step 3: Fix `reconcile_shift`**

In `src/app/cod/service.py`, replace the body of `reconcile_shift`:

```python
async def reconcile_shift(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider_id: int,
    shift_date: date,
) -> RiderShiftReconciliation:
    """Sum a rider's collections for shift_date; write reconciliation with variance.

    Caller commits. ``expected`` = the sum of ``Order.total`` for every order
    this rider delivered on ``shift_date`` (what the rider SHOULD have collected
    in cash from customers, since COD is the only tender). ``collected`` = the
    sum of what the rider actually turned in (``CodCollection`` rows). A
    nonzero variance is a real shortfall/overage signal, not the always-zero
    placeholder this function used to compute.
    """
    from app.ordering.models import Order

    collected = await session.scalar(
        select(func.coalesce(func.sum(CodCollection.amount_aed), 0)).where(
            CodCollection.restaurant_id == restaurant_id,
            CodCollection.rider_id == rider_id,
            func.date(CodCollection.collected_at) == shift_date,
        )
    )
    collected = Decimal(collected).quantize(Decimal("0.01"))

    expected = await session.scalar(
        select(func.coalesce(func.sum(Order.total), 0)).where(
            Order.restaurant_id == restaurant_id,
            Order.rider_id == rider_id,
            Order.status == "delivered",
            func.date(Order.delivered_at) == shift_date,
        )
    )
    expected = Decimal(expected).quantize(Decimal("0.01"))

    variance = (collected - expected).quantize(Decimal("0.01"))
    rec = RiderShiftReconciliation(
        rider_id=rider_id,
        restaurant_id=restaurant_id,
        shift_date=shift_date,
        expected_total_aed=expected,
        collected_total_aed=collected,
        variance_aed=variance,
        status="balanced" if variance == Decimal("0.00") else "variance",
    )
    session.add(rec)
    await session.flush()
    return rec
```

Note: `_order()` in the existing test helper (`tests/cod/test_cod.py`) does not set `delivered_at` — check its definition; if it doesn't, add `delivered_at=datetime.now(timezone.utc)` to the helper's `Order(...)` construction (or to each call site) so the new date-filtered query in Step 3 matches the seeded rows. The pre-existing `test_reconcile_shift_balanced` test (already in the file, unmodified) must still pass after this fix — if it starts failing because its seeded order lacks `delivered_at`, that confirms this helper needs the fix, not the production code.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/cod/test_cod.py -v`
Expected: PASS (all tests in the file, including the pre-existing `test_reconcile_shift_balanced`).

- [ ] **Step 5: Commit**

```bash
git add src/app/cod/service.py tests/cod/test_cod.py
git commit -m "fix(cod): compute real expected-vs-collected variance in reconcile_shift"
```

---

## Task WD-3: Delivery-proof-photo rider-app upload

**Files:**
- Create: `src/app/dispatch/delivery_proof_storage.py`
- Modify: `src/app/dispatch/rider_app_router.py`
- Test: `tests/dispatch/test_rider_app_delivery_photo.py`
- Modify: `rider-app/api.ts`
- Modify: `rider-app/App.tsx`
- Modify: `rider-app/package.json`

**Interfaces:**
- Consumes: `app.dispatch.delivery_proof.set_delivery_photo(session, *, restaurant_id, order_id, photo_url) -> Order` (existing, unchanged), `app.marketing.models.MarketingMedia` (existing blob-storage table, same pattern as `app.menu.service.store_dish_image`).
- Produces: `store_delivery_proof_image(session, *, restaurant_id, content, content_type) -> str`; `POST /api/v1/rider-app/orders/{order_id}/delivery-photo` (multipart, rider-device-token auth); `uploadDeliveryPhoto(token, orderId, fileUri) -> {url}` in `rider-app/api.ts`.

**Note on test coverage for this task:** `rider-app/` (verified during planning — `package.json` has only `start`/`android`/`build:apk` scripts, no `test`/`lint`, and no `.test.*` files exist anywhere in the directory) has **no test harness at all**. The backend half of this task (Steps 1–4) follows normal TDD. The rider-app UI half (Step 6) has no automated test to write — do not fabricate a fake-passing test. Verify it manually per Step 7 instead.

- [ ] **Step 1: Write the failing backend test**

Create `tests/dispatch/test_rider_app_delivery_photo.py`:

```python
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.dispatch.rider_app import create_pairing_code
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed_paired_rider_with_order(db_session, client, *, order_status="picked_up"):
    r = Restaurant(name="R", phone="+9710000099", password_hash="x", lat=25.2, lng=55.27)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="Photo Rider", phone="+971500000201", status="on_delivery")
    db_session.add(rider)
    await db_session.flush()
    code = await create_pairing_code(db_session, rider=rider)
    await db_session.commit()

    pair_resp = await client.post("/api/v1/rider-app/pair", json={"code": code})
    token = pair_resp.json()["device_token"]

    cust = Customer(restaurant_id=r.id, phone="+971500000202", name="Photo Cust")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=r.id, customer_id=cust.id, order_number="RPHOTO-0001",
        status=order_status, rider_id=rider.id, subtotal=Decimal("10.00"), total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.commit()
    return token, order


@pytest.mark.anyio
async def test_rider_uploads_delivery_photo(client, db_session):
    token, order = await _seed_paired_rider_with_order(db_session, client)

    resp = await client.post(
        f"/api/v1/rider-app/orders/{order.id}/delivery-photo",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("proof.jpg", b"\xff\xd8\xff fake jpeg bytes", "image/jpeg")},
    )
    assert resp.status_code == 201
    assert resp.json()["url"].endswith(".jpg")

    from app.ordering.models import Order as OrderModel

    await db_session.refresh(order)
    fresh = await db_session.scalar(select(OrderModel).where(OrderModel.id == order.id))
    assert fresh.delivery_photo_url == resp.json()["url"]


@pytest.mark.anyio
async def test_rider_uploads_delivery_photo_rejects_wrong_rider(client, db_session):
    token, order = await _seed_paired_rider_with_order(db_session, client)

    # A second rider (different device token) is not assigned to `order` — must 404.
    other = Rider(restaurant_id=order.restaurant_id, name="Other Rider", phone="+971500000203", status="on_delivery")
    db_session.add(other)
    await db_session.flush()
    other_code = await create_pairing_code(db_session, rider=other)
    await db_session.commit()
    other_token = (await client.post("/api/v1/rider-app/pair", json={"code": other_code})).json()["device_token"]

    resp = await client.post(
        f"/api/v1/rider-app/orders/{order.id}/delivery-photo",
        headers={"Authorization": f"Bearer {other_token}"},
        files={"file": ("proof.jpg", b"fake", "image/jpeg")},
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_rider_uploads_delivery_photo_rejects_bad_mime(client, db_session):
    token, order = await _seed_paired_rider_with_order(db_session, client)

    resp = await client.post(
        f"/api/v1/rider-app/orders/{order.id}/delivery-photo",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("proof.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dispatch/test_rider_app_delivery_photo.py -v`
Expected: FAIL — 404 (route doesn't exist yet).

- [ ] **Step 3: Implement blob storage**

Create `src/app/dispatch/delivery_proof_storage.py`:

```python
"""Blob storage for rider-uploaded delivery-proof photos.

Mirrors app.menu.service.store_dish_image's approach — stored in Postgres
(app.marketing.models.MarketingMedia) so the image survives redeploys on
ephemeral-disk hosts, served back via the existing "/media/<path>" URL
scheme. Skips the catalog-card compression step store_dish_image applies
(delivery photos are never pushed to WhatsApp/Meta, so full resolution up to
the same 5 MB cap is fine).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

DELIVERY_PHOTO_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_DELIVERY_PHOTO_BYTES = 5 * 1024 * 1024


async def store_delivery_proof_image(
    session: AsyncSession, *, restaurant_id: int, content: bytes, content_type: str,
) -> str:
    from app.config import get_settings
    from app.marketing.models import MarketingMedia

    rel = f"delivery-proof/{restaurant_id}/{uuid.uuid4().hex}.jpg"
    session.add(
        MarketingMedia(restaurant_id=restaurant_id, path=rel, content_type=content_type, data=content)
    )
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/media/{rel}"
```

- [ ] **Step 4: Add the router endpoint**

In `src/app/dispatch/rider_app_router.py`, add `UploadFile` to the `fastapi` import line:

```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
```

Add the endpoint after `_active_order` (or any point after `_current_rider` is defined — it depends on that helper):

```python
@router.post("/api/v1/rider-app/orders/{order_id}/delivery-photo", status_code=status.HTTP_201_CREATED)
async def upload_delivery_photo(
    order_id: int,
    file: UploadFile,
    rider: Rider = Depends(_current_rider),
    session: AsyncSession = Depends(get_session),
):
    from app.dispatch.delivery_proof import DeliveryPhotoError, set_delivery_photo
    from app.dispatch.delivery_proof_storage import (
        DELIVERY_PHOTO_MIMES,
        MAX_DELIVERY_PHOTO_BYTES,
        store_delivery_proof_image,
    )
    from app.ordering.models import Order

    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.rider_id == rider.id)
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found for this rider")
    if (file.content_type or "") not in DELIVERY_PHOTO_MIMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Delivery photo must be JPG, PNG, or WebP")
    content = await file.read()
    if len(content) > MAX_DELIVERY_PHOTO_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Photo exceeds 5 MB")

    url = await store_delivery_proof_image(
        session, restaurant_id=rider.restaurant_id, content=content, content_type=file.content_type or "image/jpeg",
    )
    try:
        await set_delivery_photo(session, restaurant_id=rider.restaurant_id, order_id=order_id, photo_url=url)
    except DeliveryPhotoError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return {"url": url}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/dispatch/test_rider_app_delivery_photo.py -v`
Expected: PASS.

- [ ] **Step 6: Wire the rider-app UI (no automated test — see note above)**

Add `expo-image-picker` to `rider-app/package.json`'s `dependencies` (matching the existing `~x.y.z` pin style of its neighbors):

```json
    "expo-image-picker": "~15.0.7",
```

In `rider-app/api.ts`, add after `markNotDelivered`:

```typescript
export const uploadDeliveryPhoto = async (
  token: string,
  orderId: number,
  fileUri: string,
): Promise<{ url: string }> => {
  const form = new FormData();
  // React Native's fetch FormData accepts this {uri, name, type} shape directly.
  form.append("file", {
    uri: fileUri,
    name: "proof.jpg",
    type: "image/jpeg",
  } as unknown as Blob);
  const resp = await fetch(`${API_BASE}/api/v1/rider-app/orders/${orderId}/delivery-photo`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const j = await resp.json();
      if (j?.detail) detail = j.detail;
    } catch {
      /* keep status */
    }
    throw new Error(detail);
  }
  return resp.json();
};
```

In `rider-app/App.tsx`, add the import:

```typescript
import * as ImagePicker from "expo-image-picker";
```

```typescript
import { getOrders, markDelivered, markNotDelivered, pickup, setDuty, uploadDeliveryPhoto, type Run, type Stop } from "./api";
```

Add a handler inside `TrackingScreen` (near `doDelivered`):

```typescript
  const doAttachPhoto = async (stop: Stop) => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Camera permission needed", "Allow camera access to attach a delivery photo.");
      return;
    }
    const result = await ImagePicker.launchCameraAsync({ quality: 0.6 });
    if (result.canceled || !result.assets?.[0]) return;
    setBusy(true);
    try {
      await uploadDeliveryPhoto(token, stop.orderId, result.assets[0].uri);
      Alert.alert("Photo attached", "Delivery proof photo saved.");
    } catch (e) {
      Alert.alert("Upload failed", e instanceof Error ? e.message : "Try again");
    } finally {
      setBusy(false);
    }
  };
```

Add a button next to the existing "Delivered" / "Not delivered" `cardActions` buttons (inside the `i === 0 ? (<>...</>) : null` block, after the "Not delivered, bring back" `Pressable`):

```tsx
                    <Pressable
                      style={({ pressed }) => [
                        styles.buttonAlt,
                        styles.buttonFlex,
                        pressed && styles.buttonAltPressed,
                        busy && styles.buttonDisabled,
                      ]}
                      disabled={busy}
                      onPress={() => doAttachPhoto(s)}
                    >
                      <Text style={styles.buttonAltText}>{busy ? "…" : "📷 Attach photo"}</Text>
                    </Pressable>
```

- [ ] **Step 7: Manual verification (no automated test harness in `rider-app/`)**

```bash
cd rider-app && npm install
npx expo start
```

Open the app in Expo Go on a physical device or simulator, pair with a test pairing code, take a photo via the new "📷 Attach photo" button on an active stop, and confirm: (a) no error alert appears, (b) `GET /api/v1/rider-app/orders/{orderId}` or the manager dashboard's order detail shows `delivery_photo_url` populated pointing at a reachable `/media/...` URL.

- [ ] **Step 8: Commit**

```bash
git add src/app/dispatch/delivery_proof_storage.py src/app/dispatch/rider_app_router.py tests/dispatch/test_rider_app_delivery_photo.py rider-app/api.ts rider-app/App.tsx rider-app/package.json
git commit -m "feat(dispatch): add rider-app delivery-proof photo upload"
```

---

## Task WD-4: Driver performance report + average delivery time

**Files:**
- Modify: `src/app/reports/analytics.py`
- Modify: `src/app/reports/router.py`
- Test: `tests/reports/test_driver_performance.py`
- Create: `frontend/src/lib/driverPerformanceApi.ts`
- Create: `frontend/src/lib/driverPerformanceApi.test.ts`
- Modify: `frontend/src/lib/types.ts` *(shared file — see Coordination point 2)*
- Create: `frontend/src/screens/DriverPerformanceScreen.tsx`
- Create: `frontend/src/screens/DriverPerformanceScreen.module.css`
- Create: `frontend/src/screens/DriverPerformanceScreen.test.tsx`
- Modify: `frontend/src/App.tsx` *(shared file)*
- Modify: `frontend/src/components/NavSidebar.tsx` *(shared file)*

**Interfaces:**
- Consumes: `app.ordering.models.Order` (`rider_id`, `status`, `delivered_at`, `sla_confirmed_at`, `late`), `app.identity.models.Rider` (`name`).
- Produces: `driver_performance_report(session, *, restaurant_id, start_date, end_date) -> list[dict]` (`reports/analytics.py`); `GET /api/v1/reports/driver-performance?start_date=&end_date=`.

- [ ] **Step 1: Write the failing backend test**

Create `tests/reports/test_driver_performance.py`:

```python
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.identity.models import Rider
from app.ordering.models import Customer, Order
from app.reports.analytics import driver_performance_report


async def _seed_order(db_session, restaurant, rider, customer, num, *, delivered_at, sla_confirmed_at, late):
    o = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number=num,
        status="delivered", rider_id=rider.id, subtotal=Decimal("30.00"), total=Decimal("30.00"),
        delivered_at=delivered_at, sla_confirmed_at=sla_confirmed_at, late=late,
    )
    db_session.add(o)
    await db_session.commit()
    return o


@pytest.mark.anyio
async def test_driver_performance_report_computes_avg_delivery_time_and_late_pct(db_session, restaurant):
    rider = Rider(restaurant_id=restaurant.id, name="Perf Rider", phone="+971500002101", status="available")
    db_session.add(rider)
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500002102", name="Perf Cust")
    db_session.add(cust)
    await db_session.flush()

    today = datetime.now(timezone.utc)
    await _seed_order(
        db_session, restaurant, rider, cust, "DRV-0001",
        delivered_at=today, sla_confirmed_at=today - timedelta(minutes=20), late=False,
    )
    await _seed_order(
        db_session, restaurant, rider, cust, "DRV-0002",
        delivered_at=today, sla_confirmed_at=today - timedelta(minutes=40), late=True,
    )

    rows = await driver_performance_report(
        db_session, restaurant_id=restaurant.id, start_date=date.today(), end_date=date.today(),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["rider_id"] == rider.id
    assert row["rider_name"] == "Perf Rider"
    assert row["delivery_count"] == 2
    assert row["avg_delivery_minutes"] == pytest.approx(30.0, abs=0.1)  # (20+40)/2
    assert row["late_count"] == 1
    assert row["late_pct"] == pytest.approx(50.0, abs=0.1)


@pytest.mark.anyio
async def test_driver_performance_report_router(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    rider = Rider(restaurant_id=restaurant.id, name="Router Rider", phone="+971500002103", status="available")
    db_session.add(rider)
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500002104", name="Router Cust")
    db_session.add(cust)
    await db_session.flush()
    today = datetime.now(timezone.utc)
    await _seed_order(
        db_session, restaurant, rider, cust, "DRV-0003",
        delivered_at=today, sla_confirmed_at=today - timedelta(minutes=25), late=False,
    )

    resp = await client.get(
        f"/api/v1/reports/driver-performance?start_date={date.today()}&end_date={date.today()}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["rider_name"] == "Router Rider" for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/reports/test_driver_performance.py -v`
Expected: FAIL — `ImportError: cannot import name 'driver_performance_report'`.

- [ ] **Step 3: Implement `driver_performance_report`**

In `src/app/reports/analytics.py`, add after `labor_hours` (any point after `_day_window` is defined):

```python
async def driver_performance_report(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    """Per-rider delivery stats over a date range, bucketed by ``delivered_at``.

    "delivery time" = ``delivered_at - sla_confirmed_at`` (the SLA-clock-start
    field, set when the customer confirms the order). "late" =
    ``Order.late is True`` (set by the delivery FSM in
    app.dispatch.delivery.advance_delivery against ``sla_deadline``). Riders
    with zero deliveries in the range are omitted.
    """
    from app.identity.models import Rider

    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.status == OrderStatus.DELIVERED,
            Order.delivered_at.isnot(None),
            Order.rider_id.isnot(None),
            Order.delivered_at >= day_start, Order.delivered_at <= day_end,
        )
    )).all()
    if not orders:
        return []

    rider_ids = {o.rider_id for o in orders}
    riders = (await session.scalars(select(Rider).where(Rider.id.in_(rider_ids)))).all()
    rider_names = {r.id: r.name for r in riders}

    by_rider: dict[int, list[Order]] = defaultdict(list)
    for order in orders:
        by_rider[order.rider_id].append(order)

    results = []
    for rider_id, rider_orders in by_rider.items():
        durations = [
            (o.delivered_at - o.sla_confirmed_at).total_seconds() / 60.0
            for o in rider_orders if o.sla_confirmed_at is not None
        ]
        late_count = sum(1 for o in rider_orders if o.late)
        delivery_count = len(rider_orders)
        results.append({
            "rider_id": rider_id,
            "rider_name": rider_names.get(rider_id, "Unknown"),
            "delivery_count": delivery_count,
            "avg_delivery_minutes": round(sum(durations) / len(durations), 2) if durations else None,
            "late_count": late_count,
            "late_pct": round(late_count / delivery_count * 100, 2) if delivery_count else 0.0,
        })
    return sorted(results, key=lambda r: r["rider_name"] or "")
```

- [ ] **Step 4: Add the router endpoint**

In `src/app/reports/router.py`, add `driver_performance_report` to the import list from `app.reports.analytics`, then add the endpoint after `labor_hours_report`:

```python
@router.get("/driver-performance")
async def driver_performance_endpoint(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await driver_performance_report(
        session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/reports/test_driver_performance.py -v`
Expected: PASS.

- [ ] **Step 6: Write the failing frontend API test**

Create `frontend/src/lib/driverPerformanceApi.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getDriverPerformance } from "./driverPerformanceApi";

describe("driverPerformanceApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify([
            { rider_id: 1, rider_name: "Ali", delivery_count: 10, avg_delivery_minutes: 28.5, late_count: 1, late_pct: 10.0 },
          ]),
          { status: 200 },
        ),
      ),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("gets driver performance rows", async () => {
    const rows = await getDriverPerformance("2026-07-01", "2026-07-08");
    expect(rows[0].rider_name).toBe("Ali");
    expect(rows[0].avg_delivery_minutes).toBe(28.5);
  });
});
```

- [ ] **Step 7: Run test to verify it fails**

Run: `cd frontend && npm test -- driverPerformanceApi`
Expected: FAIL — `Cannot find module './driverPerformanceApi'`.

- [ ] **Step 8: Add the type and API client function**

Append to `frontend/src/lib/types.ts`:

```typescript
export interface DriverPerformanceRow {
  rider_id: number;
  rider_name: string;
  delivery_count: number;
  avg_delivery_minutes: number | null;
  late_count: number;
  late_pct: number;
}
```

Create `frontend/src/lib/driverPerformanceApi.ts`:

```typescript
import { apiClient } from "./apiClient";
import type { DriverPerformanceRow } from "./types";

export async function getDriverPerformance(startDate: string, endDate: string): Promise<DriverPerformanceRow[]> {
  return apiClient.get<DriverPerformanceRow[]>(
    `/api/v1/reports/driver-performance?start_date=${startDate}&end_date=${endDate}`,
  );
}
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd frontend && npm test -- driverPerformanceApi`
Expected: PASS.

- [ ] **Step 10: Write the failing screen test**

Create `frontend/src/screens/DriverPerformanceScreen.test.tsx`:

```typescript
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DriverPerformanceScreen } from "./DriverPerformanceScreen";

describe("DriverPerformanceScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify([
            { rider_id: 1, rider_name: "Ali", delivery_count: 10, avg_delivery_minutes: 28.5, late_count: 1, late_pct: 10.0 },
          ]),
          { status: 200 },
        ),
      ),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows driver performance rows for the default range", async () => {
    render(<DriverPerformanceScreen />);
    await waitFor(() => expect(screen.getByText("Ali")).toBeInTheDocument());
    expect(screen.getByText("28.50")).toBeInTheDocument();
  });
});
```

- [ ] **Step 11: Run test to verify it fails**

Run: `cd frontend && npm test -- DriverPerformanceScreen`
Expected: FAIL — `Cannot find module './DriverPerformanceScreen'`.

- [ ] **Step 12: Implement the screen**

Create `frontend/src/screens/DriverPerformanceScreen.module.css`:

```css
.root { padding: 24px; }
.card { background: var(--surface, #fff); border-radius: 12px; padding: 16px; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border, #eee); }
.form { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; margin-bottom: 12px; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
```

Create `frontend/src/screens/DriverPerformanceScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import { getDriverPerformance } from "../lib/driverPerformanceApi";
import type { DriverPerformanceRow } from "../lib/types";
import s from "./DriverPerformanceScreen.module.css";

function defaultRange() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 7);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

export function DriverPerformanceScreen() {
  const { start, end } = defaultRange();
  const [startDate, setStartDate] = useState(start);
  const [endDate, setEndDate] = useState(end);
  const [rows, setRows] = useState<DriverPerformanceRow[]>([]);

  async function reload() {
    try {
      setRows(await getDriverPerformance(startDate, endDate));
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load driver performance.", "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load only
  }, []);

  return (
    <div className={s.root}>
      <PageHeader title="Driver Performance" subtitle="Average delivery time and lateness by rider" />
      <section className={s.card}>
        <div className={s.form}>
          <label className={s.field}>
            <span>Start date</span>
            <input aria-label="Report start date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>End date</span>
            <input aria-label="Report end date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
          <Button type="button" onClick={() => void reload()}>Refresh</Button>
        </div>
        <table className={s.table}>
          <thead>
            <tr><th>Rider</th><th>Deliveries</th><th>Avg delivery time (min)</th><th>Late</th><th>Late %</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.rider_id}>
                <td>{r.rider_name}</td>
                <td>{r.delivery_count}</td>
                <td>{r.avg_delivery_minutes !== null ? r.avg_delivery_minutes.toFixed(2) : "—"}</td>
                <td>{r.late_count}</td>
                <td>{r.late_pct.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
```

- [ ] **Step 13: Wire route and nav entry**

Read the current `frontend/src/App.tsx` and `frontend/src/components/NavSidebar.tsx` before editing — if WP-7 (WS-PAY) landed first, its edits to these two files are already present; add these lines alongside them, don't overwrite.

In `frontend/src/App.tsx`, add import:

```typescript
import { DriverPerformanceScreen } from "./screens/DriverPerformanceScreen";
```

Add route (after `/riders`):

```tsx
      <Route path="/driver-performance" element={<Guarded><DriverPerformanceScreen /></Guarded>} />
```

In `frontend/src/components/NavSidebar.tsx`, add to `ITEMS` (after `/riders`):

```typescript
  { to: "/driver-performance", label: "Driver Performance", icon: "🏍️" },
```

- [ ] **Step 14: Run tests to verify they pass**

Run: `cd frontend && npm test -- DriverPerformanceScreen`
Expected: PASS.

- [ ] **Step 15: Commit**

```bash
git add src/app/reports/analytics.py src/app/reports/router.py tests/reports/test_driver_performance.py frontend/src/lib/driverPerformanceApi.ts frontend/src/lib/driverPerformanceApi.test.ts frontend/src/lib/types.ts frontend/src/screens/DriverPerformanceScreen.tsx frontend/src/screens/DriverPerformanceScreen.module.css frontend/src/screens/DriverPerformanceScreen.test.tsx frontend/src/App.tsx frontend/src/components/NavSidebar.tsx
git commit -m "feat(reports): add driver performance report with average delivery time"
```

---

## Self-review notes (already applied above)

**1. Spec coverage** — every WS-PAY/WS-DELIVERY "done" item from the roadmap's per-workstream scope notes maps to a task:
- WS-PAY: tap-to-pay flag → WP-1; service charge + packaging/minimum-order charges → WP-2; credit note model → WP-3; deposit/advance payment tender → WP-4; Z-report/cash-closing UI → WP-7; PSP↔PaymentTransaction reconciliation job → WP-6; duplicate-payment idempotency-key wiring confirmed → WP-5.
- WS-DELIVERY: `floor` field on address → WD-1; fix `reconcile_shift` stub → WD-2; delivery-proof-photo rider-app upload UI → WD-3; driver performance report + average-delivery-time metric → WD-4.

**2. Placeholder scan** — none found; every step has literal, complete code. The one deliberate exception is WD-1 Step 8 and WD-3's rider-app UI verification (Step 7), both explicitly justified: WD-1 Step 8 defers to the target file's existing (unread-at-plan-time) mock conventions rather than guessing them wrong; WD-3 Step 7 is manual QA because `rider-app/` genuinely has no test harness (verified: no `test` script, no `.test.*` files) — fabricating a fake-passing automated test there would violate "no hallucination" harder than being explicit about the gap.

**3. Type consistency** — `CashDrawerSession`/`CashDrawerEventOut`/`ZReportOut` (WP-7 Task, `types.ts`) match the field names read directly off `src/app/cashdrawer/schemas.py:SessionOut` and `src/app/reports/router.py:z_report`. `DriverPerformanceRow` (WD-4, `types.ts`) matches the exact dict keys returned by `driver_performance_report` in `analytics.py`. `PaymentTransaction.is_tap_to_pay` (WP-1) is threaded through `charge_tender`'s signature → `ChargeIn.is_tap_to_pay` → router with the same name at every hop. `CustomerAddress.floor` (WD-1) is threaded through `upsert_address` → `create_manual_order` → `ManualOrderAddressIn.floor`/`AddressOut.floor` → router → frontend with the same name at every hop.

**4. Blast-radius check (CLAUDE.md god-node rule)** — this plan does not touch `handle_inbound`, `get_settings`, `record_audit`'s signature, `lint_template`, or `app.ordering.models` in a way that changes any existing column/behavior (WD-1 only *adds* a nullable column to `CustomerAddress`, a leaf model, not `Order` itself). WP-2/WP-3/WP-4 deliberately avoid touching `app.ordering.models.Order`'s schema at all (see Architecture section) specifically to keep both tracks' blast radius inside `src/app/payments/`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-wave2-payments-delivery.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. WP-* and WD-* tasks can be dispatched as two parallel subagent chains (matching Wave 1's execution model) since the backend files are fully disjoint (Coordination point 1); only serialize (or worktree-isolate) whichever of WP-7 / WD-4 lands second, per Coordination point 2.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
