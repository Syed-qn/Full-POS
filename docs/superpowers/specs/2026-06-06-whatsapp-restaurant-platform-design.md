# WhatsApp Restaurant Platform — Design Specification

Date: 2026-06-06
Status: Approved architecture (Approach A — modular monolith)

## 1. Overview

Multi-tenant SaaS platform where restaurants run their entire delivery operation through WhatsApp: customer ordering, AI menu digitization, intelligent dish matching, own-fleet rider dispatch with live tracking, smart batching under a hard 40-minute SLA, AI+ML demand predictions, and Klaviyo-style marketing automation — plus a web dashboard for managers.

**Actors:**
- **Customer** — orders via WhatsApp chat. Never sees an app or website.
- **Rider** — restaurant employee. Receives assignments, shares live location, completes deliveries — all via WhatsApp.
- **Manager** — onboards restaurant, confirms AI-parsed menu, watches dashboard, overrides anything.
- **Background jobs** — dispatch engine, SLA monitor, schedulers, ML retraining, template lifecycle.

**Hard business rules (non-negotiable):**
- COD only. Max delivery radius 10 km. Delivery fees: ≤3 km free, 3–5 km AED 5, >5 km AED 10.
- SLA: 40 min customer-facing, 30 min internal target, 10 min buffer per batched order.
- Riders never reject assignments (employees). Manager can deactivate a rider from future assignment.
- Order modification allowed only before `ready`/`picked_up`; restarts the 40-min SLA clock after customer confirms new ETA.
- Late delivery (>40 min, system/rider fault) → automatic coupon. Rain/weather-delay disclosed at order time → no coupon.
- Cancellation after cooking started → order auto-listed for resale, excluded from same phone/person/address.
- Dish numbers are mandatory and come from the restaurant's menu.
- Customer-facing dish info: name + description (max 3 lines), never price in descriptions.

## 2. Architecture (Approach A — approved)

Modular monolith with strict bounded contexts + async workers. One deployable API, one worker fleet, one database.

```
┌────────────────────────────────────────────────────────────────┐
│  React Dashboard SPA (manager)                                  │
└───────────────┬────────────────────────────────────────────────┘
                │ REST + WebSocket
┌───────────────▼────────────────────────────────────────────────┐
│  FastAPI app (apps/api)                                         │
│  /webhooks/whatsapp   /api/v1/*   /ws/dashboard                 │
├─────────────────────────────────────────────────────────────────┤
│  Core domain modules (src/<module>) — import-isolated           │
│  identity · menu · catalog_ai · conversation · ordering         │
│  dispatch · riders · tracking · sla · coupons · cod             │
│  predictions · marketing · segments · notifications             │
│  whatsapp (adapter) · llm (port) · geo (port) · audit · outbox  │
├─────────────────────────────────────────────────────────────────┤
│  Celery workers (apps/workers) — queues:                        │
│  dispatch · sla_monitor · schedulers · ml · marketing · outbox  │
├──────────────┬──────────────────┬───────────────────────────────┤
│ PostgreSQL   │ Redis            │ External: WhatsApp Cloud API  │
│ + PostGIS    │ cache/queue/geo  │ Google Maps · Claude API      │
│              │ hot positions    │ Weather API                   │
└──────────────┴──────────────────┴───────────────────────────────┘
```

**Enterprise discipline (what makes it enterprise-grade):**
- **Audit log** — append-only record of every state transition, actor, payload diff.
- **Outbox pattern** — every outbound WhatsApp message written transactionally to `outbox_messages`, delivered by worker with retry + dead-letter. No lost sends.
- **Idempotent webhooks** — `webhook_events` table keyed by provider message ID; duplicates ignored.
- **Explicit FSMs** — Order and Delivery state machines; illegal transitions raise, all transitions audited.
- **Graceful degradation** — LLM down → dish-number-only matching + manager alert; Maps down → haversine + static speed model; WhatsApp template rejected → fallback pre-approved template.
- **Manual override everywhere** — manager can take over any conversation, reassign any rider, force any state.

### Tech stack

