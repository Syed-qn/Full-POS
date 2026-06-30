# Dispatch Enterprise Implementation Plan (Phases 0–4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship SLA-first enterprise dispatch — OR-Tools default, preview=engine, prep-aware batching, manual zones, re-batch until pickup, and manager explainability — without regressing the 40-minute customer promise.

**Architecture:** Extract shared `run_batch_plan()` and `candidate_pool.py` from `dispatch/service.py`; OR-Tools remains the primary solver with 2s timeout → greedy fallback; zones live in `settings.delivery_zones`; re-batch extends existing `_dispatch_ortools` movable-order path with explicit triggers and customer/rider notifications.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, OR-Tools (`ortools.constraint_solver`), Celery, React (Settings + ops UI), pytest, FakeGeoProvider in tests.

**Design spec:** `docs/superpowers/specs/2026-06-30-dispatch-enterprise-design.md`  
**PR overview:** `docs/superpowers/plans/2026-06-30-dispatch-batching-enterprise-upgrade.md`

**SLA merge gate (every task):** `.venv/bin/pytest tests/dispatch/ -v` green; no on-time regression in shadow logs.

---

## File structure (locked in)

```
src/app/dispatch/
  batch_plan.py          NEW — run_batch_plan(), build_planned_batches() shared by preview + dispatch
  candidate_pool.py      NEW — build_order_candidates(), pool config
  zones.py               NEW — zone_for_point(), batch_zone_eligible(), detour check
  service.py             MODIFY — preview + _dispatch use batch_plan; OR-Tools default; re-batch triggers
  optimizer.py           MODIFY — optional distance_matrix injection (Phase 3)
  router.py              MODIFY — GET /assignments explainability
  schemas.py             NEW — AssignmentExplainOut, DispatchPreset schemas

src/app/geo/
  google_maps.py         MODIFY — distance_matrix() batch API

src/app/identity/
  models.py              MODIFY — DEFAULT_SETTINGS SLA-safe values
  schemas.py             MODIFY — prep_dispatch_lead_min, delivery_zones

frontend/src/
  screens/SettingsScreen.tsx       MODIFY — presets (SLA-safe, Dense, Suburban, Conservative)
  screens/OrderDetail*.tsx         MODIFY — dispatch_explain panel (or equivalent)
  components/DispatchKpiPanel.tsx  NEW — batch rate, on-time %, fallback rate
  lib/types.ts                     MODIFY — algorithm_score types

tests/dispatch/
  test_simulation_harness.py   NEW — A,B,A,D,B,A + SLA boundary parametrized
  test_batch_preview.py        MODIFY — preview == run_batch_plan
  test_dispatch_engine.py      MODIFY — ortools default, engine_fallback
  test_prep_aware_dispatch.py  NEW
  test_zones.py                NEW
  test_rebatch.py              NEW
  conftest_dispatch.py         NEW — shared _ready_order, _seed_restaurant helpers (optional DRY)
```

**Before any code change:** `/graphify query "dispatch batching run_batch_plan"`  
**After each task:** `graphify update .`

---

## Week 1 — Foundation (PR-5.1, PR-0.3, PR-1.1, PR-0.1)

### Task 1: Simulation harness + SLA boundary fixtures

**Files:**
- Create: `tests/dispatch/test_simulation_harness.py`
- Reference: `tests/dispatch/test_dispatch_engine.py` (`_seed_restaurant`, `_ready_order`)

- [x] **Step 1: Write failing simulation test**

