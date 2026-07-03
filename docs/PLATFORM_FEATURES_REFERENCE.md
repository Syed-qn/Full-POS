# Restaurant WhatsApp Platform — Complete Features Reference

**Last updated:** 2026-07-03  
**Audience:** Engineers, product, partners, and operators  
**Sources of truth:**  
- Business rules: `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`  
- Architecture wiring: `docs/architecture.md`  
- Implementation status: `docs/IMPLEMENTATION_STATUS.md`  
- Session log: `understanding.txt`

---

## Table of contents

1. [Platform overview](#1-platform-overview)
2. [Actors and channels](#2-actors-and-channels)
3. [Non-negotiable business rules](#3-non-negotiable-business-rules)
4. [Architecture and tech stack](#4-architecture-and-tech-stack)
5. [Data model summary](#5-data-model-summary)
6. [Order lifecycle (FSM)](#6-order-lifecycle-fsm)
7. [Customer features (WhatsApp)](#7-customer-features-whatsapp)
8. [Rider features](#8-rider-features)
9. [Dispatch, logistics, and SLA](#9-dispatch-logistics-and-sla)
10. [Manager dashboard](#10-manager-dashboard)
11. [Onboarding and Meta connect](#11-onboarding-and-meta-connect)
12. [Menu, catalog, and POS](#12-menu-catalog-and-pos)
13. [Marketing studio](#13-marketing-studio)
14. [Predictions (AI + ML)](#14-predictions-ai--ml)
15. [Wallet, coupons, and loyalty](#15-wallet-coupons-and-loyalty)
16. [Complaints and tickets](#16-complaints-and-tickets)
17. [Partner / POS integration API](#17-partner--pos-integration-api)
18. [Background workers and schedules](#18-background-workers-and-schedules)
19. [Enterprise infrastructure](#19-enterprise-infrastructure)
20. [Error handling and graceful degradation](#20-error-handling-and-graceful-degradation)
21. [Security and privacy](#21-security-and-privacy)
22. [Testing strategy](#22-testing-strategy)
23. [Delivery phases](#23-delivery-phases)
24. [Configuration reference](#24-configuration-reference)
25. [Related documentation](#25-related-documentation)

---

## 1. Platform overview

**Restaurant WhatsApp Platform** is a multi-tenant, multilingual SaaS product. Restaurants run their entire delivery operation through WhatsApp:

- **Customers** order, modify, track, and pay (COD) entirely in WhatsApp chat — no app or website required.
- **Riders** (restaurant employees) receive assignments, share live location, and complete deliveries via WhatsApp and/or a dedicated rider mobile app.
- **Managers** onboard the restaurant, manage the menu, watch live operations, override anything, and run marketing — all from a React web dashboard.
- **Background jobs** run dispatch, SLA monitoring, ML retraining, marketing automation, and outbound message delivery.

The product also supports **partner-attributed restaurants** (e.g. Cratis POS) via a full REST + webhook integration, while **standalone** restaurants use the platform end-to-end without a POS.

---

## 2. Actors and channels

| Actor | Primary channel | Capabilities |
|-------|-----------------|--------------|
| **Customer** | WhatsApp | Order, modify, track, redeem coupons/wallet, complain, opt out of marketing |
| **Rider** | WhatsApp + Rider app | Accept assignments (no reject), live location, pickup/deliver, COD collection |
| **Manager** | React dashboard | Full ops control, manual takeover, overrides, marketing, settings |
| **POS partner** | X-API-Key REST + inbound webhooks | Kitchen status, order history, chat takeover, menu sync, rider roster |
| **Background workers** | Celery + in-process sweep | Dispatch, SLA, ML, marketing, outbox, wallet, loyalty, POS sync |

**Public (unauthenticated) pages:**

- `/track/:trackingToken` — customer order tracking
- `/rider-track/:riderToken` — rider live position for customers

---

## 3. Non-negotiable business rules

These rules are enforced in code and must not be violated by new features.

| Rule | Detail |
|------|--------|
| **Payment** | COD only |
| **Delivery radius** | Maximum 10 km from restaurant |
| **Delivery fees** | ≤3 km: free · 3–5 km: AED 5 · >5 km: AED 10 |
| **Customer SLA** | 40 minutes from confirmation (`sla_confirmed_at + 40 min`) |
| **Internal SLA target** | 30 minutes (dispatch batching constraint) |
| **Batch buffer** | +10 minutes per batched order in route calculations |
| **Riders** | Employees — no accept/reject step; manager can deactivate |
| **Order modification** | Allowed only before `ready`; restarts SLA after customer confirms new ETA |
| **Late delivery** | Auto-issued coupon when breach >40 min, **unless** weather delay was disclosed at order time |
| **Cancel after cooking** | Order enters resale queue; excluded from same phone, person, or address |
| **Dish numbers** | Mandatory; menu activation blocked if any dish lacks number or price |
| **Customer dish info** | Name + description (max 3 lines); **never** include price in descriptions |
| **Marketing opt-out** | STOP keyword honored; no further promotional sends |

---

## 4. Architecture and tech stack

### Pattern

**Modular monolith** — one deployable API, one worker fleet, one database. Bounded contexts under `src/app/<module>/` are import-isolated.

Within each module:

| File | Responsibility |
|------|----------------|
| `models.py` | SQLAlchemy 2 async ORM |
| `schemas.py` | Pydantic v2 I/O |
| `service.py` | Business logic, transactions, audit, outbox |
| `router.py` | HTTP only — calls services, never other modules' models |

External systems are reached through **ports** (`port.py` + `factory.py`) with fake and production adapters selected by `APP_*_PROVIDER` settings.

### Stack

| Layer | Technology |
|-------|------------|
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic |
| Workers | Celery + Redis broker, Celery Beat |
| Database | PostgreSQL 16 + PostGIS |
| Cache / geo hot data | Redis 7 (rider positions, dispatch locks, rate limits, geocode cache) |
| Realtime | WebSocket (dashboard) + polling transport |
| LLM | Claude / DeepSeek behind `llm/` port |
| ML | LightGBM demand models (per restaurant) |
| Maps | Google Maps Platform behind `geo/` port; haversine fallback |
| WhatsApp | Cloud API behind `whatsapp/` adapter; MockProvider + web simulator for dev |
| Dashboard | React + TypeScript + Vite, TanStack Query |
| Notifications | Expo push (rider app) |
| Dev infra | docker-compose: postgres+postgis (:5433), redis (:6380) |
| Tests | pytest + pytest-asyncio, Vitest (frontend) |

### High-level diagram

```
┌────────────────────────────────────────────────────────────────┐
│  React Dashboard SPA (manager) + Public tracking pages          │
└───────────────┬────────────────────────────────────────────────┘
                │ REST (+ WebSocket where applicable)
┌───────────────▼────────────────────────────────────────────────┐
│  FastAPI (src/app/main.py)                                      │
│  /webhooks/whatsapp   /api/v1/*   /metrics   /health            │
├─────────────────────────────────────────────────────────────────┤
│  Bounded contexts: identity · menu · catalog · pos ·           │
│  conversation · ordering · dispatch · sla · coupons · cod ·    │
│  wallet · tickets · predictions · marketing · partner ·          │
│  whatsapp · webhook · outbox · llm · geo · audit · okf         │
├─────────────────────────────────────────────────────────────────┤
│  Celery workers (apps/workers) — queues: dispatch, sla, ml,    │
│  marketing, outbox, maintenance (wallet, loyalty, pos, partner) │
├──────────────┬──────────────────┬───────────────────────────────┤
│ PostgreSQL   │ Redis            │ External: WhatsApp Cloud API  │
│ + PostGIS    │ cache/queue/geo  │ Google Maps · Claude/DeepSeek │
│              │                  │ Weather · OpenAI (images)       │
└──────────────┴──────────────────┴───────────────────────────────┘
```

### Backend modules (`src/app/`)

```
audit          — append-only audit log
catalog        — Meta Commerce catalog sync, browse, native view
cod            — cash-on-delivery collection ledger
config         — pydantic-settings (APP_ prefix)
conversation   — dialogue engine, renderer, compaction, complaint agent
coupons        — coupon issue/redeem (incl. SLA auto-issue)
db             — async engine, session, TimestampMixin
dispatch       — batching, OR-Tools routing, rider app, tracking
geo            — distance, geocoding, fee tiers
identity       — auth, riders, onboarding, Meta connect, settings
llm            — extraction, conversation agents, prompt SSOT, prompt KB
loyalty        — tier recomputation (scheduled)
marketing      — segments, templates, campaigns, automations, images
menu           — upload, diff, activate, dish CRUD
middleware     — security headers, response timing
notifications  — Expo push for rider app
obs            — Sentry, request ID
okf            — hybrid retrieval grounding for conversation
ordering       — orders, customers, addresses, FSM, matching, fees
outbox         — transactional WhatsApp send queue
partner        — POS REST API, webhooks, API keys, chat surface
pos            — Cratis (and fake) menu sync, background worker
predictions    — ML forecast, LLM adjustment, accuracy tracking
ratelimit      — Redis token bucket
sla            — SLA events, monitor, breach alerts
speech         — speech-related utilities
tickets        — complaint ticket management
wallet         — customer credit balance and ledger
weather        — weather delay disclosure flag
webhook        — inbound WhatsApp normalization and idempotency
whatsapp       — Cloud API + Mock provider, templates
```

---

## 5. Data model summary

All tenant tables carry `restaurant_id` and are indexed for multi-tenant queries.

### Identity

| Table | Purpose |
|-------|---------|
| `restaurants` | Tenant root: name, email (login), phone (WhatsApp routing), location, password, settings JSONB |
| `riders` | Employee riders: name, phone, status, performance JSONB, app pairing |
| `manager_users` | (Planned) separate manager accounts when multi-user is needed |

### Menu

| Table | Purpose |
|-------|---------|
| `menus` | Versioned menus: processing → pending_confirmation → active → superseded |
| `dishes` | dish_number, name, price, sale_price, category, description, availability, POS linkage, catalog retailer ID |

### Customers

| Table | Purpose |
|-------|---------|
| `customers` | Phone (per restaurant), name, order stats, usual_order_times, tags, marketing opt-out |
| `customer_addresses` | Geography point, room/building text, receiver name, confirmed flag |

### Conversation

| Table | Purpose |
|-------|---------|
| `conversations` | Dialogue state JSONB, manual_takeover, counterpart (customer/rider) |
| `messages` | Inbound/outbound history with WhatsApp message IDs and typed payloads |

### Ordering

| Table | Purpose |
|-------|---------|
| `orders` | Full order snapshot: status FSM, SLA timestamps, fees, weather flag, resale fields |
| `order_items` | Line items with price snapshot at order time |

### Dispatch and tracking

| Table | Purpose |
|-------|---------|
| `batches` | Multi-order routes with rider assignment |
| `batch_orders` | Sequence within a batch |
| `rider_locations` | Time series; hot copy in Redis GEO |
| `assignments` | Explainability: algorithm_score JSONB |

### SLA and coupons

| Table | Purpose |
|-------|---------|
| `sla_events` | yellow_30, red_35, breach_40 |
| `coupons` | Auto-issued on late delivery; single-use redemption |

### COD

| Table | Purpose |
|-------|---------|
| `cod_collections` | Per-order cash collection by rider |
| `rider_shift_reconciliations` | Expected vs collected totals |

### Predictions

| Table | Purpose |
|-------|---------|
| `prediction_runs` | Forecast vs actual per horizon |
| `model_registry` | Per-restaurant model versions and metrics |
| `manager_overrides` | Plain-English adjustments to forecasts |

### Marketing

| Table | Purpose |
|-------|---------|
| `wa_templates` | Meta template lifecycle (draft → pending_meta → approved/rejected) |
| `campaigns` | Broadcasts, scheduled sends, stats |
| `segments` | Audience DSL compiled from plain English |
| `marketing_automations` | Preset trigger/condition/action automations |
| `recurring_message_state` | Per-customer promo scheduling |

### Platform

| Table | Purpose |
|-------|---------|
| `audit_log` | Immutable state-change record |
| `outbox_messages` | Pending/sent/failed/dead outbound WhatsApp messages |
| `webhook_events` | Inbound idempotency by provider event ID |
| `partner_api_keys` | Hashed API keys with optional partner slug |
| `tickets` | Complaint tickets |
| `wallet_entries` | Customer credit ledger |

---

## 6. Order lifecycle (FSM)

Explicit finite state machine — illegal transitions raise `IllegalTransitionError` and are never silently applied.

```
draft
  → pending_confirmation → confirmed → preparing → ready
    → assigned → picked_up → arriving → delivered

Terminal / branch states:
  cancelled        (from most pre-delivered states; actor-guarded)
  undeliverable    (customer unreachable / out of radius)
  on_resale        (cancelled after cooking)
    → resold | written_off
```

**Key transition rules:**

- Customer WhatsApp cancel: allowed through `preparing` only.
- Restaurant/POS/dashboard cancel: allowed through `arriving`.
- Post-cooking customer cancel → `on_resale` (not plain `cancelled`).
- Modification restarts SLA clock after customer confirms.
- Every transition calls `record_audit` in the same transaction.

---

## 7. Customer features (WhatsApp)

### Conversation engine (`conversation/engine.py`)

The engine is a large phase-based dispatcher combining:

- **Deterministic guards** (fast, reliable) for common intents
- **LLM-assisted** intent classification and natural replies (DeepSeek/Claude behind port)
- **Context engineering** (prompt SSOT, compaction, OKF grounding, prompt KB)

#### Dialogue phases

| Phase | Behavior |
|-------|----------|
| `ordering` | Collect items, answer questions, show menu |
| `address_capture` | Request pin + text address, validate radius |
| `awaiting_confirmation` | Show summary, accept modifications, redeem coupons/wallet |
| `post_order` | Track, modify (pre-ready), complain |
| `modify_items` / `modify_confirm` | Post-confirm line edits with diff summary |

#### Ordering capabilities

- Greeting → digital menu (formatted by category, never raw PDF)
- Fuzzy dish matching (`pg_trgm`) with confirm flow for ambiguous matches
- Dish-number fallback when name match fails
- LLM arbitration for hopeless matches → manager alert
- "What is X?" → description max 3 lines, no price
- Special requests → verbatim `additional_details`
- Multi-item orders, combo handling, kitchen modifiers
- Set-quantity phrasing ("make it 5", "only 2") replaces qty, does not add
- Keep-only ("only mandi") prunes other cart lines
- Clear cart vs "clear soup" disambiguation
- Checkout loop fix ("that's all" → proceed, not re-add)
- Complaint questions don't accidentally add items
- Off-topic guard (medical, homework, etc.) — warm decline, no menu dump
- Category availability queries ("any drinks?") — capped list, optional catalog cards
- Coupon claim and wallet credit at checkout
- Weather delay disclosure suppresses late-delivery coupon
- Resale offer acceptance for cancelled-after-cooking orders
- STOP / marketing opt-out
- Manual takeover pauses bot replies

#### Catalog ordering modes

| Mode | Description |
|------|-------------|
| Text menu | Rendered dish list (capped at 40 items) |
| Product list | Meta Commerce cards (30-card cap per message) |
| Browse by category | Paginated category picker (flag: `catalog_browse_by_category`) |
| Native catalog view | Single "View full menu" button opening WhatsApp storefront (flag: `catalog_native_view`) |
| Keyword path | Simple flows without LLM (e.g. "hi" → catalogue) |
| Catalogue cart edit | Remove / set-qty in catalogue mode |

#### Address flow

1. Request WhatsApp location pin
2. Validate ≤10 km (else "Sorry, not deliverable")
3. Request `room/apartment, building` (comma-separated)
4. Echo parsed address for confirmation
5. Store and reuse on future orders
6. Returning customers offered saved address

#### Location intents

- Customer shares pin during ordering with cart → proceed to fee calculation
- Pin without cart → acknowledgment, stay in ordering
- "Share your location" (restaurant) → send restaurant pin (not ask customer for theirs)

---

## 8. Rider features

### WhatsApp rider flow

1. Shift start → share live location (Redis GEO + `rider_locations`)
2. Orders ready → notification with order numbers (batch-aware)
3. **"Orders Picked"** → first stop pin + Google Maps link + customer contact
4. Geofence at ~100 m → delivery buttons
5. **"Collect money & delivered"** for COD → writes `cod_collections`
6. Stale location (>3 min) → rider nudge + manager alert

Riders see customer contact; customers see rider name + "Message rider" (not raw rider number).

### Rider mobile app (`/api/v1/rider-app/*`)

| Endpoint area | Features |
|---------------|----------|
| Pairing | `/pair` — link rider device |
| Duty | `/duty` — on/off shift |
| Push | `/push-token` — Expo notifications |
| Orders | `/orders` — active run; `/orders/pickup`; `/orders/{id}/delivered` |
| Location | `/location` — live GPS updates |
| Info | `/me`, `/info` |

Managers send app invites from the Riders screen (`POST /riders/{id}/app-invite`).

---

## 9. Dispatch, logistics, and SLA

### Dispatch engine (`dispatch/service.py`)

Triggers: order → `ready`, rider freed, priority order, modification.

| Step | Detail |
|------|--------|
| Eligible set | Ready unassigned orders + available riders |
| Batching | Cluster by destination proximity (PostGIS); valid iff every order meets internal 30-min target including route time + buffers |
| Priority | Protected from batching that threatens their SLA |
| Rider scoring | Distance, workload, area performance, on-time % — persisted to `assignments.algorithm_score` |
| Routing | Nearest-neighbor + 2-opt over Google Routes; priority stops first |
| Re-optimization | Rider freed early / detour / new priority → re-run, update ETAs, notify customers |
| Resale | Cancelled-after-cooking orders offered to suitable conversations |

**Operational safeguards:**

- Redis lock per restaurant during dispatch
- Batch preview cache (tenant-scoped Redis, 30s TTL)
- In-process dispatch sweep on web-only deploys (Render, no Celery worker)
- Orphaned batch cleanup (assignments deleted before empty batches)
- Idempotent SLA breach outbox keys (minute-bucketed)

### SLA monitor (`sla/monitor.py`)

Heartbeat every **30 seconds**:

| Threshold | Action |
|-----------|--------|
| 30 min | Yellow dashboard alert |
| 35 min | Red alert + manager push |
| 40 min breach | Auto coupon + apology (unless `weather_delay_disclosed`) |

### COD

- Rider confirms collection at delivery
- Shift reconciliation: expected vs collected, variance tracking

### Tracking

- Live ETA from rider position via Routes API + buffer
- Public tracking token for customers
- Dashboard live ops map (riders, orders, batches, SLA board)

---

## 10. Manager dashboard

**Stack:** React + TypeScript + Vite, TanStack Query, CSS modules.

### Navigation (`NavSidebar`)

| Route | Screen | Features |
|-------|--------|----------|
| `/` | Live Ops | KPIs, dispatch map, SLA board, real-time ops |
| `/orders` | Orders | Filtered list, batch labels, order detail drawer |
| `/customers` | Customers | Search, server pagination |
| `/customers/:id` | Customer Profile | History, wallet, coupons |
| `/new-order` | New Order | Manual order creation |
| `/menu` | Menu Manager | Upload, edit, activate, POS sync, catalog panel |
| `/riders` | Riders | Roster, duty, deactivate, COD, app invite |
| `/conversations` | Chats | Thread viewer, manual reply, takeover |
| `/tickets` | Complaints | Open tickets, resolution |
| `/coupons` | Coupons | Issued/redeemed list |
| `/marketing` | Marketing Studio | Campaigns, segments, templates, automations, broadcast |
| `/analytics` | Reports | KPIs, predictions panel |
| `/settings` | Settings | General, API keys, integrations |
| `/onboarding` | Onboarding | Meta WhatsApp connect (single gate) |
| `/login` | Login | Email + password |
| `/track/:token` | Public tracking | Customer-facing (no auth) |
| `/rider-track/:token` | Rider tracking | Customer-facing (no auth) |

### Order detail drawer

- Progressive loading with `?include=` (timeline, chat, route)
- SLA countdown, dispatch explainability section
- Kitchen advance, cancel, reassign rider
- Conversation mirror from order context

### Performance

- TanStack Query with hover prefetch on sidebar
- Onboarding gate session cache (no per-nav block)
- Batch preview server-side cache
- Target: ≤400 ms dashboard navigation (Render production)

---

## 11. Onboarding and Meta connect

**Single gate:** onboarding is complete when WhatsApp (Meta) is connected. Menu, location, and catalog are set up inside the dashboard afterward.

### Connect flow

1. Manager logs in with **email** (phone auto-set from Meta display number for webhook routing)
2. **"Connect with Facebook"** — Meta Embedded Signup popup
3. Backend automatically:
   - Exchanges OAuth code for access token
   - Subscribes app to WABA with `override_callback_uri`
   - Registers phone on Cloud API (2FA pin persisted as `wa_2fa_pin`)
   - Attaches owned catalog to WABA (list + connect; human admin required to create catalog on Meta)
   - Stores per-restaurant creds: `wa_phone_number_id`, `wa_business_account_id`, `wa_access_token`, `catalog_id`
   - Provisions POS partner integration when `?partner=<slug>` present

### Standalone vs partner

| Mode | URL | Behavior |
|------|-----|----------|
| Standalone | `/onboarding` (no query) | WhatsApp connect only; no POS key/webhook |
| Partner | `/onboarding?partner=cratis` | Connect + mint API key + wire partner webhook |

### Settings

- **Disconnect WhatsApp** (General tab) — clears Meta creds + catalog_id, sets `onboarding_complete=false`
- Manual Meta config fallback (collapsible form) when Embedded Signup unavailable

### Per-restaurant send path

`outbox/worker.py` resolves creds via `identity/meta_config.resolve_send_creds(restaurant)` — restaurant settings first, env fallback (transitional).

---

## 12. Menu, catalog, and POS

### AI menu digitization

1. Upload PDF/JPEG/PNG (multipart)
2. Claude vision extracts: dish_number, name, price, category, description
3. Manager reviews in dashboard (edit, add, remove)
4. Activation blocked until every dish has number + price
5. Re-upload: diff by `(dish_number, name)` → price-change report → confirm → new version

### Manual menu

- `POST /menus/blank` — create empty active menu
- "+ Add dish" always available (no upload required first)

### POS integration (Cratis)

| Feature | Detail |
|---------|--------|
| Sync | `POST /pos/sync` (202 background) or inline for small runs |
| Mapping | Product type 1 only; upsert by `pos_product_id` |
| Images | Auto-generated PNG for new dishes |
| Meta | Auto-publish to Commerce Manager + OKF refresh |
| Preserve | Local `image_url`, `sale_price_aed`, `whatsapp_enabled` on re-sync |
| Read-only UI | POS-owned dishes: no edit/delete in dashboard (toggle availability/WhatsApp OK) |
| Background | `pos.sync_menu` Celery task with status breadcrumb in settings |

### Meta Commerce catalog

- Push/pull dishes to catalog
- `catalog_products` mirror table
- Collections via `product_sets` API
- WhatsApp status badges: "WhatsApp off" / "In review" / "On WhatsApp"
- Toggle OFF → unpublish from Meta; toggle ON → republish (mirror refreshed on Pull from Meta)

### Dish variants and pricing

- Item variants (size, etc.)
- `sale_price_aed` when 0 < sale < base
- Single money path: `payments.recompute_order_total` + coupon application

---

## 13. Marketing studio

**Status:** Phases 1–5 complete (Campaigns, Segments, Templates, Automations, Scheduled broadcast + AI image).

### Campaigns tab

- Sortable campaign table (date, template, audience, type, status, sent/delivered/converted)
- Summary KPI strip
- Row click → stats drawer with suppression breakdown
- Scheduled badge, cancel, reschedule
- Poll every 60s when tab mounted

### Segments tab

- Plain-English audience description
- `POST /segments/compile` → validated DSL
- `POST /segments/preview` → audience count before save
- Save, list, delete segments

### Templates tab

- Create, edit, submit to Meta
- AI fix on rejection (`POST /templates/{id}/fix`)
- Approval timeline UI (stepper + resubmit)
- Auto-poll every 30s when any template `pending_meta`
- Ephemeral templates (Today's Special — auto-deleted end of day)
- Fallback template picker
- AI image generation (`POST /templates/image/generate`) with daily rate limit

### Today's Special

- Manager uploads image + offer text
- Claude generates Meta-compliant template
- Compliance lint pass
- Send to segment(s) or all customers
- Configurable send window (Dubai time)

### Broadcast

- Send now or schedule (`scheduled_at`)
- Audience: RFM segment **or** saved custom segment (mutually exclusive)
- Optional coupon value (AED)
- `DELETE /campaigns/{id}` and `PATCH /campaigns/{id}/schedule`

### Automations tab

Four preset automations (configurable template, segment, lead time):

- Post-order promo scheduling (day +3, then weekly same weekday at usual order time −15 min)
- Trigger/condition/action DSL
- Celery: automation tick (*/15 min), recurring promo tick (hourly)

### Recurring promos (background)

- `usual_order_times` updated with recency weighting
- Frequency caps + opt-out honored
- `recurring_message_state` per customer

---

## 14. Predictions (AI + ML)

### ML layer

- LightGBM per restaurant
- Features: hour, day-of-week, holiday/Ramadan, weather, trailing demand, disabled dishes, campaign activity
- Horizons: `next_1h`, breakfast, lunch, dinner, midnight
- Weekly retrain (default Monday 04:00 Dubai, configurable)
- Nightly forecast all tenants (02:00 Dubai)

### LLM layer

- Adjusts ML output with context ML cannot see
- Manager plain-English overrides ("big corporate order Thursday", "road closed")
- Reasoning shown on dashboard

### Accuracy

- Actuals backfilled per `prediction_runs`
- MAPE tracked; target ~80%

---

## 15. Wallet, coupons, and loyalty

### Wallet (`/api/v1/wallet/{customer_id}`)

- Balance, credit, debit, entry history
- Applied at checkout: `min(wallet_balance, order_total)`
- Scheduled: credit expiry (03:00 Dubai), reconciliation (03:30 Dubai)

### Coupons

- Auto-issued on SLA breach (unless weather disclosed)
- Single-use redemption at next order
- Manager view in Coupons screen
- Customer profile shows coupon history

### Loyalty

- Tier recomputation scheduled 04:00 Dubai (after wallet reconcile)
- Module: `src/app/loyalty/`

---

## 16. Complaints and tickets

- Conversation engine detects complaints (`_is_complaint`)
- Complaint agent summarizes with evidence + category
- Manager alert via outbox
- Tickets screen: list, detail, resolve (`POST /tickets/{id}/resolve`)
- Open ticket count badge on sidebar

---

## 17. Partner / POS integration API

Authenticated with `X-API-Key` header. Each restaurant has its own API key (minted on partner-attributed Meta connect).

### Outbound webhooks (platform → POS)

HMAC-signed payloads for:

- `order.created`
- `order.rider_assigned`
- `order.picked_up`
- `order.delivered`
- `order.cancelled`

### REST endpoints (`/api/v1/partner/`)

| Endpoint | Purpose |
|----------|---------|
| `GET /customers` | Customer list |
| `GET /orders` | Order list (`status=all` for full history) |
| `GET /orders/{id}` | Order detail |
| `POST /orders/{id}/status` | Kitchen/delivery status updates |
| `POST /orders/{id}/ack` | Acknowledge order |
| `GET /orders/{id}/delivery` | Delivery state + rider GPS |
| `GET /riders` | Full rider roster (not just live) |
| `GET /riders/{id}/location` | Rider position |
| `PUT /menu/items` | Bulk menu upsert |
| `PATCH /menu/items/{pos_id}` | Single item update |
| `POST /events/menu-changed` | Notify menu change |
| `GET /menu/sync-status` | Sync status |
| `GET /store` | Store config |
| `GET /conversations` | Chat list |
| `GET /conversations/{id}/messages` | Thread |
| `POST /conversations/{id}/messages` | Manual reply (+ optional takeover) |
| `POST /conversations/{id}/takeover` | Toggle bot pause |

### Manager integration config (`/api/v1/integration/`)

- `GET/PATCH /config` — webhook URL, enabled flag
- `GET /health` — connectivity check
- `POST /webhooks/test` — test webhook delivery

### API key management (`/api/v1/keys/`)

- Create, list, revoke partner API keys

### Multi-partner registry

- `APP_PARTNERS` JSON map: `{slug: {name, webhook_url, webhook_secret}}`
- `APP_DEFAULT_PARTNER` names legacy top-level webhook config
- `?partner=cratis` on onboarding tags restaurant and wires correct webhook

---

## 18. Background workers and schedules

### Celery queues

| Queue | Tasks |
|-------|-------|
| `dispatch` | `dispatch.sweep_ready` |
| `sla_monitor` | `sla.monitor_tick` |
| `ml` | `ml.forecast_all_tenants`, `ml.retrain_all_tenants` |
| `marketing` | campaigns, automations, template poll, ephemeral cleanup |
| `outbox` | message delivery, failed sweep |
| `maintenance` | wallet, loyalty, pos sync, partner webhooks |

### Celery Beat schedule

| Task | Schedule |
|------|----------|
| `sla.monitor_tick` | Every 30s |
| `dispatch.sweep_ready` | Configurable (`APP_DISPATCH_SWEEP_SECONDS`) |
| `ml.forecast_all_tenants` | 02:00 Dubai daily |
| `ml.retrain_all_tenants` | Weekly (default Mon 04:00 Dubai) |
| `marketing.send_scheduled_campaigns` | Every 5 min |
| `marketing.automation_tick` | Every 15 min |
| `marketing.recurring_promo_tick` | Hourly |
| `marketing.poll_template_statuses` | Every N min (configurable) |
| `marketing.cleanup_ephemeral_templates` | 23:30 Dubai (configurable) |
| `outbox.sweep_failed` | Every 5 min |
| `conversation.abandoned_cart_sweep` | Every 5 min |
| `wallet.expire_credits_all_tenants` | 03:00 Dubai |
| `wallet.reconcile_all_tenants` | 03:30 Dubai |
| `loyalty.recompute_all_tenants` | 04:00 Dubai |

### In-process fallback

When `APP_DISPATCH_INPROCESS_SWEEP=true` (Render web-only), FastAPI lifespan runs dispatch sweep in asyncio loop.

---

## 19. Enterprise infrastructure

| Concern | Implementation |
|---------|----------------|
| **Audit** | `record_audit()` on every state transition, same transaction |
| **Outbox** | Transactional enqueue; worker delivers with retry (max 5) + dead-letter |
| **Idempotent webhooks** | `webhook_events` keyed by provider message ID |
| **Explicit FSMs** | Order + delivery; illegal transitions raise |
| **Manual override** | Manager takeover, force state, reassign rider |
| **Rate limiting** | Redis token bucket (auth, webhook, API) |
| **Observability** | Sentry, Prometheus `/metrics`, structured logging, request ID |
| **Security headers** | CSP (incl. Facebook SDK for Embedded Signup), HSTS, X-Frame-Options |
| **Multi-tenancy** | `restaurant_id` on all tenant queries via JWT dependency |
| **Context engineering** | Prompt SSOT (`conversation_prompts.py`), compaction, OKF cap, prompt KB, goldmine archive (`context.txt`) |
| **Media persistence** | Marketing images in Postgres (`marketing_media`) for ephemeral-disk hosts |
| **Simulator** | `apps/simulator/` — mock WhatsApp UI at `/simulator/` when `APP_WHATSAPP_PROVIDER=mock` |

---

## 20. Error handling and graceful degradation

| Failure | Behavior |
|---------|----------|
| LLM API down | Dish-number-only ordering, canned dialogue, manager alert |
| Maps API down | Haversine + static speed (25 km/h) + widened buffers; flag ETAs as estimates |
| WhatsApp send fails | Outbox retry → dead-letter → manager alert |
| Webhook duplicate | Idempotency table drops replay |
| Rider offline mid-delivery | Stale-location alert, manager reassignment |
| Template rejected by Meta | AI revision loop + fallback template |
| Customer unreachable | Rider flow → manager decides → `undeliverable` |
| Kitchen overload | Prediction warning; manager can pause new orders |
| DB/Redis outage | Health 503 with retry-after; Meta queues inbound |

---

## 21. Security and privacy

- **Tenant isolation:** every query scoped by `restaurant_id`
- **Auth:** JWT (short-lived) + argon2 password hashing
- **Webhook verification:** Meta `X-Hub-Signature-256`
- **PII:** customer phone/address handling; rider personal numbers not exposed to customers
- **API keys:** hashed at rest; full key shown once on creation
- **Partner webhooks:** HMAC signature verification
- **Audit immutability:** append-only, no UPDATE/DELETE
- **Rate limits:** per phone + per tenant
- **CORS / CSP:** configured for dashboard + Facebook Embedded Signup domains

---

## 22. Testing strategy

| Layer | Coverage |
|-------|----------|
| Unit | FSM property tests, fee calculator, address parser, fuzzy matcher corpus |
| Integration | Webhook → conversation → order pipeline (MockProvider) |
| Dispatch simulation | Seeded scenarios asserting SLA invariants |
| Contract | WhatsApp adapter conformance (Mock + optional Cloud) |
| E2E | Simulator-driven full conversations; dashboard latency spec |
| Frontend | Vitest component and screen tests |
| Load | Locust profile (`load/locustfile.py`) |
| Eval harness | Conversation evals with xfail graduation tracking |
| CI | `.github/workflows/ci.yml` — pytest + ruff |

**Run tests:**

```bash
.venv/bin/pytest                          # full suite (requires Docker DB)
.venv/bin/ruff check src apps tests       # lint
cd frontend && npm test                   # frontend vitest
```

---

## 23. Delivery phases

| Phase | Scope | Status |
|-------|-------|--------|
| 0 | Scaffold, docker-compose, audit, outbox primitives | ✅ Complete |
| 1 | Identity, menu, AI extraction, rider registration | ✅ Complete |
| 2 | WhatsApp adapter, webhook, conversation engine, simulator | ✅ Complete |
| 3 | Ordering, matching, address, FSM, modification, resale | ✅ Complete |
| 4 | Dispatch, batching, SLA, COD, tracking, rider flow | ✅ Complete |
| 5 | React dashboard (all operational screens) | ✅ Complete |
| 6 | Predictions + marketing automation | ✅ Complete |
| 7 | Hardening (rate limits, metrics, security, load) | ✅ Ongoing |
| — | POS integration (Cratis) | ✅ Phase 1 |
| — | Marketing Studio Phases 1–5 | ✅ Complete |
| — | Meta Embedded Signup onboarding | ✅ Complete |
| — | Partner chat + roster + multi-partner registry | ✅ Complete |
| — | Context engineering E-01..E-24 | ✅ Complete |

---

## 24. Configuration reference

Key environment variables (`APP_` prefix, see `.env.example`):

| Variable | Purpose |
|----------|---------|
| `APP_DATABASE_URL` | PostgreSQL async connection |
| `APP_REDIS_URL` | Redis broker + cache |
| `APP_JWT_SECRET` | JWT signing |
| `APP_LLM_PROVIDER` | `fake` (tests) or `claude` / `deepseek` |
| `APP_WHATSAPP_PROVIDER` | `mock` or `cloud` |
| `APP_GEO_PROVIDER` | `fake` or `google_maps` |
| `APP_GOOGLE_MAPS_API_KEY` | Road distance + routing |
| `APP_ANTHROPIC_API_KEY` | Claude extraction + marketing |
| `APP_PUBLIC_BASE_URL` | Webhook callback override for new WABAs |
| `APP_WA_ES_CONFIG_ID` | Meta Embedded Signup configuration ID |
| `APP_POS_PROVIDER` | `fake` or `cratis` |
| `APP_PARTNER_WEBHOOK_URL` | Default partner outbound webhook |
| `APP_PARTNER_WEBHOOK_SECRET` | HMAC secret for partner webhooks |
| `APP_PARTNERS` | JSON multi-partner registry |
| `APP_OUTBOX_SYNC_DELIVERY` | In-process outbox delivery (Render free tier) |
| `APP_DISPATCH_INPROCESS_SWEEP` | In-process dispatch sweep |
| `APP_SENTRY_DSN` | Error tracking |

---

## 25. Related documentation

| Document | Contents |
|----------|----------|
| `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` | Approved business spec |
| `docs/architecture.md` | Module wiring and data flows |
| `docs/IMPLEMENTATION_STATUS.md` | Phase completion and verified rules |
| `docs/GAP_LIST.md` | Known gaps |
| `docs/deployment.md` | Deploy guide |
| `docs/observability.md` | Metrics and monitoring |
| `docs/prompt-inventory.md` | All LLM prompts map |
| `docs/enhancement.md` | Context engineering backlog |
| `docs/superpowers/plans/2026-07-02-marketing-studio-full.md` | Marketing studio plan |
| `graphify-out/GRAPH_REPORT.md` | Knowledge graph audit |
| `understanding.txt` | Chronological implementation log |

---

*This document is a living reference. When adding features, update the relevant section here and log the change in `understanding.txt`.*