# Staff & Labor — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase G, scoped)

## 1. Scope decision

Full RBAC (cashier/kitchen/manager roles enforced on every router) is an
identity-layer rewrite touching every existing endpoint's auth dependency —
too invasive to bolt on here without its own dedicated pass. **Deferred.**
Payroll integration needs a real third-party payroll vendor — **out of scope**,
same reasoning as Phase C's card gateway.

What's real and buildable now: staff records, clock-in/out, and per-order
staff attribution (sales-per-server) — the data layer RBAC and payroll will
eventually sit on top of.

## 2. Data model

- `staff_members` — id, restaurant_id, name, phone, role (string, informational only — not yet enforced), pin_hash (4-6 digit PIN for quick clock-in, hashed same as restaurant passwords)
- `clock_events` — id, restaurant_id, staff_id FK, type (clock_in|clock_out), at (datetime)
- `orders` gets `staff_id` (nullable FK) — who took/served the order, for sales-per-server.

## 3. Flow

1. Manager adds staff: `POST /api/v1/staff`.
2. Staff clocks in/out with their PIN: `POST /api/v1/staff/{id}/clock` (type=clock_in|clock_out). Reject clock_in if already clocked in (no open clock_in without a matching clock_out), same guard shape as the cash drawer's single-open-session rule.
3. `GET /api/v1/staff/{id}/hours?date=` — sums clocked minutes for a day from paired clock_in/clock_out events.
4. Sales-per-server: `GET /api/v1/staff/{id}/sales?date=` — sums `Order.total` for orders with that `staff_id` on that day (reuses the Z-report's date-window pattern).

## 4. API surface (new `src/app/staff/` module)

- `POST /api/v1/staff` — create
- `GET /api/v1/staff` — list
- `POST /api/v1/staff/{id}/clock` — clock in/out
- `GET /api/v1/staff/{id}/hours?date=`
- `GET /api/v1/staff/{id}/sales?date=`

## 5. Testing

Unit: clock-in-while-already-clocked-in rejected; hours computed correctly across paired events. Integration: full clock in → clock out → hours query cycle; sales query against seeded orders.

## Related
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase G
- RBAC and payroll integration explicitly deferred (see §1)
