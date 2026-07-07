# Table & Floor Management — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase D)

## 1. Scope

Dine-in table/floor management, independent of delivery ordering. Adds a physical
table concept for walk-in customers, distinct from the delivery `Order`/`CustomerAddress`
flow. A dine-in order still uses the existing `Order`/`OrderItem` models (so KDS,
cash drawer, Z-report all work unchanged) — a table is just an additional binding
on top of an order plus a floor-plan/status layer for the manager screen.

## 2. Data model

- `tables` — id, restaurant_id, label (e.g. "T12"), seats (int), pos_x/pos_y (float, floor-plan layout coordinates), status (available|seated|ordered|needs_bill|cleaning)
- `orders` gets `table_id` (nullable FK) — null for delivery orders, set for dine-in.

## 3. Flow

1. Manager creates tables once during setup: `POST /api/v1/tables`.
2. Server seats a table: `PATCH /api/v1/tables/{id}/status` → `seated`.
3. Server opens a dine-in order against that table (reuses the existing `Order`
   creation path — dine-in orders skip delivery fields: no address, no rider,
   `delivery_fee_aed=0`), table auto-flips to `ordered` when the order is created against it.
4. Table transfer: `PATCH /api/v1/tables/{id}/transfer-order` moves an order's
   `table_id` to a different table (e.g. guests move seats) — pure FK repoint, audited.
5. Split/merge checks: **not** modeled as new order-splitting logic (that would
   duplicate the entire OrderItem/pricing/SLA machinery) — deferred to a later
   pass once dine-in ordering itself is validated with real usage. This phase
   ships the floor plan + table lifecycle only.
6. Manager clears table after payment: `PATCH /api/v1/tables/{id}/status` → `cleaning` → `available`.

## 4. API surface (new `src/app/tables/` module)

- `POST /api/v1/tables` — create (label, seats, pos_x, pos_y)
- `GET /api/v1/tables` — floor plan list (id, label, seats, pos_x, pos_y, status, current order summary if any)
- `PATCH /api/v1/tables/{id}/status` — status transition, audited
- `PATCH /api/v1/tables/{id}/transfer-order` — move an order's table_id, audited

## 5. Testing

Unit: status transition validity (can't go straight from `available` to `needs_bill`). Integration: create table → seat → attach order → table auto-flips to `ordered` → transfer → clear.

## Related
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase D
- Split/merge checks explicitly deferred — see §3.5 above (YAGNI until dine-in ordering itself ships and is used)
