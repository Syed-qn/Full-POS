# Reporting & Analytics Expansion — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase I, scoped)

## 1. Scope

Pure aggregation over data already produced by Phases D/E/G — no new write
paths, no new domain concepts. A custom/configurable report-builder UI is
deferred (genuinely new UI investment, not justified until these fixed
reports see real usage).

## 2. Reports (new `src/app/reports/analytics.py`, alongside the existing `zreport.py`)

- **Item performance** (`item_performance`): per-dish order count + revenue for a date range, from `OrderItem`/`Order`, ordered by revenue descending (best/worst sellers).
- **Inventory usage** (`inventory_usage`): per-ingredient total deducted (from `deduct_for_order`'s effect — computed here by walking confirmed orders' recipes for the range, not from a separate ledger, since Phase E didn't add a deduction-history table — deferred as YAGNI until usage patterns show a ledger is actually needed).
- **Table turn time** (`table_turn_time`): average minutes between a table entering `seated` and returning to `available`, from `audit_log` rows recorded by the tables status-transition endpoint (Phase D already audits every transition).
- **Labor cost** (`labor_cost`): per-staff hours (reuses `staff.service.compute_hours`) — no wage rate exists yet in the data model, so this reports **hours only**, not AED cost (adding a wage-rate field is a one-line follow-up once payroll data exists, deferred to avoid inventing a number).

## 3. API surface (extends `src/app/reports/router.py`)

- `GET /api/v1/reports/item-performance?start_date=&end_date=`
- `GET /api/v1/reports/inventory-usage?start_date=&end_date=`
- `GET /api/v1/reports/table-turn-time?start_date=&end_date=`
- `GET /api/v1/reports/labor-hours?target_date=`

## 4. Testing

Unit per report function against seeded orders/tables/staff data for a known date range.

## Related
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase I
- Report-builder UI and labor-cost-in-AED explicitly deferred (see §1, §2)
