# Restaurant WhatsApp Platform

Multi-tenant SaaS platform that lets restaurants run their entire delivery operation through WhatsApp: customer ordering, AI menu digitization, intelligent dish matching, own-fleet rider dispatch with live tracking, smart batching under a hard 40-minute SLA, ML demand predictions, and marketing automation — plus a React manager dashboard.

- **Customer** orders via a WhatsApp chat; never sees an app or website.
- **Rider** is a restaurant employee; receives assignments and shares live location over WhatsApp.
- **Manager** onboards the restaurant, confirms the AI-parsed menu, and watches the dashboard.
- **Background jobs** drive dispatch, the SLA monitor, schedulers, ML retraining, and template lifecycle.

Architecture is a **modular monolith** (FastAPI, async SQLAlchemy 2, Celery) with strict bounded contexts, external integrations behind ports, a transactional outbox for outbound WhatsApp, idempotent webhooks, an append-only audit log, and `restaurant_id` tenant scoping on every tenant table.

## Status by phase

Source of truth for current state is `understanding.txt`. Phases follow the plans in `docs/superpowers/plans/`.

| Phase | Scope | Status |
|---|---|---|
| **0 — Foundation** | Project scaffold, typed settings (`APP_` env prefix), docker-compose (Postgres+PostGIS, Redis), `/health`, Alembic, Celery skeleton, audit module, savepoint test isolation. | Done, merged |
| **1 — Identity & AI Menu** | Restaurant signup + argon2/JWT auth, riders CRUD, settings patch; `llm/` port (`FakeExtractor`/`ClaudeExtractor`); menu upload → vision extraction → draft dishes, diff vs active menu, availability toggle, activation completeness gate (dish number + price mandatory). | Done, merged |
| **2 — WhatsApp Core** | `whatsapp/` adapter (Mock + Cloud API) with `X-Hub-Signature-256` verify; idempotent webhook pipeline (`webhook_events`); transactional outbox + Celery delivery worker (retry/dead-letter); `conversation/` models + greeting-state dialogue engine that renders the digital menu; zero-build web simulator. | Done, merged |
| **3 — Ordering** | `ordering/` context: fuzzy dish matching, multi-turn item collection, address capture/confirm, order FSM with transactional state, modification (SLA clock restart), cancellation + resale, status replies, end-to-end simulator smoke test. | **Gating** (this branch, `feat/phase-3`) |
| **4 — Logistics & Dispatch** | `dispatch/`, `sla/`, `cod/`: nearest-rider auto-dispatch, batching (≤3 orders / 10-min window / proximity), delivery FSM, SLA-monitor beat task + proactive notifications, live rider location, automatic late coupon, COD ledger. | Planned |
| **5 — React Dashboard** | Vite + React + TS "tactical operations" SPA: JWT login, live ops board with SLA color threading, order detail, menu manager, riders board, conversations w/ manual takeover, settings. Polling-first behind a swappable transport. | Planned |
| **6 — Predictions & Marketing** | `predictions/` (numpy demand baseline behind `ForecastModel` port, LLM context adjustment, MAPE tracking) + `marketing/` (segments, Meta template lifecycle, UAE send-window + cap + STOP opt-out, coupon integration, analytics). | Planned |
| **7 — Hardening** | Observability (structured logs, request IDs, Sentry, Prometheus), rate limiting, outbox backpressure/dead-letter alerting, security hardening, load harness with SLOs, graceful drain. | Planned |

## Quickstart

```bash
# 1. Environment (Python 3.12)
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env

# 2. Infrastructure: Postgres+PostGIS on :5433, Redis on :6380
docker compose up -d

# 3. Create the test database (once)
docker compose exec db psql -U app -d restaurant -c "CREATE DATABASE restaurant_test;"

# 4. Apply migrations to the dev DB
.venv/bin/alembic upgrade head

# 5. Run the API (mock WhatsApp provider mounts the simulator)
.venv/bin/uvicorn app.main:app --reload --port 8000

# 6. Run the Celery worker (outbox delivery, schedulers)
.venv/bin/celery -A apps.workers.celery_app:celery_app worker --loglevel=info
```

- **API docs:** http://localhost:8000/docs · **health:** http://localhost:8000/health
- **WhatsApp simulator** (mock provider only): http://localhost:8000/simulator/ — chat as a fake customer; it injects inbound messages and polls the MockProvider send log for outbound replies.

### Tests

Tests require the docker DB and use the `restaurant_test` database with savepoint-rollback isolation. A second worker can run against `restaurant_test2` for parallelism.

```bash
.venv/bin/pytest                                   # full suite
.venv/bin/pytest tests/menu/test_diff.py -v        # one file
.venv/bin/pytest tests/identity/test_auth.py::test_jwt_roundtrip -v
.venv/bin/ruff check src apps tests                # lint
```

### Frontend (Phase 5)

```bash
cd frontend
npm install
npm run dev          # Vite dev server
npm test             # vitest
```

## Architecture sketch