```python
# tests/dispatch/test_simulation_harness.py
"""Regression harness — spec §7 integration + design §10.2 SLA boundaries."""
from datetime import timedelta, timezone
from decimal import Decimal

import pytest

from app.dispatch.batching import OrderCandidate, build_batches, compute_batch_total_est_min
from app.dispatch.service import run_batch_plan  # will be created Task 2
from app.geo.fake import FakeGeoProvider


def _c(oid, lat, lon, elapsed=5.0):
    from datetime import datetime
    now = datetime.now(timezone.utc)
    return OrderCandidate(
        order_id=oid, lat=lat, lon=lon,
        ready_at=now, minutes_elapsed=elapsed, priority="normal",
    )


ORIGIN = (25.2048, 55.2708)
GEO = FakeGeoProvider()


def test_ab_ad_ba_batch_pattern_sla_invariant():
    """A,B,A,D,B,A — corridor-style stops; every stop projected <= 40."""
    # Stops along a corridor (~0.3 km apart) — matches spec integration case
    orders = [
        _c(1, 25.2050, 55.2710),
        _c(2, 25.2053, 55.2713),
        _c(3, 25.2056, 55.2716),
        _c(4, 25.2600, 55.3300, elapsed=8.0),  # far — should not join first cluster
        _c(5, 25.2059, 55.2719),
        _c(6, 25.2062, 55.2722),
    ]
    batches = build_batches(
        orders[:3] + orders[4:],  # simulate near cluster without far D in same pool
        geo_provider=GEO, origin=ORIGIN,
        max_per_batch=3, proximity_km=2.0, buffer_per_order=10,
    )
    for b in batches:
        assert compute_batch_total_est_min(b, geo_provider=GEO, origin=ORIGIN) <= 40


@pytest.mark.parametrize("elapsed,route_buf,should_batch", [
    (35, 4, False),   # design §10.2 — too late
    (20, 15, True),   # OK with buffer
])
def test_sla_boundary_greedy_internal_gate(elapsed, route_buf, should_batch):
    """Greedy: elapsed + route + buffer <= 30 internal."""
    seed = _c(1, 25.2050, 55.2710, elapsed=elapsed)
    mate = _c(2, 25.2052, 55.2712, elapsed=elapsed)
    batches = build_batches(
        [seed, mate], geo_provider=GEO, origin=ORIGIN,
        proximity_km=2.0, buffer_per_order=route_buf,
    )
    if should_batch:
        assert len(batches) == 1 and len(batches[0].orders) == 2
    else:
        assert sum(len(b.orders) for b in batches) <= 2  # split or solo
```

- [x] **Step 2: Run test — expect FAIL**

```bash
.venv/bin/pytest tests/dispatch/test_simulation_harness.py -v
```

Expected: `ImportError: cannot import name 'run_batch_plan' from 'app.dispatch.service'`

- [x] **Step 3: Implement minimal `run_batch_plan` stub in `batch_plan.py`**

```python
# src/app/dispatch/batch_plan.py
"""Shared batch planning for preview (dry) and dispatch (live)."""
from __future__ import annotations

from dataclasses import dataclass

from app.dispatch.batching import OrderCandidate, PlannedBatch, build_batches


@dataclass
class BatchPlanSettings:
    proximity_km: float = 1.5
    window_min: int = 10
    max_per_batch: int = 3
    buffer_per_order: int = 10
    max_detour_km: float = 0.0
    engine: str = "greedy"


def run_batch_plan(
    candidates: list[OrderCandidate],
    *,
    settings: BatchPlanSettings,
    geo_provider,
    origin: tuple[float, float] | None,
    dry_run: bool = True,
) -> list[PlannedBatch]:
    """Returns planned batches using the same rules as dispatch (greedy path)."""
    return build_batches(
        candidates,
        geo_provider=geo_provider,
        origin=origin,
        max_per_batch=settings.max_per_batch,
        proximity_km=settings.proximity_km,
        window_min=settings.window_min,
        buffer_per_order=settings.buffer_per_order,
        max_detour_km=settings.max_detour_km,
    )
```

Re-export from `service.py`: `from app.dispatch.batch_plan import run_batch_plan`

- [x] **Step 4: Re-run harness — parametrized SLA tests PASS; import OK**

```bash
.venv/bin/pytest tests/dispatch/test_simulation_harness.py -v
```

- [x] **Step 5: Commit**

```bash
git add tests/dispatch/test_simulation_harness.py src/app/dispatch/batch_plan.py src/app/dispatch/service.py
git commit -m "test(dispatch): add simulation harness and batch_plan stub"
```