| Layer | Choice |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Workers | Celery + Redis broker, Celery Beat for cron |
| DB | PostgreSQL 16 + PostGIS (geo), single DB, `restaurant_id` scoping on every tenant table |
| Cache/geo | Redis 7 (rider hot positions via GEO commands, dispatch locks, rate limits) |
| Realtime | WebSocket (FastAPI) for dashboard live updates |
| LLM | Claude API (vision menu extraction, fuzzy-match arbitration, descriptions, template generation, plain-English segments, prediction adjustment) behind `llm/` port |
| ML | LightGBM demand models, per restaurant; weekly retrain via Celery Beat |
| Maps | Google Maps Platform (Routes API w/ traffic, Distance Matrix, Geocoding) behind `geo/` port; haversine fallback |
| WhatsApp | Cloud API behind `whatsapp/` adapter; `MockProvider` + web simulator for dev |
| Dashboard | React + TypeScript + Vite, distinctive design (frontend-design treatment at implementation) |
| Infra (dev) | docker-compose: postgres+postgis, redis, api, workers, dashboard, simulator |
| Tests | pytest + pytest-asyncio, factory fixtures, FSM property tests, dispatch simulation harness |

## 3. Data model (core tables)

All tenant tables carry `restaurant_id FK` + composite indexes. Timestamps `created_at/updated_at` everywhere. Soft deletes only where business requires (dishes).

**identity**
- `restaurants` — id, name, phone (WABA number), location `geography(Point)`, password_hash, settings JSONB (max_orders_per_batch, max_items_per_order, delivery fee tiers, radius_km=10)
- `manager_users` — id, restaurant_id, name, phone, password_hash, role
- `riders` — id, restaurant_id, name, phone (WhatsApp), status (`available|on_delivery|off_shift|deactivated`), performance JSONB (on_time_pct, avg_delivery_min)

**menu**
- `menus` — id, restaurant_id, version, status (`processing|pending_confirmation|active|superseded`), source_files JSONB
- `dishes` — id, menu_id, restaurant_id, dish_number (int, required, unique per active menu), name, price_aed numeric, category, description, is_available bool, name_normalized (for trigram), embedding vector (optional later)
- Price-change detection: new upload matched on (dish_number, name) → diff report → manager confirms.

**customers & addresses**
- `customers` — id, restaurant_id, phone (unique per restaurant), name, first_order_at, last_order_at, usual_order_times JSONB (per weekday), tags JSONB, total_orders, total_spend
- `customer_addresses` — id, customer_id, location `geography(Point)` (WhatsApp pin), room_apartment, building, receiver_name, additional_details, confirmed bool, last_used_at. Address text format: `room/apartment, building` comma-separated, parsed + echoed back for confirmation before storing. Reused on future orders.

**conversation**
- `conversations` — id, restaurant_id, counterpart (customer|rider), phone, state JSONB (dialogue state machine), manual_takeover bool, taken_over_by
- `messages` — id, conversation_id, direction, wa_message_id, type, payload JSONB, ts

**ordering**
- `orders` — id, restaurant_id, customer_id, order_number (human, per-restaurant sequence), status FSM, items snapshot via `order_items`, additional_details text (verbatim to restaurant), address_id, distance_km, delivery_fee_aed, subtotal, total, priority (`normal|high`), weather_delay_disclosed bool, sla_confirmed_at (clock start), sla_deadline (confirmed_at+40min, reset on confirmed modification), promised_eta, delivered_at, late bool, coupon_id, cancellation fields, resale fields (resale_of_order_id, excluded_phone/address hash)
- `order_items` — order_id, dish_id snapshot (number, name, price at order time), qty, notes
- Order FSM: `draft → pending_confirmation → confirmed → preparing → ready → assigned → picked_up → arriving → delivered` | `cancelled` | `undeliverable` (out of radius / customer unreachable → "Sorry not deliverable") | `on_resale → resold|written_off`

**dispatch & tracking**
- `batches` — id, restaurant_id, rider_id, status (`planned|picked_up|in_progress|completed`), route JSONB (ordered stops + ETAs), total_est_min
- `batch_orders` — batch_id, order_id, sequence, delivered_at
- `rider_locations` — rider_id, location, ts (time series; hot copy in Redis GEO)
- `assignments` audit — order_id, rider_id, batch_id, assigned_at, algorithm_score JSONB (explainability: why this rider)

