# Wave 3 Organization + Inventory Completion Design

Date: 2026-07-09
Status: Draft for review after user selected Option A

## 1. Goal

Wave 3 completes the roadmap's `WS-ORG + WS-INVENTORY` slice by turning the already-built organization and inventory backends into usable owner workflows, then closing the remaining inventory and branch-operations gaps that are still real business value for restaurant owners.

This wave should make a multi-branch owner able to see branch performance, move stock between branches, and operate ingredients/purchasing from the dashboard. It should also make inventory financially useful through valuation, vendor price comparison, stock-adjustment approval, and low-stock owner alerts.

## 2. Current Baseline

Already implemented on `main`:

- `src/app/organizations/`: organization signup/login, branch CRUD, sales rollup, branch comparison, stock transfers.
- `src/app/inventory/`: ingredients, recipe links, stock deduction, restock, waste, stock counts, vendors, purchase orders, goods received, batches/expiry, substitutions, par levels, anomaly checks, stock closing.
- `src/app/reports/`: item performance with food cost/margin, inventory usage, daily stock closing.

Current gaps:

- No frontend screens for inventory, vendors, purchase orders, branch operations, or stock transfers.
- Vendor price comparison exists only implicitly in old purchase-order lines.
- Stock count applies immediately; there is no manager approval workflow for stock adjustments.
- Inventory valuation is not exposed as a report.
- Low-stock detection is not wired to WhatsApp/outbox owner alerts.
- Organization operations require a separate organization JWT, while the manager dashboard only stores a restaurant JWT.

## 3. In Scope

### Inventory Dashboard

Add a manager dashboard screen for the existing restaurant-scoped inventory API:

- List/create ingredients.
- Show current stock, low-stock threshold, par level, and cost per unit.
- Restock ingredients.
- Log waste.
- Submit stock counts.
- Link recipes to dishes by ingredient and quantity per dish.
- Create batches with expiry date and show expiring-soon items.
- Add/list ingredient substitutes.
- Show reorder suggestions.
- Show daily stock closing and inventory valuation.
- Show vendor price comparison for an ingredient.
- Create vendors and purchase orders.
- Receive purchase orders.

### Branch Operations Dashboard

Add a dashboard screen for organization owners:

- Organization signup/login panel that stores a separate `ops_org_token` in local storage.
- Branch list and branch creation.
- Rollup sales by date.
- Branch comparison by date range.
- Cross-branch stock transfer creation and completion.

The organization token stays separate from the normal `ops_token` manager token. Normal restaurant endpoints continue using `ops_token`. Organization endpoints use `ops_org_token`.

### Backend Gaps

Add narrowly scoped backend behavior where the frontend needs first-class APIs:

- Vendor price comparison: latest known unit cost per vendor for an ingredient, based on purchase-order lines joined through purchase orders and vendors.
- Inventory valuation: per-ingredient and total current stock value using `current_stock * cost_per_unit_aed`.
- Stock adjustment approval: manager can request a stock adjustment; a manager approval endpoint applies the adjustment and writes audit records. Existing direct `stock-count` stays for compatibility, but the dashboard should use the approval flow for counted-stock corrections.
- Low-stock owner alert: enqueue a WhatsApp outbox message for the restaurant's manager phone when low-stock ingredients exist. Alert generation is idempotent by restaurant/date/ingredient set so repeated runs do not spam.
- Organization inventory summary: organization endpoint showing branch-level low-stock counts and total inventory valuation across branches.

## 4. Out of Scope

- Real supplier ordering API integrations. Vendors remain internal records.
- Accounting-system export.
- Full branch-level RBAC matrix. Existing organization owner auth and restaurant manager auth remain separate.
- Shared loyalty/customer database changes. That belongs with the CRM wave.
- Centralized menu publishing workflow. That belongs with the menu wave.
- Aggregator channel menu/stock sync. That belongs with the aggregator wave.
- Historical point-in-time inventory ledger. This wave keeps the existing stock model and adds an approval layer around adjustments.

## 5. Data Model

Create one new inventory model:

- `StockAdjustmentRequest`
  - `id`
  - `restaurant_id`
  - `ingredient_id`
  - `requested_qty`
  - `previous_qty_snapshot`
  - `reason`
  - `status`: `pending`, `approved`, `rejected`
  - `requested_by`
  - `approved_by`
  - `decided_at`