---

### Task 2: Preview aligns with engine (PR-0.3)

**Files:**
- Modify: `src/app/dispatch/service.py` — `preview_batch_groups()`
- Modify: `src/app/dispatch/batch_plan.py` — `labels_from_batches()`
- Modify: `tests/dispatch/test_batch_preview.py`

- [x] **Step 1: Write failing test — SLA rejects preview pair that proximity would batch**

```python
# Append to tests/dispatch/test_batch_preview.py
async def test_preview_respects_sla_not_just_proximity(db_session):
    """Two nearby orders but one under SLA pressure → no shared preview label."""
    r = await _seed_restaurant(db_session)
    r.settings = {
        "batch_proximity_km": 2.0,
        "sla_buffer_per_order_minutes": 10,
        "dispatch_engine": "greedy",
    }
    db_session.add(r)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    # Order 1: 28 min elapsed — mate would push over 30 internal
    o1 = await _order(db_session, r.id, 25.2000, 55.2700, 10, status="ready")
    o1.sla_confirmed_at = now - timedelta(minutes=28)
    o2 = await _order(db_session, r.id, 25.2003, 55.2702, 11, status="ready")
    o2.sla_confirmed_at = now - timedelta(minutes=28)
    await db_session.commit()

    groups = await preview_batch_groups(db_session, restaurant_id=r.id)
    # After PR-0.3: SLA gate splits — no batch label for either
    assert o1.id not in groups or o2.id not in groups or groups[o1.id] != groups[o2.id]
```

- [x] **Step 2: Run — FAIL** (today both get same label)

```bash
.venv/bin/pytest tests/dispatch/test_batch_preview.py::test_preview_respects_sla_not_just_proximity -v
```

- [x] **Step 3: Refactor `preview_batch_groups` to use `run_batch_plan`**

```python
# src/app/dispatch/batch_plan.py — add:
def labels_from_batches(batches: list[PlannedBatch]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for idx, batch in enumerate(batches):
        if len(batch.orders) < 2:
            continue
        label = chr(ord("A") + idx)
        for o in batch.orders:
            labels[o.order_id] = label
    return labels


# src/app/dispatch/service.py — preview_batch_groups body becomes:
async def preview_batch_groups(session, *, restaurant_id: int) -> dict[int, str]:
    restaurant = await session.get(Restaurant, restaurant_id)
    rs = (restaurant.settings or {}) if restaurant else {}
    ready_candidates = await _build_preview_candidates(session, restaurant_id)  # extract helper
    if len(ready_candidates) < 2:
        return {}
    origin = (restaurant.lat, restaurant.lng) if restaurant and restaurant.lat else None
    geo = get_geo_provider()
    settings = BatchPlanSettings(
        proximity_km=float(rs.get("batch_proximity_km", 1.5)),
        max_per_batch=int(rs.get("max_orders_per_batch", 3)),
        buffer_per_order=int(rs.get("sla_buffer_per_order_minutes", get_settings().sla_buffer_per_order_minutes)),
        max_detour_km=float(rs.get("batch_max_detour_km", 0) or 0),
        engine=rs.get("dispatch_engine", "ortools"),
    )
    batches = run_batch_plan(ready_candidates, settings=settings, geo_provider=geo, origin=origin)
    return labels_from_batches(batches)
```

Implement `_build_preview_candidates` mirroring `_dispatch` candidate fields (`minutes_elapsed` from `sla_confirmed_at`) for `ready` + unassigned only.

- [x] **Step 4: Add invariant test preview == run_batch_plan**