**sla & coupons**
- `sla_events` — order_id, type (`yellow_30|red_35|breach_40`), ts, notified JSONB
- `coupons` — id, restaurant_id, customer_id, order_id (cause), code, value/percent, status (`issued|redeemed|expired`), expires_at

**cod**
- `cod_collections` — order_id, rider_id, amount, collected_at (set by "Collect money & delivered" button)
- `rider_shift_reconciliations` — rider_id, date, expected_total, collected_total, variance, status

**predictions**
- `prediction_runs` — restaurant_id, horizon (`next_1h|breakfast|lunch|dinner|midnight`), predicted JSONB (order_count, revenue, top_dishes, avg_distance), actual JSONB (backfilled), accuracy
- `model_registry` — restaurant_id, model_type, version, trained_at, metrics JSONB
- `manager_overrides` — restaurant_id, text (plain English), parsed_effect JSONB, active_window, applied_to_runs

**marketing**
- `wa_templates` — id, restaurant_id, meta_template_name, category, body/header/buttons JSONB, status (`draft|pending_meta|approved|rejected|sent|deleted`), ephemeral bool (daily specials auto-delete end-of-day), rejection_reason
- `campaigns` — id, restaurant_id, type (`todays_special|recurring|automation`), template_id, segment_id, image_url, schedule, stats JSONB
- `segments` — id, restaurant_id, name, definition JSONB (DSL compiled from plain English by LLM; preview count shown before save)
- `automations` — id, restaurant_id, trigger DSL, condition DSL, action DSL, plain_english_source, enabled
- `recurring_message_state` — customer_id, next_send_at (order day +3, then weekly same weekday, at usual_order_time −15 min), suppressed_until

**platform**
- `audit_log` — actor (system|manager|rider|customer), restaurant_id, entity, entity_id, action, before/after JSONB, ts
- `outbox_messages` — id, restaurant_id, to_phone, payload JSONB, status (`pending|sent|failed|dead`), attempts, wa_message_id, idempotency_key
- `webhook_events` — provider_event_id unique, payload, processed_at

## 4. Key flows

### 4.1 Restaurant onboarding
1. Signup: name, phone, Google Maps location (geocoded + pin confirm), password.
2. Menu upload (PDF/JPEG/PNG/multi-file) → `catalog_ai` extracts via Claude vision: dish_number, name, price, category, description — all available details.
3. Parsed menu shown in dashboard for confirmation; manager edits (add/remove/rename/reprice) before activation. Dish numbers mandatory — extraction failures flagged for manual entry.
4. Re-upload flow: diff by (dish_number, name) → price-change report → manager confirms → new menu version activates atomically.
5. Rider registration (name + WhatsApp phone). Delivery fee tiers + batch config (defaults per business rules).

### 4.2 Customer ordering (conversation engine)
Dialogue state machine per conversation, LLM-assisted intent parse:
1. Greeting → send digital menu (formatted list by category, `110. Chicken Biryani — AED 22`), never raw PDFs.
2. Dish capture: pg_trgm fuzzy match on normalized names + abbreviation expansion; reply-to-old-message handling (parse quoted message, re-confirm with current prices).
   - 1 strong match → confirm `110. Chicken Biryani - AED 22?`
   - Multiple → `Do you mean 110. Chicken Biryani - AED 22 or 111. Special Chicken Biryani - AED 28?`
   - No match → ask for dish number → still nothing → LLM arbitration → manager alert if hopeless.
3. "What is X?" → LLM description, max 3 lines, name + details, **no price**.
4. Special requests → verbatim into `additional_details`, shown exactly to restaurant.
5. Address: request WhatsApp location pin (validate ≤10 km — else "Sorry not deliverable") + text `room/apartment, building` (comma-mandatory; parse → echo `room/apartment number 111 building 1-2` → confirm → store). Receiver name + additional details. Returning customers: offer stored address.
6. Weather check: if rain/delay conditions active → inform customer in confirmation (suppresses coupon for this order).
7. Confirmation message: items, totals, delivery fee, address, COD reminder, ETA (40 min). `sla_confirmed_at` set. Kitchen notified.
8. Modification (only before `ready`): recalc ETA → customer must confirm → order updated, rider/batch notified, SLA clock restarts.
9. "Where is my order?" → status + live ETA from rider position via Routes API + buffer.

