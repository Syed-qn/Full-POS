# Dispatch Enterprise Design — SLA-First Batching (Phases 0–4)

**Date:** 2026-06-30  
**Status:** Implemented (Phases 0–4 code complete; ops rollout per §12)
**Parent spec:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` §4.3–§4.4  
**Implementation plan:** `docs/superpowers/plans/2026-06-30-dispatch-batching-enterprise-upgrade.md`  
**Constraints chosen:** Full spec §4.3 alignment (~4 weeks) + **SLA safety first** (on-time % over batch rate)

---

## 1. Executive summary

Move dispatch from a conservative greedy MVP to **enterprise-grade pooled delivery** for a single restaurant with an **employee fleet** and a **hard 40-minute WhatsApp SLA**.

The codebase already contains OR-Tools VRP, hold windows, corridor detour, prep nudge, shadow compare, and partial re-optimization. This design closes the gap in **defaults, timing alignment, explainability, zones, and re-batch until pickup** — without a greenfield dispatch system.

**Primary metric:** ≥ 92% of orders delivered within 40 minutes of confirm (no regression).  
**Secondary metric:** batch rate ≥ 25% (stretch 35%); avg stops per batch ≥ 1.4 (stretch 1.6).

When batching conflicts with SLA, **SLA always wins**: drop, solo-route, unbatch, or hold — never force a late stack.

---

## 2. Goals, non-goals & success criteria

### 2.1 Goals

1. **SLA-first routing** — OR-Tools enforces 40-min hard constraint per order; greedy is audited fallback only.
2. **Spec §4.3 completeness (Phases 0–4)** — correct defaults, prep-aware pool, manual zones, re-batch until pickup, explainability.
3. **Trustworthy ops** — preview matches dispatch; managers see why batched / why not.
4. **Safe multi-tenant rollout** — shadow compare, presets, per-restaurant rollback without deploy.

### 2.2 Non-goals (this cycle)

- Phase 6 ML (prep bandit, batch-benefit model)
- Auto-zones v2 (PR-3.2) — manual zones only
- Batch rate above 35% if it threatens SLA
- Multi-restaurant pooling, gig accept/reject, stacks > 3 orders
- New microservice or message bus for dispatch

### 2.3 SLA-first policy

```
40-min hard ceiling (per order, from confirm)
        │
        ├── OR-Tools VRP (default)
        ├── +10 min buffer per extra batched stop (tenant default)
        ├── Re-batch / unbatch safety valve (Phase 4)
        └── Maximize batching INSIDE SLA-feasible set only
```

**Conflict resolution order:**

1. Drop or solo-route rather than breach SLA.
2. Unbatch / split on projected breach (Phase 4).
3. Hold solo briefly only if batch-mate improves SLA margin and margin exists.
4. Never widen `batch_proximity_km` if 7-day on-time % is below 92%.

### 2.4 Success criteria (4-week exit)

| Metric | Target | Priority |
|--------|--------|----------|
| On-time within 40 min | ≥ 92%, no regression vs baseline | P0 |
| `breach_40` + auto-coupon rate | ≤ baseline | P0 |
| Preview vs dispatch match | 100% on simulation harness seeds | P0 |
| Explainability coverage | 100% assignments have `algorithm_score` | P0 |
| Batch rate (2+ stops per run) | ≥ 25% (stretch 35%) | P1 |
| Avg stops per completed batch | ≥ 1.4 (stretch 1.6) | P1 |
| Manager manual reassign | ↓ 30% | P1 |
| Engine fallback rate | < 5% of runs | P1 |

---

## 3. Current state & gaps

### 3.1 What exists

| Component | Path | Capability |
|-----------|------|------------|
| Greedy batching | `src/app/dispatch/batching.py` | Proximity cluster, 30-min internal gate, geo legs |
| OR-Tools VRP | `src/app/dispatch/optimizer.py` | 40-min hard constraint, priority solo, drop infeasible |
| Dispatch orchestrator | `src/app/dispatch/service.py` | Advisory lock, hold, greedy/ortools branch, shadow compare |
| Rider scoring | `src/app/dispatch/scoring.py` | Distance, workload, on-time % |
| SLA monitor | `src/app/sla/monitor.py` | yellow_30, red_35, breach_40 + coupon |
| Tracking ETA | `src/app/dispatch/tracking.py` | Geo ETA + 10 min × preceding stops |

### 3.2 Gaps blocking “enterprise grade”

| Gap | Impact | Phase |
|-----|--------|-------|
| `dispatch_engine: greedy` default | 30-min internal gate, not 40-min hard VRP | 0–1 |
| `sla_buffer_per_order_minutes: 0` in tenant defaults | Aggressive batching vs spec 10-min buffer | 0 |
| `preview_batch_groups()` proximity-only | Dashboard labels disagree with dispatch | 0 |
| Batch at `ready` only | Rider idle at counter; food sits | 2 |
| `batch_hold_seconds: 0` | No smart wait for batch-mate | 0–2 |
| Haversine clustering only | False batch/reject across highways | 3 |
| Re-batch mostly at assign | Late same-area order gets second rider | 4 |
| Thin explainability UI | Managers can't audit decisions | 1 |

### 3.3 Travel time & 40-minute SLA (reference)

See plan doc §3.6 for full detail. Summary:

- **Elapsed** = `now − sla_confirmed_at` (starts at confirm, not rider departure).
- **Route time** = restaurant → stop 1 + inter-stop legs via `geo/port`.
- **Greedy gate:** `elapsed + route + buffer ≤ 30` internal per stop.
- **OR-Tools gate:** `elapsed + route ≤ 40` per node.
- **Rider → restaurant** excluded from batch SLA math (scoring + smart hold only).
- **Not end-to-end guaranteed:** post-assign kitchen delay, traffic, stale GPS → `sla/monitor` backstop.

---

## 4. Architecture

### 4.1 Overview

Dispatch remains a **bounded context** in the modular monolith (`src/app/dispatch/`). Celery sweep + event hooks call `run_dispatch_engine()`; pure functions perform batching/VRP; persistence via existing transaction in `service.py`.

```
Triggers (ready, sweep, rider freed, priority)
    → advisory lock (per restaurant)
    → candidate pool builder
    → smart hold gate
    → engine: OR-Tools (default) | greedy (fallback)
    → commit: Batch, BatchOrder, Assignment, audit
    → outbox: rider + manager alerts