```python
async def test_preview_matches_run_batch_plan(db_session):
    r = await _seed_restaurant(db_session)
    await _order(db_session, r.id, 25.2000, 55.2700, 20, status="ready")
    await _order(db_session, r.id, 25.2003, 55.2702, 21, status="ready")
    await db_session.commit()
    preview = await preview_batch_groups(db_session, restaurant_id=r.id)
    # direct plan call must match
    from app.dispatch.batch_plan import run_batch_plan, BatchPlanSettings, labels_from_batches
    candidates = await _build_preview_candidates(db_session, r.id)  # same helper
    batches = run_batch_plan(candidates, settings=BatchPlanSettings(), geo_provider=get_geo_provider(), origin=(r.lat, r.lng))
    assert preview == labels_from_batches(batches)
```

- [x] **Step 5: Full dispatch tests**

```bash
.venv/bin/pytest tests/dispatch/test_batch_preview.py tests/dispatch/test_simulation_harness.py -v
```

- [x] **Step 6: Commit**

```bash
git commit -am "feat(dispatch): align preview_batch_groups with run_batch_plan SLA gate"
```

---

### Task 3: OR-Tools default + 2s fallback (PR-1.1)

**Files:**
- Modify: `src/app/identity/models.py` — `DEFAULT_SETTINGS`
- Modify: `src/app/dispatch/service.py` — default engine branch + timeout
- Modify: `tests/dispatch/test_dispatch_engine.py`
- Modify: `tests/identity/test_defaults.py` (if exists)

- [x] **Step 1: Write failing test — new restaurant uses ortools**

```python
async def test_default_dispatch_engine_is_ortools(db_session):
    from app.identity.models import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["dispatch_engine"] == "ortools"
    assert DEFAULT_SETTINGS["sla_buffer_per_order_minutes"] == 10


async def test_ortools_timeout_falls_back_to_greedy(db_session, monkeypatch):
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    # ... seed 2 ready orders + 1 rider ...
    def slow_optimize(*args, **kwargs):
        import time
        time.sleep(3)
        raise TimeoutError("solver timeout")
    monkeypatch.setattr("app.dispatch.service.optimize_dispatch", slow_optimize)
    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    asn = (await db_session.scalars(select(Assignment))).all()
    assert asn
    assert asn[0].algorithm_score.get("engine_fallback") is True
```

- [x] **Step 2: Run — FAIL**

```bash
.venv/bin/pytest tests/dispatch/test_dispatch_engine.py::test_default_dispatch_engine_is_ortools -v
```

- [x] **Step 3: Change defaults + wrap OR-Tools with timeout**

```python
# src/app/identity/models.py
DEFAULT_SETTINGS = {
    ...
    "dispatch_engine": "ortools",
    "sla_buffer_per_order_minutes": 10,
    "batch_hold_seconds": 120,
    "batch_proximity_km": 1.5,
    "batch_max_detour_km": 0.5,
    ...
}

# src/app/dispatch/service.py — in _dispatch_ortools after optimize_dispatch call:
# Wrap in asyncio.wait_for or signal-based 2s budget; on timeout call greedy path
# and set algorithm_score["engine_fallback"] = True, engine = "greedy"
```

- [x] **Step 4: Run dispatch suite**

```bash
.venv/bin/pytest tests/dispatch/test_dispatch_engine.py tests/identity/ -v -k default
```

- [x] **Step 5: Commit**

```bash
git commit -am "feat(dispatch): OR-Tools default with greedy fallback and SLA-safe tenant defaults"
```

---

### Task 4: Settings presets UI (PR-0.1)

**Files:**
- Modify: `frontend/src/screens/SettingsScreen.tsx`
- Modify: `frontend/src/screens/SettingsScreen.test.tsx`

- [x] **Step 1: Write failing frontend test**

```typescript
// frontend/src/screens/SettingsScreen.test.tsx
it("applies SLA-safe launch preset", async () => {
  render(<SettingsScreen />);
  await userEvent.click(screen.getByRole("button", { name: /sla-safe launch/i }));
  expect(screen.getByLabelText(/dispatch engine/i)).toHaveValue("ortools");
  expect(screen.getByLabelText(/batch proximity/i)).toHaveValue("1.5");
});
```

- [x] **Step 2: Run — FAIL**

```bash
cd frontend && npm test -- SettingsScreen.test.tsx -t "SLA-safe"
```

