# Cash Drawer + Z-Report — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase C, scoped)

## 1. Scope decision — read this before touching payments code

CLAUDE.md's non-negotiable business rules lock delivery orders to **COD only**.
There is no card/NFC/EMV gateway in this codebase and building one means
integrating a real third-party PCI-compliant processor (Stripe/Network
International/Telr, etc.) — that's a genuine external-vendor integration
decision, not something to fabricate. **Out of scope for this phase.**

What IS real and buildable without any new vendor: a **restaurant-level cash
drawer** (distinct from `cod/models.py`'s existing per-RIDER shift
reconciliation) and a **Z-report** (end-of-day sales + cash summary) built
from data that already exists: `Order`, `CodCollection`, `WalletEntry`,
`Coupon` redemptions.

## 2. Data model

- `cash_drawer_sessions` — id, restaurant_id, opened_by, opened_at, opening_float_aed, closed_by (nullable), closed_at (nullable), closing_count_aed (nullable), status (open|closed)
- `cash_drawer_events` — id, restaurant_id, session_id FK, type (cash_in|cash_out), amount_aed, reason, created_by

## 3. Flow

1. Manager opens a drawer session at start of day: `POST /api/v1/cash-drawer/sessions` with an opening float amount. Only one `status='open'` session per restaurant at a time (enforced in service, not DB constraint — DB constraints for "at most one open row" need a partial unique index, deferred as YAGNI until a second concurrent-open bug is actually seen).
2. Manager logs cash in/out during the day (e.g. paying out a rider's COD collection into the drawer, paying a supplier in cash): `POST /api/v1/cash-drawer/sessions/{id}/events`.
3. Manager closes the session with a physical cash count: `POST /api/v1/cash-drawer/sessions/{id}/close` — computes `expected = opening_float + sum(cash_in) - sum(cash_out)`, `variance = closing_count - expected`.
4. Z-report: `GET /api/v1/reports/z-report?date=YYYY-MM-DD` — aggregates that day's `Order` rows (gross sales, discounts via `coupon_discount_aed`, wallet applied, net COD due), `CodCollection` rows (cash actually collected by riders), and the day's cash drawer sessions (float, in/out, variance). Read-only aggregation query, no new write path.

## 4. API surface (new `src/app/cashdrawer/` module)

- `POST /api/v1/cash-drawer/sessions` — open (opening_float_aed)
- `GET /api/v1/cash-drawer/sessions/current` — the tenant's currently-open session, or 404
- `POST /api/v1/cash-drawer/sessions/{id}/events` — cash_in/cash_out (amount_aed, reason)
- `POST /api/v1/cash-drawer/sessions/{id}/close` — closing_count_aed
- `GET /api/v1/reports/z-report?date=` — aggregated day summary (new `src/app/reports/` module, since it's cross-cutting over orders+cod+drawer, not drawer-owned)

## 5. Testing

Unit: variance calculation (float + in - out vs count). Integration: open→events→close full lifecycle; double-open rejected; Z-report totals match hand-computed sums against seeded orders/collections.

## Related

- `src/app/cod/models.py` (existing rider-side COD collection/reconciliation — drawer is the restaurant-side counterpart)
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase C