### 4.3 Dispatch engine (the brain)
Triggers: order → `ready`; rider freed; priority order arrival; modification. Runs as Celery task with Redis lock per restaurant.

1. **Eligible set**: ready unassigned orders + available riders (employees — no accept step).
2. **Batching**: cluster orders by destination proximity (PostGIS). Candidate batch valid iff for EVERY order in it: `now − sla_confirmed_at + route_time_to_that_stop (traffic-aware) + 10 min/order buffer ≤ 30 min internal target`. Manager caps: max orders/batch, max items/order. If a new same-area order can't fit → dispatch current batch immediately, start new one.
3. **Priority orders**: protected first — single-rider dispatch if batching threatens their SLA.
4. **Rider scoring**: distance to restaurant, current workload, area performance, on-time %. Score persisted to `assignments.algorithm_score` (explainability).
5. **Route sequencing**: nearest-neighbor + 2-opt over Google Routes durations; priority stops first.
6. **Dynamic re-optimization**: rider freed early / detour detected / new priority → re-run; all downstream order ETAs updated (+10 min buffer each), customers proactively messaged on change.
7. **Resale orders**: cancelled-after-cooking orders enter resale queue → offered as fast-delivery to suitable active conversations / next matching order, never to same phone/person/address.

### 4.4 Rider flow (WhatsApp only)
1. Shift start → rider shares live location (all day; power bank provided per ops policy). Positions land in Redis GEO + `rider_locations`.
2. Orders ready → rider gets order numbers (batch-aware) → goes to kitchen.
3. Taps **"Orders Picked"** → first stop location pin + Google Maps navigation link + customer name/contact (riders see customer contact; customers see rider name + "Message rider" button, not raw number).
4. Geofence worker watches rider position; at ~100 m from stop → buttons: **"Delivered"** | **"Delivered and Next Order Location"**. Button click is the ONLY way to get next location (forces flow integrity). COD: button labeled "Collect money & delivered" → writes `cod_collections`.
5. Last order delivered → "Head back to restaurant" → status `available` on arrival geofence. Cycle continues.
6. Stale location (>3 min) → rider nudge + manager alert; dispatch avoids stale riders.

### 4.5 SLA monitor & coupons
- Heartbeat worker (30 s): orders vs `sla_deadline`. 30 min → yellow dashboard alert; 35 min → red + manager push; breach → if `weather_delay_disclosed` = false → auto-issue coupon, WhatsApp apology with coupon code; else apology only.
- Coupon redemption: code recognized at next order, applied to total, single-use.

### 4.6 Predictions (AI + ML)
- **ML layer**: LightGBM per restaurant — order count, revenue, avg distance, dish-level demand. Features: hour/dow/holiday/Ramadan calendar, weather forecast, trailing demand, disabled dishes, campaign activity. Horizons: next 1 h + breakfast/lunch/dinner/midnight windows.
- **LLM layer**: Claude adjusts ML output with context ML can't see — manager plain-English overrides ("big corporate order Thursday", "road closed"), events, anomalies — returns adjusted prediction + reasoning shown on dashboard.
- Weekly retrain (manager-configurable day/time, default Mon 04:00). Accuracy tracked per run (target ~80%; MAPE dashboard). Actuals backfilled for evaluation + retraining.

### 4.7 Marketing automation
- **Recurring**: after each order, scheduler sets: promo at day +3, then weekly same weekday, send time = customer's usual order time for that weekday − 15 min (e.g., orders 10:00 → send 09:45). Habit drift updates `usual_order_times` (recency-weighted). Frequency caps + opt-out honored.
- **Today's Special**: manager uploads image + text → Claude generates Meta-compliant marketing template (image header, body, CTA buttons; compliance lint pass) → manager preview/edit → submit to Meta approval → poll status → on approval send to chosen segment(s) or all → template auto-deleted end of day (`ephemeral`). Rejection → AI suggests fix → resubmit; pre-approved generic fallback template always available.
- **Segments & automations (Klaviyo-style)**: manager types plain English ("customers who ordered biryani 3+ times last 30 days") → LLM compiles to validated DSL → preview audience count → save. Automations: trigger/condition/action DSL from plain English; AI has template creation + content access within compliance guardrails.