```

### 4.2 Component boundaries

| Component | Responsibility | Status |
|-----------|----------------|--------|
| `candidate_pool.py` | Build `OrderCandidate[]` from DB (ready + prep-aware) | **New** (extract from service) |
| `batching.py` | Greedy cluster, SLA gate, `compute_batch_total_est_min` | Existing |
| `optimizer.py` | SLA-first VRP | Existing |
| `zones.py` | Same-zone / corridor eligibility | **New** (Phase 3) |
| `scoring.py` | Rider pick per batch | Existing |
| `service.py` | Orchestration, hold, commit, re-batch, `run_batch_plan()` | Extended |
| `tracking.py` | Live ETA with batch buffer | Existing |

**Refactor (Phase 0):** Extract `run_batch_plan()` shared by `preview_batch_groups()` and `_dispatch()`. Preview uses `dry_run=True` (no rider commit).

### 4.3 Engine selection

| Path | SLA constraint | When |
|------|----------------|------|
| OR-Tools | Hard 40 min per node | Default (`dispatch_engine: ortools`) |
| Greedy | 30 min internal + buffer | 2s timeout, missing origin, Conservative preset |

Shadow compare logs greedy vs OR-Tools served counts without changing assignment until SLA gate passes.

### 4.4 Persistence (no new tables Phases 0–3)

| Table | Use |
|-------|-----|
| `batches` | `status`, `route` JSON, `total_est_min` |
| `batch_orders` | `sequence`, `delivered_at` |
| `assignments` | `algorithm_score` JSONB (extended) |
| `orders` | `sla_confirmed_at`, `sla_deadline`, `rider_id`, `status`, `prep_deadline` |

Zones stored in `restaurants.settings.delivery_zones` (JSON array).

---

## 5. Functional design

### 5.1 Candidate pool (Phase 2)

| Status | Include when | Exclude when |
|--------|--------------|--------------|
| `ready` | Always (geocoded) | No drop-off coords |
| `preparing` | `prep_deadline - now ≤ prep_dispatch_lead_min` (default 8) | SLA pressure near ceiling |
| `assigned` | OR-Tools: not picked up — locked to rider | `picked_up`, `arriving` |

New setting: `prep_dispatch_lead_min` (default 8).

### 5.2 Smart hold (Phase 2)

```
hold_until = min(
    ready_at + batch_hold_seconds,
    prep_deadline_mate - rider_eta_to_restaurant
)
```

Hold allowed only if:

- Plausible batch-mate (ready nearby OR preparing within lead window)
- SLA margin allows remaining hold time
- Not `priority`
- No ready batch-mate already (assign immediately instead)

Under SLA pressure: **skip hold**, solo dispatch.

### 5.3 Zone model (Phase 3)

```json
[
  {"name": "Marina", "center_lat": 25.08, "center_lng": 55.14, "radius_km": 2.5}
]
```

Batch if same zone OR corridor detour ≤ `batch_max_detour_km`. OR-Tools uses Google distance matrix when `APP_GEO_PROVIDER=google_maps`; haversine fallback on API failure.

### 5.4 Re-batch FSM (Phase 4)

| Batch status | Re-batch? | Cross-rider reassign? |
|--------------|-----------|------------------------|
| `planned` | Yes — insert / resequence | No for locked orders |
| `picked_up` | **No** | **No** |
| `in_progress` | **No** | **No** |

Triggers: new `ready` order + periodic sweep while any batch is `planned`.

**Unbatch:** re-solve projects any stop > 40 min → split batch → solo or hold → audit `batch_split_sla_risk`.

Existing `_dispatch_ortools` already includes movable `assigned` orders with `locked_rider_id`; Phase 4 extends **triggers** and **notification** on resequence.

### 5.5 Preparing-order rider notification

**Decision:** Option **A** — rider sees all batch order numbers immediately; navigation / first stop pin only for **ready** stops. Rider is not sent to kitchen until at least the first assigned stop is ready (spec §4.4 flow integrity).

### 5.6 Explainability schema (Phase 1)

`assignments.algorithm_score` JSONB per order:

```json
{
  "engine": "ortools",
  "engine_fallback": false,
  "route_sequence": [12, 14, 9],
  "total_est_min": 28.5,
  "per_stop": [
    {"order_id": 12, "projected_min": 22.1, "route_min": 8.0, "buffer_min": 0},
    {"order_id": 14, "projected_min": 28.5, "route_min": 14.2, "buffer_min": 10}
  ],
  "rejections": [
    {"order_id": 15, "reason": "sla_risk", "projected_min": 41.2}
  ],
  "zone": "Marina",
  "batch_reason": "same_zone_corridor_ok"
}
```

**Rejection reasons:** `sla_risk` | `proximity` | `max_per_batch` | `no_rider` | `no_geo` | `priority_solo` | `hold_matured_solo`

Exposed on order detail and `GET /api/v1/dispatch/assignments` (new).

### 5.7 Preview invariant

`preview_batch_groups()` must call the same `run_batch_plan()` as `_dispatch()` (dry run). CI asserts label equality on harness seeds.

---

## 6. Error handling

| Failure | Behaviour |
|---------|-----------|
| OR-Tools timeout (>2s) | Greedy fallback; `engine_fallback=true` in score |
| Infeasible order | `unassigned`; stays `ready`; manager alert if projected > 40 while waiting |
| No geocoded drop-off | Skip auto-dispatch; manager alert (existing) |
| No riders | `needs_retry`; predictive SLA alert if projected > 40 |
| Google Maps down | Haversine + 25 km/h; ETAs flagged estimated |
| Re-batch SLA breach | Unbatch; audit `batch_split_sla_risk` |
| Re-batch after pickup | Reject; new order separate run |
| Priority order | Dedicated nearest rider; never batched |

**Principle:** degrade to more conservative path or leave unassigned with visibility — never silent late batch.

### 6.1 Re-optimization messaging

| Event | Rider | Customer |
|-------|-------|----------|
| Initial assign | Batch order numbers | Tracking when picked up |
| Resequence (planned) | Updated stop order | ETA update if stop moved later |
| Unbatch | Stop removed from run | New ETA if already assigned |

---

## 7. API surface

| Endpoint | Change | Phase |
|----------|--------|-------|
| `POST /api/v1/dispatch/trigger` | Unchanged | — |
| `GET /api/v1/dispatch/assignments` | **New** — explainability list | 1 |
| Order detail | `batch_preview_label`, `dispatch_explain` | 1 |
| Settings PATCH | Presets, `prep_dispatch_lead_min`, `delivery_zones` | 0–3 |
| Live ops map | Batch polylines, SLA rings | 5 |

---

## 8. Configuration

### 8.1 New tenant defaults (SLA-safe launch)

| Key | Value |
|-----|-------|
| `dispatch_engine` | `"ortools"` |
| `sla_buffer_per_order_minutes` | `10` |
| `batch_hold_seconds` | `120` |
| `batch_proximity_km` | `1.5` |
| `batch_max_detour_km` | `0.5` |
| `prep_dispatch_lead_min` | `8` |
| `max_orders_per_batch` | `3` |

### 8.2 Presets (Settings UI)

| Preset | Engine | proximity | detour | hold | buffer |
|--------|--------|-----------|--------|------|--------|
| **SLA-safe launch** (default new) | ortools | 1.5 | 0.5 | 120 | 10 |
| **Dense city** (after 7 green days) | ortools | 2.0 | 0.8 | 150 | 10 |
| **Suburban** | ortools | 3.0 | 1.5 | 120 | 10 |
| **Conservative (rollback)** | greedy | 1.0 | 0 | 0 | 10 |

Existing tenants: opt-in via preset; no silent migration.

### 8.3 Production environment

- `APP_GEO_PROVIDER=google_maps`
- `dispatch_shadow_compare=true` (14-day minimum before widening geometry)

---

## 9. Implementation schedule

| Week | PRs | Deliverable |
|------|-----|-------------|
| **1** | PR-0.3, PR-1.1, PR-0.1, PR-5.1 | Shared preview; OR-Tools default; presets; simulation CI |
| **2** | PR-1.2, PR-1.3, PR-2.1–2.3 | Explainability UI; prep-aware pool; smart hold |
| **3** | PR-3.1, PR-3.3, PR-5.3 | Manual zones; distance matrix; KPI panel |
| **4** | PR-4.1–4.3, PR-5.2 | Re-batch; unbatch; live ops map |

**Deferred:** PR-3.2 auto-zones, Phase 6 ML.

### 9.1 PR dependency graph

```
Phase 0 (preview + defaults)
    └── Phase 1 (OR-Tools + explainability)
            ├── Phase 2 (prep-aware)
            ├── Phase 3 (zones)
            └── Phase 5 KPIs / simulation