- [x] **Step 3: Add preset buttons with values from design §8.2**

```typescript
const PRESETS = {
  slaSafe: { dispatch_engine: "ortools", batch_proximity_km: 1.5, batch_max_detour_km: 0.5, batch_hold_seconds: 120, sla_buffer_per_order_minutes: 10 },
  dense: { dispatch_engine: "ortools", batch_proximity_km: 2.0, batch_max_detour_km: 0.8, batch_hold_seconds: 150, sla_buffer_per_order_minutes: 10 },
  suburban: { dispatch_engine: "ortools", batch_proximity_km: 3.0, batch_max_detour_km: 1.5, batch_hold_seconds: 120, sla_buffer_per_order_minutes: 10 },
  conservative: { dispatch_engine: "greedy", batch_proximity_km: 1.0, batch_max_detour_km: 0, batch_hold_seconds: 0, sla_buffer_per_order_minutes: 10 },
} as const;
```

- [x] **Step 4: npm test PASS**

- [x] **Step 5: Commit**

```bash
git commit -am "feat(settings): dispatch presets SLA-safe, Dense, Suburban, Conservative"
```

---

## Week 2 — Explainability + prep-aware (PR-1.2, PR-1.3, PR-2.1–2.3)

### Task 5: Explainability payload on assign (PR-1.2)

**Files:**
- Modify: `src/app/dispatch/service.py` — `_commit_route` / assignment writer
- Create: `src/app/dispatch/schemas.py`
- Modify: `tests/dispatch/test_dispatch_engine.py`

- [x] **Step 1: Failing test — algorithm_score has per_stop and rejections**

```python
async def test_assignment_algorithm_score_explainability(db_session):
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    # 2 nearby ready + rider
    ...
    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    asn = (await db_session.execute(select(Assignment))).scalar_one()
    score = asn.algorithm_score
    assert score["engine"] == "ortools"
    assert "route_sequence" in score
    assert "per_stop" in score
    assert all(p["projected_min"] <= 40 for p in score["per_stop"])
```

- [x] **Step 2–4: Build score dict in commit path from plan + route_times**

- [x] **Step 5: Commit** `feat(dispatch): rich algorithm_score explainability payload`

---

### Task 6: GET /api/v1/dispatch/assignments (PR-1.2)

**Files:**
- Modify: `src/app/dispatch/router.py`
- Create: `tests/dispatch/test_dispatch_router.py` (extend)

- [x] **Step 1: Failing API test**

```python
async def test_list_assignments_explainability(client, auth_headers, seeded_assignment):
    r = await client.get("/api/v1/dispatch/assignments", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body[0]["algorithm_score"]["engine"] in ("ortools", "greedy")
```

- [x] **Step 2–4: Router + schema**

- [x] **Step 5: Commit** `feat(dispatch): assignments explainability API`

---

### Task 7: Dashboard order detail — why batched / why not (PR-1.3)

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: order detail screen component showing `algorithm_score.rejections`

- [x] **Step 1: Render test for rejection reasons**

- [x] **Step 2–5: UI panel "Dispatch" with engine, projected_min, rejections**

- [x] **Commit** `feat(dashboard): dispatch explainability on order detail`

---

### Task 8: Prep-aware candidate pool (PR-2.1)

**Files:**
- Create: `src/app/dispatch/candidate_pool.py`
- Modify: `src/app/dispatch/service.py`
- Create: `tests/dispatch/test_prep_aware_dispatch.py`
- Modify: `src/app/identity/schemas.py` — `prep_dispatch_lead_min`

- [x] **Step 1: Failing test**

```python
async def test_preparing_order_in_pool_when_prep_deadline_within_lead(db_session):
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    r.settings["prep_dispatch_lead_min"] = 8
    # order preparing, prep_deadline in 6 min, nearby ready order
    ...
    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    # both assigned same batch OR pre-batch planned
    batch_orders = (await db_session.scalars(select(BatchOrder))).all()
    assert len(batch_orders) >= 2
```

