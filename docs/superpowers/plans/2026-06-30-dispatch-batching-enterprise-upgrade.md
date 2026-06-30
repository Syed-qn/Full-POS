# Dispatch & Batching Enterprise Upgrade Plan

**Date:** 2026-06-30  
**Status:** Approved plan (not yet implemented)  
**Spec reference:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` §4.3  
**Goal:** Move from greedy proximity MVP to restaurant-grade pooled delivery — applying Zomato / Swiggy / Talabat / Noon *principles* while respecting our constraints: **own employee fleet, single restaurant, hard 40-minute WhatsApp SLA, max 3 orders per batch**.

---

## 1. Executive summary

Industry giants optimize **city-wide margin** with ML + continuous VRP on a gig pool. We optimize **one kitchen + employee riders + fixed customer promise**. The codebase already contains most building blocks (OR-Tools VRP, hold window, corridor detour, prep nudge, shadow compare). The gap is **defaults, timing, explainability, and ops UX** — not a greenfield dispatch system.

| Layer | Today | Target |
|-------|-------|--------|
| Solver | `greedy` default | `ortools` SLA-first VRP default |
| Hold | `batch_hold_seconds = 0` | Smart hold 120–180s (prep-aware) |
| Trigger | Batch at `ready` only | Prep-deadline-aware candidate pool |
| Spatial | Flat `batch_proximity_km` | Zones + corridor detour |
| Re-batch | Locked at assign | Re-solve until rider picks up |
| Ops | Limited visibility | Explainability + KPIs + simulation |

---

## 2. Success metrics (measure before/after)

Track for 90 days post-rollout per restaurant:

| Metric | Target |
|--------|--------|
| **Batch rate** | ≥ 35% of ready orders ride with another stop (2+ per run) |
| **Avg stops per completed batch** | ≥ 1.6 |
| **SLA on-time %** | ≥ 92% within 40 min (no regression) |
| **Solo dispatches** | ↓ 30% in dense zones |
| **Manager manual reassign** | ↓ 50% |
| **Rider idle at restaurant** | ↓ 20% (prep-aligned dispatch) |

**Instrumentation:** `assignments.algorithm_score`, `batches.total_est_min`, `sla_events`, dispatch metrics (`DISPATCH_RUNS`, `DISPATCH_ORDERS`).

---

## 3. Current state (what exists)

### 3.1 Batching engine (`src/app/dispatch/batching.py`)

- Greedy proximity clustering within `batch_proximity_km` (default **1 km**)
- 10-minute readiness window
- Max **3** orders per batch (settings)
- SLA gate: `elapsed + route_to_stop + buffer_per_order ≤ 30 min` internal target
- Inter-stop travel via geo port (Google Maps or haversine fallback)
- Corridor / on-the-way batching when `batch_max_detour_km > 0` (default **0** = off)
- Priority orders → sealed single-order batches

### 3.2 Dispatch service (`src/app/dispatch/service.py`)

- Default engine: **`greedy`**; **`ortools`** opt-in via `dispatch_engine` setting
- `batch_hold_seconds` default **0** (no wait for batch-mate)
- 30s in-process + Celery dispatch sweep
- `preview_batch_groups()` — forecast labels for order list (must align with engine)
- `_nudge_batchable_cooking_orders()` — kitchen `batch_expedite` when cooking order shares area with outgoing delivery
- Shadow OR-Tools compare (`dispatch_shadow_compare`)
- Per-restaurant Postgres advisory lock (prevents race → one-by-one assign)

### 3.3 OR-Tools optimizer (`src/app/dispatch/optimizer.py`)

- SLA-first hard constraint, minimize drive time
- Priority orders pulled to dedicated nearest rider
- Drop infeasible orders with penalty (never block whole plan)
- Locked orders (assigned, not picked) pinned to current rider

### 3.4 Settings (manager dashboard)

Exposed in `SettingsScreen.tsx`: `dispatch_engine`, `batch_proximity_km`, `batch_max_detour_km`, `batch_hold_seconds`, `batch_expedite_radius_km`, `max_orders_per_batch`.

### 3.5 Gap vs marketplace giants

| Capability | Zomato / Swiggy | Talabat / Noon | This platform |
|------------|-----------------|----------------|---------------|
| Scope | City, 10k+ riders | Multi-restaurant zones | **1 restaurant fleet** |
| Batching driver | Margin + capacity | Zone SLA + partners | **40 min SLA + labor** |
| Spatial model | H3 / zones | Zones + distance bands | **Haversine radius** |
| Solver | Continuous VRP + ML | VRP + rules | **Greedy (+ optional OR-Tools)** |
| Ready signal | Predicted + KDS | Tablet / POS | **Manual `ready`** |
| Hold for stack | Always (implicit) | Often | **Opt-in, default off** |
| Re-batch | Until pickup | Until pickup | **Mostly at assign** |

---

## 4. Target architecture

```
┌─────────────────────────────────────────────────────────┐
│ INPUTS                                                   │
│  • confirmed / preparing / ready orders                  │
│  • rider GPS + availability                            │
│  • prep_deadline + cook estimate                       │
│  • delivery zones / corridor                           │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│ ENGINE                                                   │
│  1. Candidate pool builder                             │
│  2. Smart hold window                                  │
│  3. OR-Tools SLA-first VRP (fallback: greedy)          │
│  4. Explainability layer                               │
└──────────────────────────┬──────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────┐
│ OUTPUTS                                                  │
│  • Batch + route JSON (stops, ETAs)                    │
│  • Assignment audit (why batched / why not)            │
│  • Dashboard live map + KPIs                           │
│  • Rider WhatsApp / native app notification            │
└─────────────────────────────────────────────────────────┘
```

---

## 5. What we will NOT copy

- Multi-restaurant city-wide pooling (out of spec)
- Gig rider accept/reject (riders are employees)
- 5+ order stacks (cap stays at 3 per business rules)
- Marketplace surge pricing (optional later via existing `priority` flag only)

---

## 6. Implementation phases

### Phase 0 — Quick wins (3–5 days, no schema)

**Problem:** Enterprise features exist but defaults are conservative.

#### PR-0.1: Smart defaults + presets

| Item | Detail |
|------|--------|
| **Files** | `src/app/identity/models.py` (`DEFAULT_SETTINGS`), `frontend/src/screens/SettingsScreen.tsx` |
| **New tenant defaults** | `dispatch_engine: "ortools"`, `batch_hold_seconds: 150`, `batch_max_detour_km: 0.8`, `batch_proximity_km: 2.0` |
| **UI presets** | **Dense city** / **Suburban** / **Conservative (legacy)** with tooltips |
| **Tests** | `tests/identity/test_defaults.py`, settings API round-trip |

#### PR-0.2: Shadow compare in production

| Item | Detail |
|------|--------|
| **Files** | `src/app/config.py`, deploy env |
| **Change** | `dispatch_shadow_compare: true` in prod; structured logs for greedy vs ortools served counts |
| **Ops** | 14-day shadow → flip `ortools` per restaurant if ortools serves ≥ greedy |

#### PR-0.3: Align preview with engine

| Item | Detail |
|------|--------|
| **Files** | `src/app/dispatch/service.py` — `preview_batch_groups()` |
| **Change** | Call same `build_batches()` + SLA gate as `_dispatch()`, not simplified proximity-only greedy |
| **Tests** | Extend `tests/dispatch/test_batch_preview.py` with SLA + detour cases |

**Exit criteria:** Preview labels match actual dispatch; new restaurants batch more on day one.

---

### Phase 1 — OR-Tools as production default (1 week)

#### PR-1.1: Default engine + rollout safety

| Item | Detail |
|------|--------|
| **Files** | `src/app/dispatch/service.py`, `src/app/identity/models.py` |
| **Logic** | `ortools` default; 2s solve timeout → fallback `greedy` + audit `engine_fallback` |
| **Tests** | `tests/dispatch/test_optimizer.py`, `tests/dispatch/test_dispatch_engine.py` — include spec A,B,A,D,B,A case |

#### PR-1.2: Assignment explainability

| Item | Detail |
|------|--------|
| **Files** | `src/app/dispatch/service.py`, `src/app/dispatch/models.py` (`algorithm_score` JSONB) |
| **Payload example** | `{"engine":"ortools","rejections":[{"order_id":12,"reason":"sla_risk","projected_min":31.2}],"route_sequence":[4,7,9],"total_est_min":28.5}` |
| **API** | Expose in order detail or `GET /api/v1/dispatch/assignments` |

#### PR-1.3: Dashboard — why batched / why not

| Item | Detail |
|------|--------|
| **Files** | Live ops / order detail components, `frontend/src/lib/types.ts` |
| **UI** | Batch label, engine used, SLA projection per stop, rejection reasons |

**Exit criteria:** Managers see why two orders didn't batch; OR-Tools is live default.

---

### Phase 2 — Prep-aware dispatch (1.5 weeks)

**Problem:** Giants batch on predicted ready time; we only batch at `ready`.

#### PR-2.1: Expanded candidate pool

| Item | Detail |
|------|--------|
| **Files** | `src/app/dispatch/service.py` — `_build_candidate_pool()` |
| **Include** | `ready` + `preparing` when `prep_deadline - now ≤ prep_dispatch_lead_min` (new setting, default 8 min) |
| **Rule** | Pre-batch only: rider assigned when first stop is `ready`; others may still be `preparing` |
| **Tests** | `tests/dispatch/test_prep_aware_dispatch.py` (new) |

#### PR-2.2: Smart hold (not fixed seconds)

Replace flat `batch_hold_seconds` with:

```
hold_until = min(
  ready_at + batch_hold_seconds,
  prep_deadline_mate - rider_eta_to_restaurant
)
```

Hold only when plausible batch-mate exists (see `tests/dispatch/test_batch_hold.py`).

#### PR-2.3: Wire cook estimate

Use `ordering/service.py`: `compute_prep_deadline`, `compute_cook_estimate`, dish `prep_minutes`, `default_prep_minutes`. Later: `predictions` module.

#### PR-2.4: Kitchen signal (optional)

WhatsApp manager alert when pre-batch formed: rider assigned for orders #12 + #14 — finish together.

**Exit criteria:** Rider arrives as food finishes; fewer solo trips; less idle time at counter.

---

### Phase 3 — Zone & corridor model (1.5 weeks)

**Problem:** Single `batch_proximity_km` fails across mixed UAE geography.

#### PR-3.1: Delivery zones v1 (manual)

| Item | Detail |
|------|--------|
| **Files** | `src/app/dispatch/zones.py` (new), `restaurants.settings.delivery_zones` |
| **Schema** | `[{name, center_lat, center_lng, radius_km}]` or polygon (v2) |
| **Rule** | Batch if same zone OR corridor detour ≤ `max_detour_km` |

#### PR-3.2: Auto-zone v2

Celery job: cluster 90-day drop-offs; suggest zones in Settings for manager approval.

#### PR-3.3: Google distance matrix for OR-Tools

Batch matrix API in `geo/google_maps.py` when `APP_GEO_PROVIDER=google_maps`; haversine fallback.

**Exit criteria:** Dense vs suburban areas batch correctly; fewer false rejects.

---

### Phase 4 — Dynamic re-batch until pickup (2 weeks)

**Problem:** Giants re-optimize until rider leaves restaurant; we lock at assign.

#### PR-4.1: Re-solve on new `ready`

When rider has `planned` batch (not `picked_up`) and new order fits SLA → insert into route. Audit `batch_resequenced`; notify rider app.

#### PR-4.2: Unbatch on SLA breach

Re-solve drops order → split batch, reassign or hold. Tests: `tests/dispatch/test_rebatch.py` (new).

#### PR-4.3: Locked order rules

Document and enforce: `assigned` + not `picked_up` = locked to rider; `picked_up` = no reassign (spec §4.4).

**Exit criteria:** Late same-area order joins existing run instead of new rider.

---

### Phase 5 — Ops & simulation (1 week)

#### PR-5.1: Dispatch simulation harness

Parametrized pytest or CLI: seed A,B,A,D,B,A → assert batch groups + SLA invariants. CI regression gate.

#### PR-5.2: Live ops map

Batch polylines, stop sequence, per-stop ETA, yellow/red SLA rings.

#### PR-5.3: KPI panel

Batch rate, avg stops/run, ortools vs greedy served (from shadow logs).

**Exit criteria:** Ops visibility comparable to internal marketplace tools at restaurant scale.

---

### Phase 6 — ML layer (optional, 2–3 weeks)

Only after Phases 1–4 are stable.

| Model | Input | Output | Use |
|-------|--------|--------|-----|
| Prep ETA | dishes, time, kitchen load | minutes | `prep_dispatch_lead_min` |
| Hold bandit | zone, hour, queue depth | seconds | replace fixed hold |
| Batch benefit | order pair features | P(success) | gate corridor joins |

- **Module:** `src/app/dispatch/learning/` (mirror `predictions/`)
- **Train:** weekly Celery on `ml` queue; per `restaurant_id`
- **Rollout:** shadow → canary → default

---

## 7. PR dependency graph

```
Phase 0 (defaults + preview align)
    └── Phase 1 (OR-Tools default + explainability)
            ├── Phase 2 (prep-aware dispatch)
            ├── Phase 3 (zones)          ← can parallel with Phase 2 after Phase 1
            └── Phase 5 (ops KPIs)
                    └── Phase 6 (ML)

