# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

## MANDATORY: Act as Full stack developer and AI and ML engineer with 5 years of experince. Update understanding.txt after every code change in bullet poing with date and time log and also look into plugins and use them. Always preffer multi agent approach. Investegate producer, source, consumer, handler, plan, implement and run always run a smoke test after implementing, NO hallucination, No assumptions, No ambiguity, Do not drift from goal. 100% enterprise Grade code properly wired and production ready. At the begining of the session you have to read this file. Before changing any edits read last 3 bullet points: 

Multi-tenant SaaS platform: restaurants run delivery operations entirely through WhatsApp — customer ordering, AI menu digitization, own-fleet rider dispatch with live tracking, smart batching under a hard 40-minute SLA, ML demand predictions, marketing automation, plus a React manager dashboard.

**Read these before changing anything:**
- Spec (single source of truth for business rules): `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`
- Active implementation plan: `docs/superpowers/plans/2026-06-06-phase-0-1-foundation.md`

## Commands

```bash
# environment
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker compose up -d                      # postgres+postgis :5433, redis :6380
docker compose exec db psql -U app -d restaurant -c "CREATE DATABASE restaurant_test;"  # once

# tests (require docker db; tests use restaurant_test DB, recreate schema per test)
.venv/bin/pytest                          # full suite
.venv/bin/pytest tests/menu/test_diff.py -v                   # one file
.venv/bin/pytest tests/identity/test_auth.py::test_jwt_roundtrip -v  # one test

# lint
.venv/bin/ruff check src apps tests

# migrations
.venv/bin/alembic revision --autogenerate -m "name"
.venv/bin/alembic upgrade head

# run
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/celery -A apps.workers.celery_app:celery_app worker --loglevel=info
```

## Architecture

Modular monolith (FastAPI, async SQLAlchemy 2, Celery) — see spec §2 for full diagram.

- `src/app/<module>/` — bounded contexts: `identity`, `menu`, `llm`, `audit`, later `conversation`, `ordering`, `dispatch`, `marketing`, `predictions`. Within a module: `models.py` (SQLAlchemy), `schemas.py` (Pydantic I/O), `service.py` (business logic), `router.py` (HTTP only). **Routers never touch other modules' models — they call services.**
- `apps/workers/` — Celery app; queues for dispatch, SLA monitor, schedulers, ML, marketing, outbox.
- External integrations live behind ports: `llm/port.py` (`FakeExtractor` for tests/dev, `ClaudeExtractor` for prod, chosen by `APP_LLM_PROVIDER`), later `whatsapp/` adapter (Mock + Cloud API) and `geo/` (Google Maps + haversine fallback). Tests override ports via FastAPI dependency injection — never hit real APIs in tests.
- Settings: `app/config.py`, pydantic-settings, `APP_` env prefix, `.env` file. `get_settings()` is cached — tests set env vars before importing app modules (see `tests/conftest.py` top).
- Multi-tenancy: every tenant table carries `restaurant_id`; routes resolve tenant via `identity/deps.py:current_restaurant` (JWT bearer). Restaurant row IS the manager account (no separate users table yet).
- Audit: every state change calls `audit/service.py:record_audit` in the same transaction. Append-only.
- Migrations: alembic autogenerate; new model modules must be imported in BOTH `alembic/env.py` and `tests/conftest.py` to register metadata.

## Non-negotiable business rules (from spec)

- COD only; max delivery radius 10 km; fee tiers ≤3 km free / 3–5 km AED 5 / >5 km AED 10.
- SLA: customer told 40 min, internal target 30 min, 10 min buffer per batched order. Order modification (allowed only before `ready`) restarts the SLA clock after customer confirms.
- Riders are employees — no accept/reject step in dispatch.
- Late delivery → automatic coupon, EXCEPT weather delays disclosed at order time.
- Dish numbers mandatory; menu activation blocked if any dish lacks number or price.
- Customer-facing dish descriptions: max 3 lines, never include price.
- Cancelled-after-cooking orders auto-resell, excluded from same phone/person/address.

## Conventions

- TDD: failing test first, then implementation (plan tasks are structured this way).
- Money: `Numeric(8,2)` / `Decimal`, AED. Time zone: Asia/Dubai (Celery), UTC in DB.
- Order/Delivery statuses are explicit FSM strings — never invent new ones; spec §3 lists them.
- Commit per task, conventional-commit style (`feat:`, `chore:`).
- New tables using TimestampMixin: add BEFORE UPDATE trigger trg_<table>_updated_at in their migration (see updated_at_triggers migration).