# Implementation Status — Restaurant WhatsApp Platform
**Date:** 2026-06-08 | **Backend tests:** 463 passing | **Frontend tests:** 88 passing | **Lint:** clean

---

## Overall Architecture (what exists)

```
src/app/
  identity/     Restaurant signup/login, Rider CRUD, JWT (iss+aud), argon2 hashing, rate limit
  menu/         AI menu extraction (Claude/Fake), diff, activate, FileBlobStore, re-extract
  llm/          Port + FakeExtractor + ClaudeExtractor + ordering ports (Describer, IntentClassifier)
  conversation/ Engine (1000-line FSM dispatcher), service, models, STOP wiring
  ordering/     Order/Customer/Address models, FSM, fees, fuzzy dish matching, weather flag
  dispatch/     Batching, scoring, delivery FSM, rider_flow, rider_location, tracking (live ETA)
  sla/          SlaEvent (idempotent), monitor Celery task (yellow_30/red_35/breach_40), coupon trigger
  geo/          Port + FakeGeoProvider + GoogleMapsProvider + haversine + fee tiers
  whatsapp/     Port + MockProvider + CloudAPIProvider (HMAC verify)
  webhook/      Normalizer, router (GET verify + signed POST), replay guard, rate limit dep
  outbox/       Enqueue service, worker (max_retries=5, exponential backoff), claim-race fix
  marketing/    Segments (DSL+LLM), templates (port+mock+meta), throttle, window, optout, service, router
  predictions/  Features (numpy), RollingAverage model, accuracy (MAPE), adjust (LLM override), service, router
  cod/          COD collection model + service + router
  coupons/      Coupon model + service (SLA breach auto-issue)
  weather/      Port + FakeWeather (flag only, no API)
  ratelimit/    Redis token bucket (auth 5/min, webhook 120/min)
  middleware/   SecurityHeadersMiddleware (CSP, HSTS, X-Frame)
  obs/          Request-ID middleware, Prometheus metrics (/metrics), Sentry init hook
  audit/        Append-only audit log (all state changes)

apps/workers/
  celery_app.py  Queues: dispatch, sla_monitor, ml, marketing, outbox
                 Beats: sla-monitor-tick (60s), nightly-forecast (02:00 UAE), send-campaigns (09:00 UAE)

apps/simulator/
  router.py      WhatsApp simulator (mock delivery, manual inject)
  static/index.html  Single-page UI for testing conversations

frontend/src/
  screens/       Login, LiveOps, Orders, MenuManager, Riders, Conversations, Analytics, Settings
  components/    AppShell, NavSidebar, CountdownTimer, KPITile, SLAOrderCard, DiffPanel, etc.
  lib/           apiClient, auth, ordersApi, menuApi, ridersApi, conversationsApi,
                 predictionsApi, marketingApi, sla, usePoll, pollingTransport

load/locustfile.py    Locust load profile (order + status flows)
ops/secrets_audit.py  CI/cron gate: checks secret strength in prod/staging
.github/workflows/ci.yml  CI: pytest (deprecation-strict) + ruff
```

---

## Phase Status

| Phase | Scope | Status | Tests |
|-------|-------|--------|-------|
| 0-1 Foundation | Scaffold, identity, menu, LLM | ✅ Complete | 60+ |
| 2 WhatsApp Core | Webhook, outbox, conversation, simulator | ✅ Complete | 40+ |
| 3 Ordering | Customer/order flow, FSM, matching, fees | ✅ Complete | 50+ |
| 4 Logistics | Dispatch, SLA, COD, rider flow, tracking | ✅ Complete | 50+ |
| 5 Dashboard | React frontend, all 8 operational screens | ✅ Complete | 88 (frontend) |
| 6 Predictions + Marketing | ML demand, campaign automation | ✅ Complete | 60+ |
| 7 Hardening | Rate limit, JWT claims, secrets, CI, metrics | ✅ Complete | 30+ |

---

## Key Business Rules — Verified Implemented

| Rule | File | Status |
|------|------|--------|
| COD only | cod/service.py | ✅ |
| Max 10 km radius | geo/fees.py | ✅ |
| Fee tiers (≤3km free / 3-5 AED5 / >5 AED10) | geo/fees.py | ✅ |
| SLA 40-min customer / 30-min internal / 10-min batch buffer | sla/monitor.py, dispatch/batching.py | ✅ |
| Order modify only before `ready`, restarts SLA | ordering/service.py | ✅ |
| Riders employees — no accept/reject | dispatch/service.py | ✅ |
| Late delivery → auto coupon (except weather-disclosed) | sla/monitor.py | ✅ |
| Dish numbers mandatory, activation blocked if missing | menu/service.py | ✅ |
| Customer description max 3 lines, no price | conversation/engine.py | ✅ |
| Cancelled-after-cooking → auto-resell, excluded same phone/address | ordering/service.py | ✅ |
| STOP keyword → opt-out, no further marketing | conversation/engine.py, marketing/optout.py | ✅ |
| "Where is my order?" → live rider ETA | dispatch/tracking.py | ✅ |
| Rider 100m geofence → "Delivered and Next Order Location" buttons | dispatch/rider_flow.py | ✅ |
| Priority orders → single-rider batch | dispatch/batching.py | ✅ |

---

## Known Gaps (from GAP_LIST.md — factual, sourced from spec)

### HIGH: Functionality missing from spec

**1. Dispatch batching — inter-stop travel time**
- Spec: "for every order: now − sla_confirmed_at + route_time_to_that_stop + 10-min buffer ≤ 30 min"
- Current: proximity clustering + fixed 10-min buffer per stop. No inter-stop geo travel summed.
- `total_est_min` field on Batch model never computed/set.
- File: `dispatch/batching.py`, `dispatch/service.py`

