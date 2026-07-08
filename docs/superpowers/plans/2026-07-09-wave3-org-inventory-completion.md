# Wave 3 Organization + Inventory Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved Wave 3 `WS-ORG + WS-INVENTORY` scope by adding inventory finance/approval/alert APIs and owner-facing Inventory + Branch Operations dashboard screens.

**Architecture:** Keep the existing bounded contexts. Inventory stock-adjustment state lives in `src/app/inventory/`; valuation remains an inventory service surfaced through `reports/router.py`; organization branch inventory summary lives in `src/app/organizations/service.py`. Frontend code is split into focused API clients and screens, then wired through the existing router/sidebar pattern.

**Tech Stack:** FastAPI, async SQLAlchemy 2, Alembic, pytest/anyio, React/Vite/TypeScript, Vitest/Testing Library.

---

## Task 1: Inventory Finance, Adjustment, and Alert Services

**Files:**
- Modify: `src/app/inventory/models.py`
- Modify: `src/app/inventory/schemas.py`
- Modify: `src/app/inventory/service.py`
- Test: `tests/inventory/test_wave3_finance.py`

- [ ] **Step 1: Write failing backend tests**

Create `tests/inventory/test_wave3_finance.py` with tests for:

```python
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.inventory.models import Ingredient, PurchaseOrderLine, StockAdjustmentRequest
from app.inventory.purchasing import create_purchase_order, create_vendor
from app.inventory.service import (
    approve_stock_adjustment,
    inventory_valuation,
    low_stock_alert,
    reject_stock_adjustment,
    request_stock_adjustment,
    vendor_price_comparison,
)
from app.outbox.models import OutboxMessage


@pytest.mark.anyio
async def test_vendor_price_comparison_uses_latest_po_cost_per_vendor(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id, name="Tomato", unit="kg",
        current_stock=Decimal("10.000"), cost_per_unit_aed=Decimal("2.0000"),
    )
    db_session.add(ingredient)
    await db_session.flush()
    v1 = await create_vendor(db_session, restaurant_id=restaurant.id, name="Fresh One")
    v2 = await create_vendor(db_session, restaurant_id=restaurant.id, name="Fresh Two")
    await db_session.flush()
    await create_purchase_order(
        db_session, restaurant_id=restaurant.id, vendor_id=v1.id,
        lines=[{"ingredient_id": ingredient.id, "qty_ordered": "1.000", "unit_cost_aed": "3.0000"}],
    )
    await create_purchase_order(
        db_session, restaurant_id=restaurant.id, vendor_id=v1.id,
        lines=[{"ingredient_id": ingredient.id, "qty_ordered": "1.000", "unit_cost_aed": "2.5000"}],
    )
    await create_purchase_order(
        db_session, restaurant_id=restaurant.id, vendor_id=v2.id,
        lines=[{"ingredient_id": ingredient.id, "qty_ordered": "1.000", "unit_cost_aed": "2.7500"}],
    )
    await db_session.commit()

    rows = await vendor_price_comparison(db_session, restaurant_id=restaurant.id, ingredient_id=ingredient.id)
    assert [(r["vendor_name"], r["unit_cost_aed"]) for r in rows] == [
        ("Fresh One", Decimal("2.5000")),
        ("Fresh Two", Decimal("2.7500")),
    ]


@pytest.mark.anyio
async def test_inventory_valuation_returns_rows_and_total(db_session, restaurant):
    db_session.add_all([
        Ingredient(
            restaurant_id=restaurant.id, name="Rice", unit="kg",
            current_stock=Decimal("5.000"), cost_per_unit_aed=Decimal("4.0000"),
        ),
        Ingredient(
            restaurant_id=restaurant.id, name="Oil", unit="L",
            current_stock=Decimal("2.000"), cost_per_unit_aed=Decimal("8.5000"),
        ),
    ])
    await db_session.commit()

    result = await inventory_valuation(db_session, restaurant_id=restaurant.id)
    assert result["total_value_aed"] == Decimal("37.00")
    assert [row["ingredient_name"] for row in result["rows"]] == ["Rice", "Oil"]


@pytest.mark.anyio
async def test_stock_adjustment_requires_approval_before_stock_changes(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id, name="Flour", unit="kg",
        current_stock=Decimal("9.000"), cost_per_unit_aed=Decimal("1.0000"),
    )
    db_session.add(ingredient)
    await db_session.commit()

    request = await request_stock_adjustment(
        db_session, restaurant_id=restaurant.id, ingredient_id=ingredient.id,
        requested_qty=Decimal("12.000"), reason="closing count", requested_by="cashier",
    )
    await db_session.commit()
    await db_session.refresh(ingredient)
    assert ingredient.current_stock == Decimal("9.000")
    assert request.status == "pending"

    approved = await approve_stock_adjustment(
        db_session, restaurant_id=restaurant.id, adjustment_id=request.id, approved_by="manager",
    )
    await db_session.commit()
    await db_session.refresh(ingredient)
    assert approved.status == "approved"
    assert ingredient.current_stock == Decimal("12.000")
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.entity == "stock_adjustment", AuditLog.entity_id == str(request.id))
    )
    assert audit is not None


@pytest.mark.anyio
async def test_rejected_stock_adjustment_leaves_stock_unchanged(db_session, restaurant):
    ingredient = Ingredient(
        restaurant_id=restaurant.id, name="Cheese", unit="kg",
        current_stock=Decimal("4.000"), cost_per_unit_aed=Decimal("10.0000"),
    )
    db_session.add(ingredient)
    await db_session.commit()

    request = await request_stock_adjustment(
        db_session, restaurant_id=restaurant.id, ingredient_id=ingredient.id,
        requested_qty=Decimal("2.000"), reason="bad count", requested_by="cashier",
    )
    await db_session.commit()
    rejected = await reject_stock_adjustment(
        db_session, restaurant_id=restaurant.id, adjustment_id=request.id, approved_by="manager",
    )
    await db_session.commit()
    await db_session.refresh(ingredient)
    assert rejected.status == "rejected"
    assert ingredient.current_stock == Decimal("4.000")


@pytest.mark.anyio
async def test_low_stock_alert_enqueues_idempotent_owner_message(db_session, restaurant):
    restaurant.phone = "+971500001111"
    ingredient = Ingredient(
        restaurant_id=restaurant.id, name="Mint", unit="bunch",
        current_stock=Decimal("1.000"), low_stock_threshold=Decimal("2.000"),
        par_level=Decimal("10.000"), cost_per_unit_aed=Decimal("0.5000"),
    )
    db_session.add(ingredient)
    await db_session.commit()

    first = await low_stock_alert(db_session, restaurant=restaurant)
    second = await low_stock_alert(db_session, restaurant=restaurant)
    await db_session.commit()

    assert first["enqueued"] is True
    assert second["enqueued"] is True
    rows = (await db_session.scalars(select(OutboxMessage))).all()
    assert len(rows) == 1
    assert "Mint" in rows[0].payload["body"]
```

