# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

## MANDATORY: Act as Full stack developer and AI and ML engineer with 5 years of experince. Update understanding.txt after every code change in bullet poing with date and time log and also look into plugins and use them. Always preffer multi agent approach. Investegate producer, source, consumer, handler, plan, implement and run always run a Unit Testing, Integration Testing, System Testing, End-to-End (E2E) Testing, User Acceptance Testing (UAT), Performance Testing, Load Testing, Stress Testing, Security Testing, Usability Testing, Black-Box Testing, White-Box Testing, Grey-Box Testing, Regression Testing, Smoke Testing and Sanity Testing after implementing, NO hallucination, No assumptions, No ambiguity, Do not drift from goal. 100% enterprise Grade code properly wired and production ready. At the begining of the session you have to read this file. Before changing any edits read last 3 bullet points: 

Multi-tenant multilingual SaaS platform: restaurants run delivery operations entirely through WhatsApp — customer ordering, AI menu digitization, own-fleet rider dispatch with live tracking, smart batching under a hard 40-minute SLA, ML demand predictions, marketing automation, plus a React manager dashboard.

 read these pages https://www.anthropic.com/engineering/building-effective-agents https://www.anthropic.com/engineering/writing-tools-for-agents https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents and learn about evals https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents 
 **Foundational Blog**  
https://lilianweng.github.io/posts/2023-06-23-agent/

**Core Papers**  
https://arxiv.org/abs/2210.03629  
https://arxiv.org/abs/2302.04761  
https://arxiv.org/abs/2303.11366  
https://github.com/noahshinn/reflexion  
https://arxiv.org/abs/2305.16291  
https://voyager.minedojo.org/  
https://arxiv.org/abs/2304.03442  
https://github.com/joonspk-research/generative_agents

**Benchmarks**  
https://arxiv.org/abs/2311.12983  
https://huggingface.co/spaces/gaia-benchmark/leaderboard  
https://arxiv.org/abs/2307.13854  
https://arxiv.org/abs/2308.03688  
https://github.com/THUDM/AgentBench

**Best Free Course**  
https://huggingface.co/learn/agents-course  
https://github.com/huggingface/agents-course

**Key Frameworks**  
https://langchain-ai.github.io/langgraph/  
https://microsoft.github.io/autogen/  
https://docs.crewai.com/

**Curated Lists**  
https://github.com/hyp1231/awesome-llm-powered-agent  
https://github.com/luo-junyu/awesome-agent-papers  
https://github.com/Shubhamsaboo/awesome-llm-apps

**Production / Advanced**  
https://arxiv.org/abs/2504.19413

**Read these before changing anything:**
- Spec (single source of truth for business rules): `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`
- Active implementation plan: `docs/superpowers/plans/2026-06-06-phase-0-1-foundation.md`

## Knowledge Graph (Graphify) — MANDATORY

The codebase has a live knowledge graph in `graphify-out/` (3940 nodes, 6842 edges, 361 communities).

**Before any code change:**
1. Query the graph for the relevant area: `/graphify query "<what you're about to change>"`
2. Check god nodes touched by the change (`handle_inbound`, `get_settings`, `record_audit`, `lint_template`, `app.ordering.models`) — changes near these have wide blast radius.
3. Review community membership of affected files — cross-community changes need extra care.

**After any code change:**
1. Run `/graphify . --update` to re-extract only changed files and rebuild the graph.
2. Check that no new AMBIGUOUS edges appeared in the affected area.

**Graph artifacts:**
- `graphify-out/graph.html` — interactive visualization (open in browser)
- `graphify-out/GRAPH_REPORT.md` — god nodes, surprising connections, community labels
- `graphify-out/graph.json` — raw GraphRAG-ready data

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

# frontend (manager dashboard — React/Vite in frontend/)
cd frontend && npm install
cd frontend && npm run dev          # local UI :5173
cd frontend && npm test             # vitest unit tests
cd frontend && npm run lint         # tsc --noEmit

# playwright e2e — ALWAYS use vendored install (do NOT npm install from registry/git URL)
# Source: https://github.com/microsoft/playwright.git → vendor/playwright (built monorepo)
# frontend links @playwright/test via file:../vendor/playwright/packages/playwright-test
cd vendor/playwright && npm ci && npm run build   # first-time / after git pull
cd frontend && npm install                        # relink local packages
cd frontend && npx playwright install             # browser binaries (once per version)
cd frontend && npm run e2e                        # all e2e specs (frontend/e2e/)
cd frontend && npx playwright test --list         # discover tests
cd frontend && npx playwright test e2e/smoke.spec.ts  # single file
cd frontend && npx playwright test --ui           # interactive runner
```

### Playwright (vendored) — mandatory for dashboard E2E

Use the **local clone** at `vendor/playwright` sourced from [microsoft/playwright](https://github.com/microsoft/playwright.git). The dashboard (`frontend/`) depends on it through `file:` paths in `frontend/package.json` (with `overrides` for `playwright` + `playwright-core`).

**Do not** install Playwright via `npm install @playwright/test` or `github:microsoft/playwright#path:…` — the monorepo root resolves incorrectly and breaks `playwright.config.ts`.

**First-time setup (or fresh clone):**
```bash
git clone --depth 1 https://github.com/microsoft/playwright.git vendor/playwright
cd vendor/playwright && npm ci && npm run build
cd ../../frontend && npm install && npx playwright install
```

**Update to latest upstream main:**
```bash
cd vendor/playwright && git pull && npm ci && npm run build
cd ../../frontend && npm install && npx playwright install
```

**E2E layout:** specs in `frontend/e2e/`, config in `frontend/playwright.config.ts` (preview server on `:4173`). Requires Node ≥20 for the vendored build.

**Developing Playwright itself:** see `vendor/playwright/CONTRIBUTING.md` and skills under `vendor/playwright/.claude/skills/` (`playwright-dev`, `playwright-triage`, `playwright-devops`).

## Architecture

Modular monolith (FastAPI, async SQLAlchemy 2, Celery) — see spec §2 for full diagram.

- `src/app/<module>/` — bounded contexts: `identity`, `menu`, `llm`, `audit`, later `conversation`, `ordering`, `dispatch`, `marketing`, `predictions`. Within a module: `models.py` (SQLAlchemy), `schemas.py` (Pydantic I/O), `service.py` (business logic), `router.py` (HTTP only). **Routers never touch other modules' models — they call services.**
- `apps/workers/` — Celery app; queues for dispatch, SLA monitor, schedulers, ML, marketing, outbox.
- External integrations live behind ports: `llm/port.py` (`FakeExtractor` for tests/dev, `ClaudeExtractor` for prod, chosen by `APP_LLM_PROVIDER`), later `whatsapp/` adapter (Mock + Cloud API) and `geo/` (Google Maps + haversine fallback). Tests override ports via FastAPI dependency injection — never hit real APIs in tests.
- Settings: `app/config.py`, pydantic-settings, `APP_` env prefix, `.env` file. `get_settings()` is cached — tests set env vars before importing app modules (see `tests/conftest.py` top).
- Multi-tenancy: every tenant table carries `restaurant_id`; routes resolve tenant via `identity/deps.py:current_restaurant` (JWT bearer). Restaurant row IS the manager account (no separate users table yet).
- Audit: every state change calls `audit/service.py:record_audit` in the same transaction. Append-only.
- Migrations: alembic autogenerate; new model modules must be imported in BOTH `alembic/env.py` and `tests/conftest.py` to register metadata.
- Frontend: `frontend/` — React manager dashboard; unit tests via Vitest, E2E via vendored Playwright (`vendor/playwright` → `frontend/e2e/`).

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