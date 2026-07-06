# Desktop Shell Foundation — Design Specification

Date: 2026-07-07
Status: Approved architecture (Electron shell over existing cloud backend)

## 1. Overview

Full POS's manager dashboard and all future counter-facing screens (KDS, register, floor management, etc. — see `docs/TRADITIONAL_POS_SYSTEM.md` §17 build order) move from browser-only web app to a **native Windows desktop application** (`.exe`, Electron-based), while the existing cloud backend (FastAPI + Celery + PostgreSQL/PostGIS + Redis, described in `docs/architecture.md`) stays exactly as-is and remains the system of record.

This spec covers only the **shell**: the Electron wrapper, local offline cache/queue, sync engine, and native hardware access layer. It introduces no new business features — those arrive in per-phase specs (Phase B: KDS, Phase C: payments, etc.) that build on top of this shell.

**Why:** the platform's traditional-POS gap analysis (`docs/TRADITIONAL_POS_SYSTEM.md` §12, §18) identifies offline resilience and native hardware access (printers, USB, drawers) as P0/P1 requirements a browser tab cannot satisfy reliably. Restaurant counters need software that keeps working when Wi-Fi drops and can talk directly to local hardware.

**Non-goals for this spec:** no new screens, no new business logic, no change to server-side APIs beyond adding sync endpoints. The existing React screens are reused unmodified in phase 1 of this rollout.

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Windows .exe (Electron)                                     │
│  ┌─────────────────────────┐   ┌───────────────────────────┐│
│  │ Renderer process         │   │ Main process               ││
│  │ (existing React/Vite     │◄─►│ - local SQLite cache/queue ││
│  │  frontend/, unmodified   │IPC│ - sync engine (push/pull)  ││
│  │  screens + new KDS etc.) │   │ - native printer/USB access││
│  └─────────────────────────┘   │ - system tray, auto-start   ││
│                                  └──────────────┬─────────────┘│
└─────────────────────────────────────────────────┼──────────────┘
                                                    │ HTTPS (existing REST
                                                    │  API + new /sync/* routes)
                                    ┌───────────────▼──────────────┐
                                    │ Existing cloud backend        │
                                    │ FastAPI + Celery + Postgres   │
                                    │ (unchanged, source of truth)  │
                                    └────────────────────────────────┘
```

- **Renderer process**: today's `frontend/` React app, unmodified. It no longer calls the cloud API directly — all data access goes through Electron's IPC bridge to the main process, which serves from local SQLite and queues writes.
- **Main process**: the new code in this spec. Owns the local SQLite database, a background sync loop, and native modules for hardware (printer/USB in later phases).
- **Cloud backend**: unchanged. Gets a new thin `sync` module (see §5) for batched pull/push; every other route stays as-is — the desktop app is just another authenticated client.

## 3. Local data model (SQLite, in Electron main process)

A local cache/queue, not a second source of truth. Mirrors a subset of server tables needed for offline operation:

- `local_menu` — mirrored read-only cache of active menu (dishes, categories, prices). Pulled on sync, never written locally.
- `local_orders` — orders created or modified while offline, plus a cached read view of recent server orders for display continuity.
- `pending_ops` — outbound queue: `id, entity, entity_id, op (create|update), payload JSON, created_at, status (pending|synced|failed|conflict), attempts`. This is the offline write queue — mirrors the server's own `outbox_messages` pattern (append, deliver, retry, dead-letter) but for **outbound API calls** instead of WhatsApp sends.
- `sync_state` — single row per entity type: `last_synced_at`, `last_cursor` (for incremental pull).

**Authority rule:** money-moving and audit-relevant fields (order totals, payment status, SLA timestamps) are never resolved locally — `pending_ops` entries for these always go through full server-side validation on sync; the local cache only reflects the last known server state until confirmed. Non-critical UI state (e.g. which KDS ticket is being viewed) has no server round-trip at all.

## 4. Sync engine

- **Push:** background loop (every N seconds when online, or immediately on network-reconnect event) drains `pending_ops` FIFO per entity, POSTs each to the existing REST endpoint it corresponds to (e.g. an order-status bump queued offline replays as the same `PATCH /api/v1/orders/{id}/status` call the online UI would have made — no bespoke sync protocol, just replay of the normal API with an idempotency key).
- **Idempotency:** every queued op carries a client-generated UUID sent as an `Idempotency-Key` header; server dedupes (new lightweight table `idempotency_keys` scoped by `restaurant_id`, short retention) so replay-after-partial-failure can't double-apply.
- **Pull:** periodic + on-reconnect fetch of anything changed since `last_cursor` (menu updates, order status changes made from other terminals) via existing endpoints with an `updated_since` filter; written into local cache tables.
- **Conflict handling:** last-write-wins is *not* used for anything financial. If a queued op is rejected by the server (e.g. order already cancelled by another terminal), it's marked `conflict` in `pending_ops`, surfaced in the UI for a human to resolve — never silently dropped or overwritten (matches your no-deletions/add-and-edit-only constraint: conflicts are marked, not erased).
- **Retry/backoff:** exponential backoff per op, same shape as `outbox/worker.py`'s existing retry logic server-side — same pattern, client-side.

## 5. Server-side additions (minimal)

- New `sync` concerns bolted onto existing routers, not a new bounded context: `updated_since` query param support on menu/orders list endpoints (pull), `Idempotency-Key` header support + `idempotency_keys` table (push dedup).
- No change to business logic, FSMs, or existing bounded contexts (`ordering`, `menu`, etc.) — sync is transport, not a new domain.

## 6. Native hardware access layer

- Lives in the Electron main process (Node.js has direct OS access — no browser sandbox restriction).
- Printer/USB/drawer integrations are **not built in this spec** — this spec only establishes the main-process module boundary (`src/native/printer.ts`, `src/native/usb.ts` stubs) that Phase B (KDS printer routing) and Phase F (hardware SDK) will implement into. Establishing the boundary now means KDS's print job delivery (Phase B) doesn't need a separate standalone bridge process — it runs in the same Electron main process already talking to local hardware.

## 7. Packaging & distribution

- `electron-builder` produces a signed Windows installer (`.exe`) from the existing `frontend/` build output + new Electron main-process code (new `desktop/` directory at repo root, alongside `frontend/`).
- Auto-update: electron-builder's built-in updater checks a version manifest served by the existing backend (new static route), so restaurants get shell/bugfix updates without manual reinstall.
- System tray icon + auto-start on Windows boot (so the register/KDS machine is always ready without staff manually launching an app).

## 8. Error handling matrix (additions to existing table in the main spec)

| Failure | Behavior |
|---|---|
| Internet down | Renderer keeps working off local SQLite cache; writes queue in `pending_ops`; tray icon shows offline indicator |
| Sync push rejected (conflict) | Op marked `conflict`, surfaced in UI, never auto-overwritten or silently dropped |
| Electron main process crash | Auto-restart via electron-builder's crash reporter + relaunch; pending_ops persisted to disk (SQLite file), nothing lost |
| Server unreachable during startup | App opens in offline mode against last-synced local cache, banner shown |

## 9. Testing strategy

- **Unit:** `pending_ops` queue drain logic, idempotency key generation, conflict-marking logic — pure functions, no Electron needed, run under Vitest same as existing frontend tests.
- **Integration:** sync engine against a real (test) FastAPI instance — push/pull round trip, idempotency replay dedup, `updated_since` pull correctness.
- **E2E:** Playwright-in-Electron (Playwright supports Electron apps directly) — launch app, go offline (mock network), create/modify an order, go online, assert it synced.
- **Manual/UAT:** kill Wi-Fi mid-session on a real Windows machine, confirm app keeps working and syncs cleanly on reconnect.

## 10. Delivery phases (this spec only)

1. Electron shell wrapping existing `frontend/` unmodified, online-only (no offline queue yet) — proves packaging/distribution works.
2. Local SQLite cache (read-only mirror) + pull sync.
3. `pending_ops` write queue + push sync + idempotency.
4. Conflict UI surfacing + native hardware module stubs (empty, ready for Phase B to fill in).

Each step ships with passing tests + a working `.exe` install demo.

## Related documents

- Traditional POS capability reference: `docs/TRADITIONAL_POS_SYSTEM.md`
- Current architecture (backend, unchanged): `docs/architecture.md`
- Business rules spec (unchanged): `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`
- Next spec: Phase B — Kitchen/KDS (builds on this shell)