- [ ] **Step 2: Run tests to verify RED**

Run: `.venv/bin/pytest tests/inventory/test_wave3_finance.py -q`
Expected: import errors for the new model/functions.

- [ ] **Step 3: Implement minimal backend service/model/schema**

Add `StockAdjustmentRequest` to `src/app/inventory/models.py`. Add schemas for adjustment create/out, vendor price rows, valuation rows, valuation result, and alert result to `src/app/inventory/schemas.py`. Add service functions named in the tests to `src/app/inventory/service.py`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `.venv/bin/pytest tests/inventory/test_wave3_finance.py -q`
Expected: all tests pass.

## Task 2: API Wiring and Migration

**Files:**
- Modify: `src/app/inventory/router.py`
- Modify: `src/app/reports/router.py`
- Create: `alembic/versions/z7a8b9c0d1e2_stock_adjustment_requests.py`
- Test: `tests/inventory/test_wave3_router.py`
- Test: `tests/reports/test_inventory_valuation_router.py`

- [ ] **Step 1: Write failing router tests**

Create tests proving:

- `GET /api/v1/ingredients/{id}/vendor-price-comparison` returns cost rows.
- `POST /api/v1/ingredients/{id}/stock-adjustments` creates pending adjustment.
- `POST /api/v1/ingredients/stock-adjustments/{id}/approve` applies stock.
- `POST /api/v1/ingredients/low-stock-alert` returns an idempotent outbox id.
- `GET /api/v1/reports/inventory-valuation` returns row values and total.

- [ ] **Step 2: Run router tests to verify RED**

Run: `.venv/bin/pytest tests/inventory/test_wave3_router.py tests/reports/test_inventory_valuation_router.py -q`
Expected: 404 for new endpoints.

- [ ] **Step 3: Wire endpoints and migration**

Add inventory routes under existing `/api/v1/ingredients`; add valuation route in `reports/router.py`; create Alembic revision `z7a8b9c0d1e2` with `down_revision = "y6z7a8b9c0d1"`.

- [ ] **Step 4: Run router tests to verify GREEN**

Run: `.venv/bin/pytest tests/inventory/test_wave3_router.py tests/reports/test_inventory_valuation_router.py -q`
Expected: all tests pass.

## Task 3: Organization Inventory Summary