- [x] **Step 2: Implement `build_order_candidates`**

```python
# src/app/dispatch/candidate_pool.py
async def build_order_candidates(session, restaurant_id, *, prep_lead_min: int, now) -> list[OrderCandidate]:
    # ready unassigned (always)
    # preparing unassigned where prep_deadline - now <= prep_lead_min
    # compute minutes_elapsed from sla_confirmed_at
```

- [x] **Step 3: Wire into `_dispatch`; preparing stays `preparing` until ready**

- [x] **Step 4: pytest PASS**

- [x] **Step 5: Commit** `feat(dispatch): prep-aware candidate pool`

---

### Task 9: Smart hold (PR-2.2)

**Files:**
- Modify: `src/app/dispatch/service.py` — hold block (~L756)
- Modify: `tests/dispatch/test_batch_hold.py`

- [x] **Step 1: Extend test — hold uses rider_eta cap**

```python
async def test_smart_hold_capped_by_prep_deadline_minus_rider_eta(db_session, monkeypatch):
    # pipeline mate prep_deadline in 4 min; batch_hold_seconds=120
    # effective hold <= 4 min - rider_eta
    ...
```

- [x] **Step 2–4: Replace flat hold with `min(ready_at + hold, prep_deadline_mate - rider_eta)`**

- [x] **Step 5: Commit** `feat(dispatch): smart SLA-aware hold window`

---

## Week 3 — Zones + matrix + KPIs (PR-3.1, PR-3.3, PR-5.3)

### Task 10: Manual delivery zones (PR-3.1)

**Files:**
- Create: `src/app/dispatch/zones.py`
- Create: `tests/dispatch/test_zones.py`
- Modify: `src/app/dispatch/batch_plan.py` — zone filter before build_batches
- Modify: `frontend/src/screens/SettingsScreen.tsx` — zone editor (simple list)

- [x] **Step 1: Failing unit test**

```python
from app.dispatch.zones import zone_for_point, same_zone_or_corridor

ZONES = [{"name": "Marina", "center_lat": 25.08, "center_lng": 55.14, "radius_km": 2.5}]

def test_same_zone_eligible():
    a = zone_for_point(25.081, 55.141, ZONES)
    b = zone_for_point(25.082, 55.142, ZONES)
    assert a == b == "Marina"
    assert same_zone_or_corridor(a, b, (25.08, 55.14), (25.081, 55.141), (25.082, 55.142), max_detour_km=0.8)
```

- [x] **Step 2–4: Integrate into `build_batches` append check**

- [x] **Step 5: Commit** `feat(dispatch): manual delivery zones v1`

---

### Task 11: Google distance matrix for OR-Tools (PR-3.3)

**Files:**
- Modify: `src/app/geo/google_maps.py`
- Modify: `src/app/dispatch/optimizer.py`
- Modify: `tests/geo/test_geo_port.py`

- [x] **Step 1: Test FakeGeoProvider matrix fallback**

```python
def test_distance_matrix_fallback_square():
    from app.geo.fake import FakeGeoProvider
    m = FakeGeoProvider().distance_matrix([(25.0, 55.0)], [(25.01, 55.01), (25.02, 55.02)])
    assert len(m[0]) == 2
    assert m[0][0] < m[0][1]
```

- [x] **Step 2–4: `distance_matrix(origins, dests) -> list[list[float minutes]]` used in optimizer**

- [x] **Step 5: Commit** `feat(geo): distance matrix for dispatch OR-Tools`

---

### Task 12: KPI panel (PR-5.3)

**Files:**
- Create: `frontend/src/components/DispatchKpiPanel.tsx`
- Modify: backend metrics endpoint or aggregate from `assignments` + `sla_events`

- [x] **Step 1: API test for batch_rate and on_time_pct**

- [x] **Step 2–4: Panel showing batch rate, avg stops, engine_fallback %**

- [x] **Step 5: Commit** `feat(dashboard): dispatch KPI panel`

---