No new organization tables are required. Organization inventory summary can join existing `Restaurant` branches to existing `Ingredient` rows.

## 6. API Surface

Add inventory endpoints:

- `POST /api/v1/ingredients/{ingredient_id}/stock-adjustments`
- `GET /api/v1/ingredients/stock-adjustments?status=pending`
- `POST /api/v1/ingredients/stock-adjustments/{adjustment_id}/approve`
- `POST /api/v1/ingredients/stock-adjustments/{adjustment_id}/reject`
- `GET /api/v1/ingredients/{ingredient_id}/vendor-price-comparison`
- `GET /api/v1/reports/inventory-valuation`
- `POST /api/v1/ingredients/low-stock-alert`

Add organization endpoint:

- `GET /api/v1/organizations/inventory-summary`

Existing endpoints remain unchanged.

## 7. Frontend Architecture

Add focused API clients:

- `frontend/src/lib/inventoryApi.ts`
- `frontend/src/lib/organizationsApi.ts`

Add focused screens:

- `frontend/src/screens/InventoryScreen.tsx`
- `frontend/src/screens/BranchOpsScreen.tsx`

Add routes/navigation:

- `/inventory`
- `/branches`

Use existing dashboard patterns: `PageHeader`, `Button`, `toast`, local loading/error state, compact tables, and form sections. No marketing-style hero pages.

## 8. Data Flow

Inventory screen:

1. Load ingredients, low-stock list, reorder suggestions, daily stock closing, and valuation using the restaurant manager token.
2. Mutations call existing or new inventory endpoints.
3. After a mutation, reload the affected lists and show a toast.
4. Stock adjustments use request/approve flow, not direct count application.

Branch operations screen:

1. User signs up or logs in with organization credentials in the branch screen.
2. Store `ops_org_token`.
3. Load branches, rollup sales, branch comparison, and inventory summary using the organization token.
4. Stock-transfer completion reloads inventory summary and branch transfer state.

Low-stock alert:

1. Backend reads low-stock ingredients for the authenticated restaurant.
2. If no items are low, return `{"enqueued": false, "reason": "no_low_stock"}`.
3. If items are low, enqueue one outbox text message to the restaurant manager phone.
4. Repeated calls with the same restaurant/date/ingredient set return the existing outbox row.

## 9. Error Handling and Security

- All inventory endpoints enforce `restaurant_id` ownership.
- Organization endpoints enforce `aud="org"` through `current_organization`.
- Cross-organization stock transfers remain forbidden.
- Stock-adjustment approve/reject endpoints reject non-pending requests.
- Vendor price comparison ignores purchase-order lines whose purchase order belongs to another restaurant.
- Low-stock alert returns a 409 if the restaurant has no usable manager phone.

## 10. Testing

Backend pytest:

- Vendor price comparison returns latest costs per vendor for one ingredient.
- Inventory valuation computes per-row and total value.
- Stock-adjustment approval applies stock only after approval and writes audit.
- Stock-adjustment reject leaves stock unchanged.
- Low-stock alert enqueues exactly one idempotent outbox row.
- Organization inventory summary aggregates valuation and low-stock counts across branches.

Frontend Vitest:

- Inventory screen loads ingredients and renders low-stock/reorder/valuation sections.
- Inventory screen restock/waste/stock-adjustment flows call the expected endpoints and refresh.
- Branch operations screen stores organization token after login and loads branch/rollup/comparison/summary sections.
- Branch operations screen creates stock transfers using the organization token.

Verification commands:

- `.venv/bin/pytest tests/inventory tests/organizations tests/reports -q`
- `.venv/bin/ruff check src/app/inventory src/app/organizations src/app/reports tests/inventory tests/organizations tests/reports`
- `cd frontend && npm test -- InventoryScreen BranchOpsScreen`
- `cd frontend && npm run lint`

## 11. Success Criteria

Wave 3 is complete when:

- A restaurant manager can run daily inventory operations from the dashboard without calling raw API endpoints.
- An organization owner can manage branches and stock transfers from the dashboard with a separate organization token.
- Food-cost visibility includes inventory valuation and vendor price comparison.
- Stock adjustments can be approved or rejected without silently rewriting stock.
- Low-stock items can generate a single idempotent WhatsApp/outbox owner alert.
- Tests cover the backend and frontend flows above.
