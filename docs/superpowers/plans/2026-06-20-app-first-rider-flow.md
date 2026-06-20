# Plan: App-first rider flow (native app primary, WhatsApp fallback)

**Date:** 2026-06-20
**Status:** Proposed (awaiting go on Phase A)

## Goal

Move the rider's operational flow — pickup, delivery status, COD, GPS, and
(later) chat — out of WhatsApp buttons and into the **native Android app**, with
**push notifications** pulling the rider in. **Customer ordering stays on
WhatsApp.** The existing WhatsApp rider flow + web tracker remain as a
**fallback** (app not installed / iOS / app closed) and are NOT removed.

## Why

- Background GPS is reliable in the app; the WhatsApp "keep the web page open"
  flow is fragile (riders don't keep it open — confirmed with the user).
- Push notifications wake the rider; no dependence on WhatsApp's 24h window.
- One surface for everything the rider does.

## Non-negotiables / constraints

- **iOS deferred** → iOS riders keep WhatsApp + web tracker. App-first = Android-first.
- **Keep the WhatsApp rider flow working** throughout (fallback). No big-bang cutover.
- COD-only, 40-min SLA, employee riders (no accept/reject) — unchanged (spec).
- Reuse FSM transitions; never duplicate order/delivery status logic.

## Architectural key: transport-agnostic rider service

Today `dispatch/rider_flow.py` couples FSM transitions to WhatsApp
(`handle_orders_picked`, `handle_delivered` build WhatsApp messages inline).

**Refactor first:** extract the pure state transitions into
`dispatch/rider_actions.py` (transport-agnostic):
- `mark_batch_picked_up(session, rider, batch_id) -> PickupResult`
- `mark_order_delivered(session, rider, order_id, cod_collected) -> DeliverResult`
- `active_batch_for(session, rider) -> BatchView` (orders, stops, COD, coords)

Both the **WhatsApp handlers** (existing) and the **new app endpoints** call these.
WhatsApp handlers keep their message-building; app endpoints return JSON. This is
the one piece that makes everything else clean — do it before Phase A features.

---

## Phase A — Push notifications + app-driven pickup/delivered/COD

**Backend**
- `riders.push_token` column (Expo push token) + migration (+ updated_at trigger).
- `POST /api/v1/rider-app/push-token` — app registers/refreshes its Expo token.
- Push sender port: `notifications/push.py` (Expo Push API; `FakePush` for tests).
- On dispatch assignment → send push "New delivery assigned — open app".
- New rider-app endpoints (call the transport-agnostic service):
  - `GET  /api/v1/rider-app/orders` — current batch + stops + COD + coords.
  - `POST /api/v1/rider-app/orders/pickup` — mark batch picked up.
  - `POST /api/v1/rider-app/orders/{id}/delivered` — deliver + record COD.
- Reuse existing `/rider-app/location` for GPS (already live).

**App (rider-app/)**
- `expo-notifications`: register, get push token, POST to backend; tap → open active delivery.
- Active-delivery screen: **Picked up** button → then per-stop **Delivered / Collect COD**.
- Background GPS already streams (no change); first-stop reveal now keyed off app pings.

**Tests:** unit (service transitions), integration (endpoints w/ FakePush),
push-token persistence, assignment→push fires, regression on WhatsApp fallback.

**Exit:** an Android rider can do a full delivery in-app (notified → open →
pickup → GPS → delivered → COD) with zero WhatsApp taps; WhatsApp still works.

---

## Phase B — Order list / detail screens

- App: list of assigned stops, order items, customer name/address, COD amount,
  one-tap **Navigate** (Google Maps deep link), delivery sequence.
- Backend: extend `GET /rider-app/orders` payload (items, address, sequence) — no new FSM.
- Tests: payload shape, multi-stop batch ordering.

**Exit:** rider sees the whole run and navigates per stop without WhatsApp.

---

## Phase C — Rider ↔ restaurant chat

- Backend: `rider_messages` table (rider_id, direction, body, ts) + endpoints
  (`GET/POST /api/v1/rider-app/messages`), push on inbound to rider.
- App: chat screen. Dashboard: rider chat panel (frontend) + manager send endpoint.
- Tests: send/receive both directions, push on new message, tenant isolation.

**Exit:** rider and restaurant communicate in-app; no WhatsApp needed for ops.

---

## Sequencing & risk

1. **Refactor to transport-agnostic service** (no behavior change; full green tests).
2. **Phase A** (the core value — notifications + in-app actions).
3. **Phase B**, then **Phase C**.

Each phase: TDD, full test matrix, graph update, conventional commits, keep
WhatsApp fallback green. iOS native build is a separate future track.