Phase 2 + 3 → Phase 4 (re-batch)
Phase 4 → Phase 5 live map
```

### 9.2 SLA gate per PR (merge blocker)

- `pytest tests/dispatch/ -v` green
- SLA boundary cases pass (39 min elapsed, buffer edges)
- Simulation harness A,B,A,D,B,A passes
- Preview == engine tests pass
- `ruff check src/app/dispatch tests/dispatch`
- `graphify update .` — no new AMBIGUOUS edges in dispatch area

### 9.3 Production rollout

1. Record baseline week (greedy + shadow).
2. Apply SLA-safe launch preset + `google_maps`.
3. Monitor 7 days — on-time P0, batch rate P1.
4. Widen to Dense city preset only if on-time ≥ 92%.
5. Week 2+: prep-aware → zones → re-batch (canary one restaurant first).
6. **Rollback:** Conservative preset (no deploy).

---

## 10. Testing strategy

### 10.1 Test files

| File | Scope |
|------|-------|
| `test_batch.py` | Greedy, SLA gate, corridor |
| `test_optimizer.py` | OR-Tools constraints, drops |
| `test_batch_hold.py` | Hold, SLA pressure skip |
| `test_batch_preview.py` | Preview == engine |
| `test_dispatch_engine.py` | E2E assign, fallback |
| `test_prep_aware_dispatch.py` | **New** — preparing in pool |
| `test_zones.py` | **New** — zone + detour |
| `test_rebatch.py` | **New** — insert, unbatch, no-op after pickup |
| `test_simulation_harness.py` | **New** — A,B,A,D,B,A + seeds |

### 10.2 SLA boundary cases (CI P0)

```
elapsed=35, route=4, buffer=0  → must NOT batch (greedy) / route (ortools)
elapsed=20, 2-stop route=15, buffer=10 → max projected ≤ 40 → batch OK
elapsed=38, any batch → hold skipped
```

### 10.3 Performance targets

| Measure | Target |
|---------|--------|
| OR-Tools solve (≤6 orders, 3 riders) | p99 < 2s |
| Dispatch sweep per restaurant | < 5s total |
| Distance matrix 3×3 | < 500ms, cached per sweep |

### 10.4 UAT (simulator)

1. Three nearby orders ready → one batch, one rider.
2. Stop-2 tracking ETA includes batch buffer.
3. Non-batched pair shows `sla_risk` in manager UI.
4. `breach_40` triggers coupon (non-weather).

---

## 11. Key code references

| Area | Path |
|------|------|
| Greedy batching | `src/app/dispatch/batching.py` |
| Dispatch engine | `src/app/dispatch/service.py` |
| OR-Tools VRP | `src/app/dispatch/optimizer.py` |
| Rider scoring | `src/app/dispatch/scoring.py` |
| SLA monitor | `src/app/sla/monitor.py` |
| Tracking ETA | `src/app/dispatch/tracking.py` |
| Order SLA deadline | `src/app/ordering/service.py` |
| Default settings | `src/app/identity/models.py` |
| Manager settings UI | `frontend/src/screens/SettingsScreen.tsx` |
| Upgrade plan (PR detail) | `docs/superpowers/plans/2026-06-30-dispatch-batching-enterprise-upgrade.md` |

---

## 12. Definition of done

Enterprise-grade dispatch (Phases 0–4) is complete when:

- [x] All §10 tests pass in CI
- [x] Preview matches engine on harness seeds
- [ ] On-time ≥ 92% for 7 consecutive days (canary restaurant)
- [ ] `breach_40` ≤ baseline
- [x] 100% assignments have `algorithm_score`
- [x] Re-batch works for `planned`; blocked after `picked_up`
- [ ] Rollback preset verified in UAT
- [x] Implementation plan executed and merged

---

## 13. Changelog

| Date | Author | Note |
|------|--------|------|
| 2026-06-30 | Engineering | Design spec from brainstorming (B+C: full §4.3, SLA-first) |