**2. Marketing — Meta image header upload**
- Spec: resumable Meta upload for image headers in templates
- Current: `template_meta.py` has comments but no actual httpx POST to Meta /uploads endpoint
- File: `marketing/template_meta.py`

**3. Marketing — ephemeral template cleanup**
- Spec: daily ephemeral templates auto-deleted at 23:30 UAE
- Current: `deleted_at` field exists in model but no Celery beat task to clean them up
- File: `apps/workers/celery_app.py`, `marketing/worker.py`

**4. Marketing — Meta template approval polling**
- Spec: periodic poll of pending_meta templates for status changes
- Current: `get_status()` port method exists but no beat task polls it
- File: `apps/workers/celery_app.py`, `marketing/service.py`

### MEDIUM: Minor surface/UX deviations

**5. Customer address echo text**
- Current: `"Address noted: room/apartment {room}, building {building}."`
- Spec example exact: `"room/apartment number 111 building 1-2"` (includes word "number")
- File: `conversation/engine.py` ~line 396

**6. Weekly ML retrain schedule**
- Spec: configurable weekly retrain (default Mon 04:00 UAE)
- Current: only nightly forecast at 02:00, no retrain/model-registry update
- File: `apps/workers/celery_app.py`, `predictions/worker.py`

### LOW: Nice-to-have

**7. Batching `total_est_min` not persisted** (related to gap 1)

**8. Weather provider** — FakeWeather only. No real weather API integration (spec mentions it as optional integration, flag-based approach is acceptable).

---

## Uncommitted Work (from last session's agents)

The following files have been modified by agents but not committed. They pass all 463 tests and lint:

**Backend changes (agents):**
- `src/app/main.py` — Sentry init hook wiring
- `src/app/config.py` — `sentry_dsn` field added
- `src/app/outbox/worker.py` — sweep_failed_outbox task
- `apps/workers/celery_app.py` — outbox sweeper beat
- `src/app/obs/sentry.py` — NEW: Sentry init hook
- `src/app/dispatch/batching.py` — possible agent changes
- `src/app/dispatch/rider_flow.py` — possible agent changes
- `src/app/dispatch/service.py` — possible agent changes
- Various other src changes (see `git status`)

**New test files (not committed):**
- `tests/dispatch/test_dispatch_router.py`
- `tests/marketing/test_worker.py`
- `tests/outbox/test_sweeper.py`
- `tests/predictions/test_worker.py`
- `tests/test_lifespan.py`

**Frontend (not committed):**
- `frontend/src/lib/predictionsApi.ts` — NEW
- `frontend/src/lib/marketingApi.ts` — NEW
- `frontend/src/screens/AnalyticsScreen.tsx` — updated from stub
- `frontend/src/screens/AnalyticsScreen.test.tsx` — NEW

**Action required:** Review each change, then `git add` + `git commit` in logical groups.

---

## Test Coverage Summary

| Module | Test File(s) | Count (approx) |
|--------|-------------|----------------|
| identity | test_auth, test_hashing, test_jwt_claims, test_login_rate_limit, test_riders, test_signup_login | 30 |
| menu | test_activate, test_diff, test_edit, test_reextract, test_storage, test_upload | 25 |
| ordering | test_cancellation, test_fees, test_fsm, test_matching, test_modification, test_service, test_status_reply, test_weather_stub | 35 |
| dispatch | test_batch, test_delivery_fsm, test_dispatch_engine, test_scoring, test_tracking, test_dispatch_router | 30 |
| conversation | test_engine, test_engine_ordering, test_engine_pipeline, test_engine_rider, test_rider_flow, test_service | 40 |
| marketing | test_compliance, test_models, test_naming, test_optout, test_router, test_segments, test_service, test_template_provider, test_throttle, test_window | 50 |
| predictions | test_accuracy, test_adjust, test_features, test_models, test_port, test_rolling, test_router, test_service | 35 |
| outbox | test_backoff, test_claim_race, test_outbox_service, test_outbox_worker | 15 |
| sla | test_sla_monitor | 8 |
| geo | test_fees, test_geo_port, test_haversine | 10 |
| webhook | test_processed_at_type, test_replay, test_webhook_router | 10 |
| whatsapp | test_cloud_provider, test_mock_provider, test_normalizer | 10 |
| simulator | test_simulator, test_simulator_ordering | 8 |
| other | test_audit, test_config, test_health, test_metrics | 6 |
| **Frontend** | 27 test files | 88 |

---

## Migration Chain (alembic)

```
Single head: 464f76bc2e70 (menu_files)
Chain: audit_log → identity → menus+dishes → webhook_events → conversations+messages → 
       outbox → riders+delivery_settings → orders+items → pg_trgm+name_normalized → 
       sla+coupons+cod → dispatch_models → rider_locations+geo → updated_at_triggers →
       sla_event_unique → webhook_processed_at_timestamptz → menu_files
```

---

## How to Run

```bash
# Backend
.venv/bin/pytest                    # 463 tests
.venv/bin/ruff check src apps tests # lint clean

# Frontend  
cd frontend && npm test -- --run    # 88 tests

# Server
.venv/bin/uvicorn app.main:app --reload --port 8000

# Celery worker
.venv/bin/celery -A apps.workers.celery_app:celery_app worker --loglevel=info

# Simulator UI
http://localhost:8000/simulator/

# Metrics
http://localhost:8000/metrics
```
