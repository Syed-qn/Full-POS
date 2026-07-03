# Marketing Studio Full — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans per phase. TDD: failing test → implement → green. **Do not git commit until user approves.**

**Goal:** Deliver full manager Marketing Studio per `docs/superpowers/specs/2026-07-02-marketing-studio-full-design.md` in five phases.

**Architecture:** Incremental tabs on `MarketingScreen` (Approach 3); backend `marketing/` bounded context; reuse `run_campaign_send`, `SideDrawer`, existing Reports APIs.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Pydantic v2, React 18, Vitest, pytest, Celery.

**Spec:** `docs/superpowers/specs/2026-07-02-marketing-studio-full-design.md`

---

## Phase 1 — Campaigns tab (Prove ROI)

**Exit:** Campaigns tab with summary strip, table, detail drawer; enriched `GET /campaigns`; `rfm_segment` in broadcast stats.

### Task 1.1: Backend — enriched `CampaignResponse`

**Files:** `src/app/marketing/schemas.py`, `src/app/marketing/service.py`, `src/app/marketing/router.py`, `tests/marketing/test_router.py`

- [ ] Test `test_list_campaigns_includes_template_and_audience_labels` — FAIL
- [ ] Add `audience_label_for_campaign()` in `service.py`
- [ ] Extend `CampaignResponse` fields: `created_at`, `template_name`, `audience_label`, `segment_id`, `template_id`
- [ ] `list_campaigns`: join templates/segments, sort `created_at` desc
- [ ] Test `test_broadcast_persists_rfm_segment_in_stats` — store `rfm_segment` in `camp.stats` before send
- [ ] `pytest tests/marketing/test_router.py -v` green

### Task 1.2: Frontend — Campaigns tab

**Files:** `frontend/src/lib/marketingApi.ts`, `frontend/src/screens/MarketingScreen.tsx`, `MarketingScreen.module.css`, `frontend/src/components/SideDrawer.tsx` (reuse)

- [ ] Extend `CampaignResponse` TypeScript type
- [ ] Add `campaigns` tab; `usePoll(fetchCampaigns, 60_000)` when tab active
- [ ] Summary strip (4 metrics — same logic as `AnalyticsScreen`)
- [ ] Table + row click → `SideDrawer` with `getCampaignStats(id)`
- [ ] `frontend/src/screens/MarketingScreen.campaigns.test.tsx` green
- [ ] `npm test` green

---

## Phase 2 — Segments + broadcast targeting

**Exit:** Segments tab; compile/preview/delete APIs; RFM vs segment mutual exclusivity; coupon on broadcast.

### Task 2.1: Segment compile/preview/delete API

**Files:** `schemas.py`, `service.py`, `router.py`, `tests/marketing/test_router.py`

- [ ] `POST /segments/compile`, `POST /segments/preview`, `DELETE /segments/{id}`
- [ ] `compile_segment_from_english()` + dish catalog in prompt
- [ ] Tests per spec §4.2.10

### Task 2.2: Broadcast upgrades

- [ ] Mutual exclusivity `segment_id` vs `rfm_segment`
- [ ] Persist audience metadata in `campaign.stats`
- [ ] Coupon validation on broadcast

### Task 2.3: Frontend Segments tab + WhatsApp audience

- [ ] `marketingApi.ts` segment functions
- [ ] Segments builder UI + saved table
- [ ] WhatsApp: audience state machine + coupon row

---

## Phase 3 — Template lifecycle polish

**Exit:** Approval timeline, shimmer, auto-poll, fix-with-AI, ephemeral Today's Special, fallback template.

### Task 3.1: Fix template + ephemeral create

- [ ] `POST /templates/{id}/fix`, `ephemeral` on `TemplateCreate`
- [ ] `TEMPLATE_FIX_PROMPT` + `fix_template_body()`
- [ ] `resolve_todays_special_template()`, cleanup settings side effect

### Task 3.2: Frontend template UX

- [ ] `ApprovalTimeline.tsx`, shimmer CSS, 30s poll
- [ ] Fix with AI flow; fallback picker on Today's Special

### Task 3.3: Meta image upload test + beat verify

- [ ] `test_template_meta_upload.py` httpx mock
- [ ] Confirm celery beat entries

---

## Phase 4 — Automation tab

**Exit:** Four preset automations; `on_order_delivered` hook; workers automation_tick + recurring_promo_tick.

### Task 4.1: Migrations + models

- [ ] `marketing_automations`, `recurring_message_state`, `marketing_automation_sends`
- [ ] Register in `alembic/env.py`, `tests/conftest.py`

### Task 4.2: Automations service + evaluators

- [ ] `marketing/automations.py` presets
- [ ] `on_order_delivered`, `run_automation_tick`, `run_recurring_promo_tick`
- [ ] Hook in `dispatch/delivery.py`
- [ ] Extend `run_campaign_send` for `audience_ids` in stats

### Task 4.3: API + workers + UI

- [ ] `GET/PATCH /automations`
- [ ] Celery tasks + */5 scheduled sends
- [ ] Automation tab cards

---

## Phase 5 — AI image + scheduled broadcast

**Exit:** Generate image port; schedule broadcast UI; cancel/reschedule campaigns.

### Task 5.1: Image generation port

- [ ] `image_port.py`, `image_placeholder.py`, `POST /templates/image/generate`
- [ ] Rate limit per restaurant/day

### Task 5.2: Scheduled broadcast

- [ ] `scheduled_at` on `BroadcastRequest`
- [ ] `DELETE /campaigns/{id}`, `PATCH /campaigns/{id}/schedule`
- [ ] WhatsApp schedule mode UI; Campaigns scheduled rows

---

## Execution order

1. Phase 1 → review → Phase 2 → … → Phase 5
2. After each phase: `pytest tests/marketing/`, `ruff check`, frontend `npm test`
3. Update `understanding.txt` (no git commit until user says)