Phase 2 + Phase 3 → Phase 4 (re-batch until pickup)
Phase 4 → Phase 5 (live map)
```

**Parallel tracks:** Phase 0 + 1 start immediately. Phase 3 can run parallel to Phase 2 after Phase 1 lands.

---

## 8. Testing strategy (every PR)

| Layer | Commands / files |
|-------|------------------|
| Unit | `tests/dispatch/test_batch.py`, `test_optimizer.py`, `test_batch_hold.py` |
| Integration | `tests/dispatch/test_dispatch_engine.py` |
| Simulation | A,B,A,D,B,A + SLA boundary cases |
| Full dispatch suite | `.venv/bin/pytest tests/dispatch/ -v` |
| Lint | `.venv/bin/ruff check src/app/dispatch tests/dispatch` |
| UAT | Simulator: 3 nearby orders marked ready → 1 batch, 40 min promise holds |

**TDD:** failing test first → implement → `graphify update` → commit (conventional: `feat(dispatch):`).

---

## 9. Recommended settings presets

### Dense city (e.g. Dubai Marina, JLT)

| Setting | Value |
|---------|-------|
| `dispatch_engine` | `ortools` |
| `batch_proximity_km` | `2.0` |
| `batch_max_detour_km` | `0.8` |
| `batch_hold_seconds` | `150` |
| `batch_expedite_radius_km` | `2.0` |
| `max_orders_per_batch` | `3` |

### Suburban (e.g. outer Dubai / Sharjah edges)

| Setting | Value |
|---------|-------|
| `dispatch_engine` | `ortools` |
| `batch_proximity_km` | `3.0` |
| `batch_max_detour_km` | `1.5` |
| `batch_hold_seconds` | `120` |
| `batch_expedite_radius_km` | `2.5` |

### Conservative (legacy behaviour)

| Setting | Value |
|---------|-------|
| `dispatch_engine` | `greedy` |
| `batch_proximity_km` | `1.0` |
| `batch_max_detour_km` | `0` |
| `batch_hold_seconds` | `0` |

---

## 10. Rollout schedule

| Week | Deliverable |
|------|-------------|
| 1 | Phase 0 + Phase 1 |
| 2 | Phase 2 (prep-aware pool + smart hold) |
| 3 | Phase 3 zones (manual) + Phase 5 KPIs |
| 4 | Phase 4 re-batch + dashboard map |
| 5+ | Phase 6 ML + auto-zones |

### Production flip checklist

1. Set `APP_GEO_PROVIDER=google_maps` for traffic-aware legs (prod).
2. Run shadow compare 14 days; document ortools win rate per restaurant.
3. Apply **Dense city** preset; tune `batch_proximity_km` from live map.
4. Train kitchen on existing `batch_expedite` nudge (already in `service.py`).
5. Monitor SLA % daily for 2 weeks; rollback preset if regression.

---

## 11. First implementation sprint (highest ROI)

Execute in order:

1. **PR-0.3** — preview = engine logic  
2. **PR-1.1** — OR-Tools default  
3. **PR-0.1** — settings presets  
4. **PR-2.1** — prep-aware candidate pool  

---

## 12. Key code references

| Area | Path |
|------|------|
| Greedy batching | `src/app/dispatch/batching.py` |
| Dispatch engine | `src/app/dispatch/service.py` |
| OR-Tools VRP | `src/app/dispatch/optimizer.py` |
| Rider scoring | `src/app/dispatch/scoring.py` |
| Default settings | `src/app/identity/models.py` (`DEFAULT_SETTINGS`) |
| Manager settings UI | `frontend/src/screens/SettingsScreen.tsx` |
| Batch hold tests | `tests/dispatch/test_batch_hold.py` |
| Optimizer tests | `tests/dispatch/test_optimizer.py` |
| Batch preview tests | `tests/dispatch/test_batch_preview.py` |
| Spec §4.3 | `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` |
| Phase 4 plan (original) | `docs/superpowers/plans/2026-06-06-phase-4-logistics.md` |

---

## 13. Changelog

| Date | Author | Note |
|------|--------|------|
| 2026-06-30 | Engineering | Initial plan from marketplace comparison + codebase audit |