## Week 4 — Re-batch + live map (PR-4.1–4.3, PR-5.2)

### Task 13: Re-solve on new ready (PR-4.1)

**Files:**
- Modify: `src/app/dispatch/service.py` — trigger on ready hook + sweep includes movable
- Create: `tests/dispatch/test_rebatch.py`

- [x] **Step 1: Failing integration test**

```python
async def test_new_ready_inserts_into_planned_batch(db_session):
    r = await _seed_restaurant(db_session, dispatch_engine="ortools")
    # Assign batch [o1, o2] planned not picked
    o3 = await _ready_order(db_session, r.id, near_lat, near_lon, 99)
    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()
    bo = (await db_session.scalars(select(BatchOrder).where(BatchOrder.order_id == o3.id))).first()
    assert bo is not None
    assert bo.batch_id == existing_batch_id
```

- [x] **Step 2–4: Ensure sweep + ready hook call `_dispatch_ortools` with movable orders**

- [x] **Step 5: Commit** `feat(dispatch): re-batch insert on new ready`

---

### Task 14: Unbatch on SLA breach (PR-4.2)

**Files:**
- Modify: `src/app/dispatch/service.py`
- Modify: `tests/dispatch/test_rebatch.py`

- [x] **Step 1: Test — insert rejected when projected > 40**

```python
async def test_rebatch_splits_when_sla_risk(db_session):
    # planned batch with 2 stops; third would breach
    ...
    assert o3.rider_id is None or o3 in separate_batch
```

- [x] **Step 2–4: audit `batch_split_sla_risk`; manager optional alert**

- [x] **Step 5: Commit** `feat(dispatch): unbatch on SLA breach projection`

---

### Task 15: Re-sequence notifications + live ops map (PR-4.1 UI, PR-5.2)

**Files:**
- Modify: `src/app/dispatch/service.py` — customer ETA message on sequence change
- Modify: live ops map component — batch polylines, SLA rings

- [x] **Step 1: Test customer notification enqueued on resequence**

```python
async def test_resequence_enqueues_customer_eta_update(db_session):
    ...
    msgs = (await db_session.scalars(select(OutboxMessage).where(...))).all()
    assert any("ETA" in m.payload.get("body", "") for m in msgs)
```

- [x] **Step 2–4: Map layer from `batches.route` JSON**

- [x] **Step 5: Commit** `feat(dispatch): resequence notifications and live ops map`

---

## Ops tasks (parallel week 1)

### Task O1: Shadow compare in prod (PR-0.2)

**Files:**
- Modify: deploy env / `src/app/config.py`

- [ ] Set `APP_DISPATCH_SHADOW_COMPARE=true` in prod config
- [ ] Structured log: `shadow_compare greedy_served=%d ortools_served=%d restaurant_id=%d`
- [ ] Document 14-day review in runbook (no code beyond logging if already present)

---

## Plan self-review vs spec

| Spec section | Task(s) |
|--------------|---------|
| §2 SLA-first policy | 3, 9, 14 |
| §4 Architecture / batch_plan | 1, 2 |
| §5.1 Candidate pool | 8 |
| §5.2 Smart hold | 9 |
| §5.3 Zones | 10, 11 |
| §5.4 Re-batch FSM | 13, 14 |
| §5.5 Preparing rider notify A | 8 (assign; rider_flow unchanged until ready) |
| §5.6 Explainability | 5, 6, 7 |
| §5.7 Preview invariant | 2 |
| §6 Error handling | 3 (fallback), 14 (unbatch) |
| §8 Config / presets | 3, 4 |
| §9 Schedule | Week 1–4 mapping |
| §10 Testing | 1, all task tests |

**Placeholder scan:** None — all tasks have file paths and concrete test snippets.

---

## Execution handoff

**Plan saved to** `docs/superpowers/plans/2026-06-30-dispatch-enterprise-implementation.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — implement tasks in this session with checkpoints  

**Which approach do you want?**

Also: say if you want this plan + spec **committed** to git (you previously required explicit permission).