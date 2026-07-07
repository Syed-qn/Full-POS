# Kitchen/KDS — Design Specification

Date: 2026-07-07
Status: Approved (per prior in-session discussion, Traditional POS §17 Phase B)

## 1. Overview

Native Kitchen Display System + printer routing, built on the desktop shell foundation.
Every order line gets a station-scoped, per-item status; screens per station show
tickets with age-based urgency color; printers get a redundant copy via the same
Electron main process that already has native hardware access (`desktop/src/main/native/`
stubs from the foundation phase).

**Non-negotiable per spec/CLAUDE.md:** multi-tenant (`restaurant_id` everywhere), audit
every kitchen status transition, TDD, no deletions (bump/recall is a status transition,
never a row delete).

## 2. Data model

- `kitchen_stations` — id, restaurant_id, name, printer_ip, printer_port (nullable — USB stations have none)
- `category_station_defaults` — id, restaurant_id, category (string — `dishes.category` is a free-text column, not an FK, so this maps that same string to a default station), station_id FK. Unique(restaurant_id, category).
- `dishes` (existing) gets `station_id` FK (nullable — falls back to `category_station_defaults` lookup by `dishes.category`), `prep_minutes` numeric nullable
- `order_items` (existing) gets `kitchen_status` (received|preparing|ready|bumped, default received on insert), `bumped_at` nullable, `station_id_snapshot` FK (captured at ticket-creation time, so later station reassignment doesn't retroactively move an in-flight ticket)
- `print_jobs` — id, restaurant_id, station_id, order_id, payload (text), status (pending|sent|failed|dead), attempts, mirrors `outbox_messages`' exact shape/retry pattern

## 3. Flow

1. Order reaches a kitchen-visible status (`confirmed`) → `kds/service.py` sets `kitchen_status='received'` + `station_id_snapshot` on each `order_item` (resolved: dish.station_id → category.default_station_id → a restaurant-level fallback "Main" station created on first use) and enqueues one `print_jobs` row per distinct station touched, same transaction as the status change (same pattern as outbox).
2. Desktop app's KDS screen (`frontend/src/screens/KdsScreen.tsx`, new route `/kds/:stationId`) polls `GET /api/v1/kds/stations/{id}/tickets` — returns order_items grouped by order, with `prep_minutes` from the dish snapshot and elapsed-time-based color (yellow @80% prep_minutes, red @100%).
3. Cook taps item → `PATCH /api/v1/kds/items/{id}/bump` → `kitchen_status='ready'`, audited. All items on an order ready → order-level ticket auto-clears from the active view (still `preparing` order status — KDS bump doesn't drive the order FSM, kitchen "ready" is signaled back to the order FSM separately via existing `advance` flow). Recall = `PATCH .../recall` reverts the last bump (soft, no delete).
4. Print delivery: Electron main process (already has `native/printer.ts`'s `PrinterPort` boundary) implements a real ESC/POS driver against `kitchen_stations.printer_ip/port`, polling `GET /api/v1/kds/print-jobs/pending` the same way `pos-api-request`/scheduler already poll — reuses the existing sync scheduler infrastructure, doesn't invent a new polling loop.
5. KDS screen is primary; printer fires always (redundancy, not failover), matching the desktop-shell-foundation spec's already-decided answer.

## 4. API surface (new `src/app/kds/` module: models.py/schemas.py/service.py/router.py)

- `GET /api/v1/kds/stations` — list stations for the tenant
- `POST /api/v1/kds/stations` — create a station (name, printer_ip/port optional)
- `GET /api/v1/kds/stations/{id}/tickets` — active (non-bumped) order_items for that station
- `PATCH /api/v1/kds/items/{id}/bump`
- `PATCH /api/v1/kds/items/{id}/recall`
- `GET /api/v1/kds/print-jobs/pending` — for the Electron print poller
- `PATCH /api/v1/kds/print-jobs/{id}/status` — poller reports sent/failed

## 5. Testing

Unit: per-item status transition guard (illegal transition raises), station-resolution fallback chain (dish → category → default), age-color threshold calc.
Integration: order confirmed → kitchen tickets + print_jobs created in one transaction (assert both or neither).
E2E: simulator order → ticket appears on the right station → bump → cleared.

## Related

- `docs/TRADITIONAL_POS_SYSTEM.md` §4, §17 (Phase B)
- `docs/superpowers/specs/2026-07-07-desktop-shell-foundation-design.md` (native hardware boundary, sync scheduler this reuses)