```
        ┌───────────────────────────────┐
        │  React Dashboard SPA (manager)│   REST + (later) WebSocket
        └───────────────┬───────────────┘
                        │
┌───────────────────────▼────────────────────────────────────────┐
│  FastAPI app  (app.main:create_app)                            │
│  /webhooks/whatsapp   /api/v1/*   /simulator/* (mock only)      │
├─────────────────────────────────────────────────────────────────┤
│  Bounded contexts (src/app/<module>)  — import-isolated         │
│  identity · menu · conversation · ordering · audit · outbox     │
│  webhook · whatsapp(adapter) · llm/geo/weather (ports)          │
│  later: dispatch · sla · cod · predictions · marketing          │
│  Per module: models.py · schemas.py · service.py · router.py    │
│  Routers are HTTP-only; they call services, never other models. │
├─────────────────────────────────────────────────────────────────┤
│  Celery workers (apps/workers)  queues: outbox · dispatch ·     │
│  sla_monitor · schedulers · ml · marketing                      │
├──────────────┬──────────────────┬───────────────────────────────┤
│ PostgreSQL16 │ Redis 7          │ External (behind ports):      │
│ + PostGIS    │ broker / cache / │ WhatsApp Cloud API · Claude   │
│ :5433        │ hot positions    │ Google Maps · Weather  :6380  │
└──────────────┴──────────────────┴───────────────────────────────┘
```

**Key patterns**

- **Ports & adapters** — external systems sit behind a port interface with a fake (tests/dev) and a real implementation, selected by an `APP_*_PROVIDER` env var: `llm` (`FakeExtractor`/`ClaudeExtractor`), `whatsapp` (`MockProvider`/`CloudAPIProvider`), `geo` (haversine/Google Maps), `weather` (fake/real). Tests override ports via FastAPI dependency injection — never hit real APIs.
- **Transactional outbox** — every outbound WhatsApp message is written to `outbox_messages` in the same transaction as the state change; a Celery worker delivers with retry + dead-letter, so no send is lost.
- **Idempotent webhooks** — inbound events keyed by provider message ID; duplicates dropped.
- **Audit log** — every state change calls `audit/service.py:record_audit` in the same transaction; append-only.
- **Multi-tenancy** — every tenant table carries `restaurant_id`; routes resolve the tenant from the JWT bearer via `identity/deps.py:current_restaurant`. The restaurant row is the manager account (no separate users table yet).
- **Explicit FSMs** — Order/Delivery statuses are fixed strings; illegal transitions raise and every transition is audited.

See `docs/architecture.md` for bounded-context tables, data-flow diagrams, the port/adapter inventory, migration conventions, and the test architecture.

## Business rules (non-negotiable)

- COD only. Max delivery radius 10 km. Delivery fee tiers: ≤3 km free / 3–5 km AED 5 / >5 km AED 10.
- SLA: 40 min customer-facing, 30 min internal target, 10 min buffer per batched order. A confirmed order modification (allowed only before `ready`) restarts the SLA clock.
- Riders are employees — no accept/reject step in dispatch; managers can deactivate a rider from future assignment.
- Late delivery (system/rider fault) → automatic coupon, **except** weather delays disclosed at order time.
- Dish numbers and prices are mandatory; menu activation is blocked if any dish lacks a number or price.
- Customer-facing dish descriptions: max 3 lines, never include price.
- Cancellation after cooking started → order auto-listed for resale, excluded from the same phone / person / address.
- Money is `Numeric(8,2)` / `Decimal` in AED. DB stores UTC; Celery time zone is Asia/Dubai.

## Repository map

```
src/app/            FastAPI app + bounded contexts (config.py, db.py, main.py)
  identity/         restaurants, riders, argon2/JWT auth, tenant deps
  menu/             menus, dishes, upload/diff/activation
  conversation/     conversations, messages, dialogue engine
  ordering/         orders FSM, matching, fees, order dialogue
  webhook/          inbound WhatsApp webhook + normalizer (idempotent)
  whatsapp/         provider port + Mock + Cloud API adapters
  llm/ geo/ weather/  external-integration ports (fake + real) + factory
  outbox/           transactional outbox model + delivery worker
  audit/            append-only audit log
apps/
  workers/          Celery app (celery_app.py)
  simulator/        zero-build web chat simulator (mock provider)
frontend/           Vite + React + TS manager dashboard (Phase 5)
alembic/            migrations (env.py filters PostGIS system tables)
tests/              pytest suite (savepoint isolation, port overrides)
docs/
  superpowers/specs/   design spec (single source of truth)
  superpowers/plans/   per-phase implementation plans
  architecture.md      deeper architecture reference
understanding.txt   running dated log of project state
CLAUDE.md           agent guidance / conventions
```

## Reference docs

- **Spec (single source of truth for business rules):** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`
- **Architecture deep-dive:** `docs/architecture.md`
- **Implementation plans:** `docs/superpowers/plans/2026-06-06-phase-{0-1,2,3,4,5,6,7}-*.md`
- **Conventions / agent guidance:** `CLAUDE.md`
- **Project state log:** `understanding.txt`