**Files:**
- Modify: `src/app/organizations/service.py`
- Modify: `src/app/organizations/router.py`
- Test: `tests/organizations/test_inventory_summary.py`

- [ ] **Step 1: Write failing organization tests**

Create tests proving `organization_inventory_summary()` returns branch rows with `low_stock_count`, `inventory_value_aed`, and totals, and `GET /api/v1/organizations/inventory-summary` serializes decimals as strings.

- [ ] **Step 2: Run tests to verify RED**

Run: `.venv/bin/pytest tests/organizations/test_inventory_summary.py -q`
Expected: import/404 failure.

- [ ] **Step 3: Implement service and route**

Add `organization_inventory_summary(session, *, organization_id)` to `organizations/service.py`, using `list_branches()` and `inventory_valuation()`. Add `GET /inventory-summary` to `organizations/router.py`.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `.venv/bin/pytest tests/organizations/test_inventory_summary.py -q`
Expected: all tests pass.

## Task 4: Frontend API Clients

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/lib/inventoryApi.ts`
- Create: `frontend/src/lib/organizationsApi.ts`
- Test: `frontend/src/lib/inventoryApi.test.ts`
- Test: `frontend/src/lib/organizationsApi.test.ts`

- [ ] **Step 1: Write failing API client tests**

Mock `fetch` and verify the new clients call the approved paths and send `Authorization: Bearer ops_org_token` for organization endpoints.

- [ ] **Step 2: Run tests to verify RED**

Run: `cd frontend && npm test -- inventoryApi organizationsApi`
Expected: module-not-found failures.

- [ ] **Step 3: Implement clients and types**

Add typed functions for inventory list/create/restock/waste/adjustments/vendor comparison/valuation/alert and organization login/signup/branches/rollup/comparison/inventory summary/stock transfer.

- [ ] **Step 4: Run tests to verify GREEN**

Run: `cd frontend && npm test -- inventoryApi organizationsApi`
Expected: all tests pass.

## Task 5: Inventory Screen

**Files:**
- Create: `frontend/src/screens/InventoryScreen.tsx`
- Create: `frontend/src/screens/InventoryScreen.module.css`
- Create: `frontend/src/screens/InventoryScreen.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavSidebar.tsx`

- [ ] **Step 1: Write failing screen test**

Render `InventoryScreen`, mock `inventoryApi`, and verify the screen shows ingredients, low stock, reorder suggestions, valuation, and exposes restock/waste/stock-adjustment actions.

- [ ] **Step 2: Run test to verify RED**

Run: `cd frontend && npm test -- InventoryScreen`
Expected: module-not-found failure.

- [ ] **Step 3: Implement screen and route**

Use existing `StaffScreen` patterns: `PageHeader`, form sections, compact tables, `Button`, `toast`. Add route `/inventory` and nav item.

- [ ] **Step 4: Run test to verify GREEN**

Run: `cd frontend && npm test -- InventoryScreen`
Expected: all tests pass.

## Task 6: Branch Operations Screen and Final Verification

**Files:**
- Create: `frontend/src/screens/BranchOpsScreen.tsx`
- Create: `frontend/src/screens/BranchOpsScreen.module.css`
- Create: `frontend/src/screens/BranchOpsScreen.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavSidebar.tsx`
- Modify: `understanding.txt`

- [ ] **Step 1: Write failing screen test**

Render `BranchOpsScreen`, mock `organizationsApi`, and verify org login stores token, loads branches/rollup/comparison/inventory summary, and submits a stock transfer.

- [ ] **Step 2: Run test to verify RED**

Run: `cd frontend && npm test -- BranchOpsScreen`
Expected: module-not-found failure.

- [ ] **Step 3: Implement screen and route**

Add route `/branches` and sidebar item. Keep organization token separate from restaurant token.

- [ ] **Step 4: Run frontend test to verify GREEN**

Run: `cd frontend && npm test -- BranchOpsScreen`
Expected: all tests pass.

- [ ] **Step 5: Update project memory and verify**

Append a dated bullet to `understanding.txt`. Run:

```bash
.venv/bin/ruff check src/app/inventory src/app/organizations src/app/reports tests/inventory tests/organizations tests/reports
.venv/bin/pytest tests/inventory tests/organizations tests/reports -q
PYTHONPATH=src .venv/bin/alembic heads
cd frontend && npm test -- inventoryApi organizationsApi InventoryScreen BranchOpsScreen
cd frontend && npm run lint
```

- [ ] **Step 6: Graphify update and commit**

Run `graphify update .` if `/graphify . --update` cannot run without an LLM key. Stage only Wave 3 files and commit with `feat: complete wave 3 org inventory workflows`.