### 4.8 Dashboard (React)
KPIs (orders, revenue, AOV, avg delivery time, SLA %, late count, coupons issued) · live dispatch map (riders, active orders, batches) · SLA board (yellow/red) · predictions panel + plain-English override box · menu manager (parsed-menu confirmation, dish disable — immediate menu effect) · marketing studio (today's special, segments, automations, template status) · rider management (shift on/off, deactivate-from-assignment, COD reconciliation) · conversation viewer + manual takeover · audit explorer.

## 5. Error handling matrix

| Failure | Behavior |
|---|---|
| LLM API down | Dish-number-only ordering, canned dialogue, manager alert |
| Maps API down | Haversine + static speed (25 km/h city) + widened buffers; flag ETAs as estimates |
| WhatsApp send fails | Outbox retry w/ backoff → dead-letter → manager alert |
| Webhook duplicate/replay | Idempotency table drop |
| Rider offline mid-delivery | Stale-location alert, manager reassignment tools |
| Template rejected by Meta | AI revision loop + fallback template |
| Customer unreachable at door | Rider "Customer unavailable" flow → manager decides (retry/return); order → `undeliverable` |
| Kitchen overload (orders > capacity) | Prediction-informed warning; manager can pause new orders (menu auto-replies "temporarily closed") |
| DB/Redis outage | Health checks, API 503s with retry-after; WhatsApp messages queue at Meta side |

## 6. Security & privacy
- Tenant isolation: every query scoped by `restaurant_id`; FastAPI dependency injects tenant context from auth.
- Auth: manager JWT (short-lived) + refresh; password hashing argon2; webhook signature verification (Meta `X-Hub-Signature-256`).
- PII: customer phone/address encrypted at rest (pgcrypto), rider personal numbers never sent to customers; data retention policy on location time series (30 days raw, aggregates kept).
- Rate limiting per phone + per tenant; audit log immutable (no UPDATE/DELETE grants).

## 7. Testing strategy
- Unit: FSM transitions (property tests — no illegal transition possible), fee calculator, address parser, fuzzy matcher corpus (misspellings: "chikn briyani" → confirm flow).
- Integration: webhook → conversation → order pipeline against MockProvider; dispatch simulation harness (seeded order/rider scenarios incl. the A,B,A,D,B,A batching case) asserting SLA invariants.
- Contract: WhatsApp adapter conformance tests run against both Mock and Cloud providers (Cloud in CI optional).
- E2E: simulator-driven full conversations (order, modify, cancel, "where is my order", rider full cycle).
- Load: Locust profile for peak-hour webhook bursts.

## 8. Delivery phases
0. **Scaffold** — repo, docker-compose, FastAPI+Celery skeleton, settings, CI, Alembic, audit/outbox primitives.
1. **Identity + Menu** — signup, auth, menu upload, Claude vision extraction, manager confirm/edit, versioned re-upload diff.
2. **WhatsApp core** — adapter (Mock + Cloud), webhook pipeline, outbox, conversation engine, simulator.
3. **Ordering** — fuzzy matching, dialogue flows, address capture/confirm/store, order FSM, confirmation, modification, cancellation/resale.
4. **Logistics** — riders, live tracking, geofences, dispatch engine + batching, SLA monitor, coupons, COD ledger.
5. **Dashboard** — full React app (frontend-design treatment), WebSocket live updates.
6. **Predictions** — feature store, LightGBM training, LLM adjustment, override box, accuracy tracking.
7. **Marketing** — recurring scheduler, today's special pipeline w/ Meta approval lifecycle, plain-English segments/automations.
8. **Hardening** — load tests, rate limits, observability (structured logs, metrics, tracing), security pass.

Each phase ends with passing tests + working demo via simulator.
