# Phase 6: ML Demand Predictions + Marketing Automation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Every task is TDD: write the failing test, run it red, implement, run it green, commit. Steps use checkbox (`- [ ]`) syntax for tracking. NO placeholders, NO `pass`-stubs left behind, NO hitting real Meta/Anthropic APIs in tests — ports are overridden with fakes. Each task is self-contained for a zero-context implementer.

**Goal:** Two new bounded contexts.

1. **`predictions/`** — hourly per-dish demand forecasting using a **pure-Python/numpy** baseline (rolling averages + weekday/time-of-day features) behind a swappable `ForecastModel` port (sklearn/LightGBM/prophet can drop in later with NO call-site changes), an LLM context-adjustment layer (manager plain-English overrides), prep-ahead suggestions pushed to the manager via WhatsApp + surfaced on the dashboard, and accuracy tracking (MAPE) with actuals backfilled nightly.
2. **`marketing/`** — campaign + audience-segment model (segments compiled from customer tags/order history), Meta template lifecycle management (datestamped names, approval-status tracking, 30-day name-reuse blackout), a send scheduler enforcing the **UAE 09:00–18:00 window**, the **Meta ~2-marketing-msgs/user/24h cap**, and **STOP-keyword opt-out**, Phase-4 coupon integration, and campaign analytics (sent/delivered/converted).

**Hard constraint (overrides spec §4.6 LightGBM mention):** Phase 6 ships **no heavy ML dependency** (no LightGBM/sklearn/prophet/pandas in `pyproject` deps). The baseline model is hand-rolled numpy. The `ForecastModel` Protocol is the seam so a future phase can `pip install lightgbm` and register `LightGBMForecastModel` without touching services, workers, or routers. numpy is already transitively available; if not, add `numpy>=1.26` to project deps in Task 1.

**Architecture:** Modular monolith conventions (see CLAUDE.md). Two contexts under `src/app/` — `predictions/` and `marketing/`. Within each: `models.py` (SQLAlchemy), `schemas.py` (Pydantic I/O), `service.py` (business logic), `router.py` (HTTP only — calls services, never other modules' models). External integrations behind ports: `predictions/port.py` (`ForecastModel` Protocol; `RollingAverageModel` baseline + `FakeForecastModel` deterministic test double) and `marketing/template_port.py` (`TemplatePort` Protocol; `MockTemplateProvider` for tests/dev + `MetaTemplateProvider` real adapter, chosen by `APP_MARKETING_TEMPLATE_PROVIDER`). LLM adjustment + segment-DSL compilation reuse the existing `llm/` port (new `ForecastAdjuster` + `SegmentCompiler` port methods, Fake + Claude impls). Celery: two new queues — `ml` (nightly forecast + nightly accuracy backfill via Celery Beat) and `marketing` (scheduled campaign sends + template-status polling).

**Spec:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` §3 (data model: `prediction_runs`, `model_registry`, `manager_overrides`, `wa_templates`, `campaigns`, `segments`, `automations`, `recurring_message_state`), §4.6 (Predictions), §4.7 (Marketing automation).

**Compliance source of truth (MANDATORY READ before marketing tasks):** `docs/research/meta-template-compliance.md` and `docs/research/whatsapp-cloud-api-notes.md`. Key enforced constants:
- UAE marketing send window **09:00–18:00 Asia/Dubai** (UAE Cabinet Decision 56/2024).
- Per-user marketing cap **~2 / rolling 24h across all businesses**; over-cap sends fail silently with Meta **error 131049** — we throttle to 2/user/24h locally AND treat 131049 status callbacks as a soft suppression signal.
- Template name **lowercase `^[a-z0-9_]+$`, ≤512 chars**; after delete, **same name unreusable for 30 days** → datestamped unique names (`todays_special_YYYYMMDD` + collision suffix).
- Template create rate **100/WABA/hour**; approval **1–30 min typical, up to 48h**; statuses `PENDING|APPROVED|REJECTED|PAUSED|DISABLED|PENDING_DELETION|ARCHIVED`.
- Body ≤1024 chars, footer ≤60 chars (no emoji/URL/variables), header text ≤60 chars, ≤2 URL buttons, full `https://` only, opt-out (STOP) mechanism mandatory.

**Prerequisites (all merged before Phase 6 starts):** Phase 0–2 (identity, menu AI digitization, WhatsApp core: `whatsapp/port.py`, outbox `enqueue_message`, conversation engine). Phase 3 ordering (`Order`/`OrderItem` FSM, `Customer`/`CustomerAddress`, `customers.usual_order_times`/`tags`/`total_spend`, `order_items` dish snapshots). Phase 4 logistics (`Coupon` model + `coupons/service.py:issue_coupon`, SLA monitor, `sla_events`). Phase 5 dashboard (read-only consumer of the read APIs below — Phase 6 only needs the JSON contracts to line up).

**Ports & infra already present (reuse, do not recreate):**
- `app.config.Settings` (pydantic-settings, `APP_` prefix, `SecretStr` for secrets, `get_settings()` cached).
- `app.outbox.service.enqueue_message(session, *, restaurant_id, to_phone, msg_type, payload, idempotency_key)` — writes outbox row in caller's txn, caller commits.
- `app.whatsapp.port.OutboundMessageType` (`TEXT|BUTTONS|LIST|LOCATION_REQUEST|IMAGE|TEMPLATE`).
- `app.audit.service.record_audit(...)` — append-only, same txn, caller commits.
- `app.identity.deps.current_restaurant` — JWT tenant resolver for routers.
- `app.llm.factory` (`get_describer/get_intent_classifier/get_arbiter`, cached `_get_anthropic_client`).
- `apps.workers.celery_app.celery_app` — Celery instance; `task_routes` + `autodiscover_tasks` pattern.
- `app.coupons.service.issue_coupon(...)` (Phase 4) — reused by campaign coupon integration.

---

## File structure (locked in)

```
src/app/
  predictions/
    __init__.py
    models.py            PredictionRun, ModelRegistry, ManagerOverride tables
    features.py          pure-numpy feature builder: hour/dow/trailing-demand matrix from order history
    port.py              ForecastModel Protocol (fit / predict_dish_hour) + ForecastResult dataclass
    rolling.py           RollingAverageModel — numpy baseline (weekday × hour × dish rolling mean)
    fake.py              FakeForecastModel — deterministic test double (constant per dish)
    factory.py           get_forecast_model() — APP_FORECAST_PROVIDER (rolling|fake; lightgbm later)
    accuracy.py          mape(), backfill_actuals(), score_run() — accuracy math (pure)
    adjust.py            apply_overrides() — merges active ManagerOverride parsed_effect into a run
    service.py           run_forecast(), prep_ahead_suggestions(), create_override(), list/get runs
    router.py            GET /api/v1/predictions/runs, GET /runs/latest, POST /overrides
    schemas.py           PredictionRunOut, DishForecastOut, ManagerOverrideIn/Out, PrepSuggestionOut
    worker.py            Celery tasks: nightly_forecast_all(), nightly_backfill_accuracy()

  marketing/
    __init__.py
    models.py            WaTemplate, Campaign, Segment, MarketingSend, OptOut tables
    template_port.py     TemplatePort Protocol (create/get_status/delete) + TemplateSpec/TemplateStatus
    template_meta.py     MetaTemplateProvider — Graph API adapter (httpx); guarded, never hit in tests
    template_mock.py     MockTemplateProvider — in-memory; auto-approves; for tests/dev
    template_factory.py  get_template_provider() — APP_MARKETING_TEMPLATE_PROVIDER (mock|meta)
    naming.py            datestamped_name(), is_name_reusable() — 30-day blackout + ^[a-z0-9_]+$
    compliance.py        lint_template() — body/footer/header/button/emoji/URL rule checks (pure)
    segments.py          compile_segment(), evaluate_segment() — DSL → SQLAlchemy filter on customers
    window.py            is_within_uae_window(), next_window_open() — 09:00–18:00 Asia/Dubai (pure)
    throttle.py          can_send_marketing() — per-user 2/24h cap + opt-out + DNCR hook (pure-ish)
    optout.py            is_stop_keyword(), record_opt_out(), is_opted_out()
    service.py           create_campaign(), submit_template(), schedule_send(), record_send_status(),
                         convert_attribution(), campaign_stats()
    router.py            POST /campaigns, GET /campaigns, POST /segments, GET /segments/{id}/preview,
                         POST /templates/{id}/submit, GET /campaigns/{id}/stats
    schemas.py           CampaignIn/Out, SegmentIn/Out + preview, TemplateOut, CampaignStatsOut
    worker.py            Celery tasks: scheduled_campaign_tick(), poll_template_statuses(),
                         recurring_promo_tick()

  conversation/
    engine.py            EXTEND: inbound "STOP" keyword → marketing.optout.record_opt_out (any state)

apps/workers/
  celery_app.py          MODIFY: add ml + marketing queues, autodiscover predictions/marketing,
                         beat schedule (nightly_forecast 02:00, backfill 01:30, campaign tick */5,
                         template poll */2, recurring tick hourly) — all Asia/Dubai

app/config.py            MODIFY: add forecast_provider, marketing_template_provider,
                         marketing_window_start_hour/end_hour, marketing_per_user_daily_cap,
                         wa_business_account_id, marketing_send_dry_run

alembic/versions/
  <hash>_prediction_tables.py    prediction_runs, model_registry, manager_overrides
  <hash>_marketing_tables.py     wa_templates, campaigns, segments, marketing_sends, opt_outs

tests/
  predictions/
    __init__.py
    test_features.py        feature matrix shape + trailing-demand correctness
    test_rolling.py         RollingAverageModel weekday×hour mean + cold-start fallback
    test_accuracy.py        mape() + score_run() + backfill_actuals()
    test_adjust.py          apply_overrides() multiplies/sets predicted JSONB
    test_service.py         run_forecast() persists PredictionRun; prep_ahead_suggestions()
    test_router.py          GET runs/latest + POST overrides (tenant-scoped, auth)
    test_worker.py          nightly_forecast_all() smoke (fake model)
  marketing/
    __init__.py
    test_naming.py          datestamped_name format + 30-day reuse blackout
    test_compliance.py      lint_template() catches each rule violation
    test_window.py          UAE window boundaries (08:59 closed / 09:00 open / 18:00 boundary)
    test_throttle.py        2/24h cap + opt-out suppression
    test_optout.py          STOP keyword variants + record/is_opted_out
    test_segments.py        compile + evaluate DSL against seeded customers
    test_template_provider.py  MockTemplateProvider create→approve→delete lifecycle
    test_service.py         create_campaign, submit_template, record_send_status, stats
    test_router.py          campaigns/segments/preview endpoints (tenant-scoped, auth)
    test_worker.py          scheduled_campaign_tick respects window+cap (smoke)
  conversation/
    test_engine_optout.py   inbound STOP from customer → opted out, no further marketing
```

**Migration registration:** every new model module (`app.predictions.models`, `app.marketing.models`) MUST be imported in BOTH `alembic/env.py` AND `tests/conftest.py` to register metadata (project rule). All `TimestampMixin` tables get a `trg_<table>_updated_at` BEFORE UPDATE trigger in their migration. Every tenant table carries `restaurant_id`.

**Task dependency order:** 1 (config+deps) → 2–8 (predictions, mostly independent, 5 depends on 2–4, 6 depends on 5) → 9–17 (marketing) → 18 (conversation STOP wiring) → 19 (Celery wiring) → 20 (full-suite + smoke gate). Predictions and marketing tracks are parallelizable after Task 1.

---

### Task 1: Config additions + numpy dependency + migration skeletons

**Files:**
- Modify: `src/app/config.py`, `pyproject.toml`, `.env.example`
- Modify: `alembic/env.py`, `tests/conftest.py` (register the two new model modules — created in Tasks 2/9, but add the import lines now and create empty `models.py` files so metadata import does not break; flesh out in later tasks)
- Create: `src/app/predictions/__init__.py`, `src/app/predictions/models.py` (empty placeholder — `from app.db import Base  # noqa: F401` only, real tables in Task 2), `src/app/marketing/__init__.py`, `src/app/marketing/models.py` (same placeholder)

**Step 1: Write the failing test**

```python
# tests/predictions/__init__.py  -> empty
# tests/marketing/__init__.py    -> empty
# tests/predictions/test_config.py
from app.config import Settings


def test_forecast_and_marketing_settings_have_safe_defaults():
    s = Settings()
    assert s.forecast_provider == "rolling"
    assert s.marketing_template_provider == "mock"
    assert s.marketing_window_start_hour == 9
    assert s.marketing_window_end_hour == 18
    assert s.marketing_per_user_daily_cap == 2
    assert s.marketing_send_dry_run is True  # never hit Meta unless explicitly disabled
```

Run red: `.venv/bin/pytest tests/predictions/test_config.py -v` → `AttributeError`.

**Step 2: Add settings.** Append to `Settings` in `src/app/config.py` (after the WhatsApp block):

```python
    # Predictions
    forecast_provider: str = "rolling"  # rolling | fake | lightgbm (future)

    # Marketing
    marketing_template_provider: str = "mock"  # mock | meta
    marketing_window_start_hour: int = 9   # Asia/Dubai, UAE Cabinet Decision 56/2024
    marketing_window_end_hour: int = 18
    marketing_per_user_daily_cap: int = 2  # Meta ~2/user/24h across all businesses
    marketing_send_dry_run: bool = True    # True = simulate sends, never call real Meta
    wa_business_account_id: str = ""        # WABA id for Template Management API
```

**Step 3: numpy dep.** In `pyproject.toml` add `"numpy>=1.26"` to `[project].dependencies` (only if not already present — check first; do NOT add lightgbm/sklearn/prophet/pandas). Reinstall: `.venv/bin/pip install -e ".[dev]"`.

**Step 4: `.env.example`** — document the new `APP_` keys with their defaults and a one-line comment each (mirror the settings above; secrets like `wa_business_account_id` left blank).

**Step 5: Placeholder models + registration.** Create `src/app/predictions/models.py` and `src/app/marketing/models.py` each containing only:

```python
from app.db import Base  # noqa: F401
# Tables defined in Task 2 (predictions) / Task 9 (marketing).
```

In `alembic/env.py` AND `tests/conftest.py`, add (alongside the existing model imports):

```python
import app.predictions.models  # noqa: F401
import app.marketing.models  # noqa: F401
```

**Step 6: Run green.** `.venv/bin/pytest tests/predictions/test_config.py -v` → pass. Full suite must still pass (no schema change yet). `.venv/bin/ruff check src apps tests`.

**Step 7: Commit.** `git commit -m "chore: phase-6 config (forecast+marketing settings), numpy dep, model registration"`

---

### Task 2: Prediction tables + migration

**Files:**
- Replace placeholder: `src/app/predictions/models.py`
- Create: `alembic/versions/<hash>_prediction_tables.py`
- Create: `tests/predictions/test_models.py`

Spec §3 `predictions`: `prediction_runs` (restaurant_id, horizon, predicted JSONB, actual JSONB, accuracy), `model_registry` (restaurant_id, model_type, version, trained_at, metrics JSONB), `manager_overrides` (restaurant_id, text, parsed_effect JSONB, active_window, applied_to_runs).

**Step 1: Failing test**

```python
# tests/predictions/test_models.py
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.predictions.models import ManagerOverride, ModelRegistry, PredictionRun


@pytest.mark.asyncio
async def test_prediction_run_roundtrip(db_session, restaurant):
    run = PredictionRun(
        restaurant_id=restaurant.id,
        horizon="lunch",
        target_date=datetime(2026, 6, 7, tzinfo=UTC).date(),
        predicted={"order_count": 42, "revenue": "1260.00",
                   "dish_demand": {"1": 18, "2": 9}, "avg_distance_km": 3.2},
        model_version="rolling-v1",
    )
    db_session.add(run)
    await db_session.flush()
    got = (await db_session.execute(select(PredictionRun))).scalar_one()
    assert got.horizon == "lunch"
    assert got.predicted["dish_demand"]["1"] == 18
    assert got.actual is None and got.accuracy is None  # backfilled later


@pytest.mark.asyncio
async def test_model_registry_and_override(db_session, restaurant):
    db_session.add(ModelRegistry(restaurant_id=restaurant.id, model_type="rolling",
                                 version="1", metrics={"mape": 0.18}))
    db_session.add(ManagerOverride(
        restaurant_id=restaurant.id,
        text="big corporate order Thursday lunch",
        parsed_effect={"horizon": "lunch", "dow": 3, "order_count_delta": 30},
        active_from=datetime(2026, 6, 7, tzinfo=UTC),
        active_to=datetime(2026, 6, 8, tzinfo=UTC),
    ))
    await db_session.flush()
```

Run red: `ModuleNotFoundError`/import error.

**Step 2: Models.** Replace `src/app/predictions/models.py`:

```python
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class PredictionRun(Base, TimestampMixin):
    __tablename__ = "prediction_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    horizon: Mapped[str] = mapped_column(String(16))  # next_1h|breakfast|lunch|dinner|midnight
    target_date: Mapped[date] = mapped_column(Date)
    predicted: Mapped[dict] = mapped_column(JSONB)     # order_count, revenue, dish_demand, avg_distance_km
    actual: Mapped[dict | None] = mapped_column(JSONB, nullable=True)        # backfilled
    accuracy: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)  # 1 - MAPE, 0..1
    model_version: Mapped[str] = mapped_column(String(64))
    adjusted: Mapped[bool] = mapped_column(default=False)  # True if LLM/override applied
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_prediction_runs_rest_date_horizon", "restaurant_id", "target_date", "horizon"),
    )


class ModelRegistry(Base, TimestampMixin):
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    model_type: Mapped[str] = mapped_column(String(32))   # rolling | lightgbm (future)
    version: Mapped[str] = mapped_column(String(64))
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=__import__("sqlalchemy").text("now()"))
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)  # mape, n_samples, etc.


class ManagerOverride(Base, TimestampMixin):
    __tablename__ = "manager_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    text: Mapped[str] = mapped_column(Text)                  # plain English from manager
    parsed_effect: Mapped[dict] = mapped_column(JSONB)       # DSL: {horizon, dow, *_delta, *_mult}
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_to_runs: Mapped[list] = mapped_column(JSONB, default=list)  # run ids the override touched
    enabled: Mapped[bool] = mapped_column(default=True)
```

> Prefer a clean `from sqlalchemy import text` import at top over the inline `__import__` shown above — that inline form is only to keep the snippet copy-paste-safe; the implementer should tidy it.

**Step 3: Migration.** `.venv/bin/alembic revision --autogenerate -m "prediction_tables"`. Verify it creates only the 3 tables (strip any PostGIS `spatial_ref_sys` noise per the Phase-3 alembic caveat). Add BEFORE UPDATE triggers `trg_prediction_runs_updated_at`, `trg_model_registry_updated_at`, `trg_manager_overrides_updated_at` (copy the pattern from the existing `updated_at_triggers` migration). `.venv/bin/alembic upgrade head`.

**Step 4: Run green** `.venv/bin/pytest tests/predictions/test_models.py -v`; `ruff check`.

**Step 5: Commit.** `git commit -m "feat: prediction_runs, model_registry, manager_overrides tables + migration"`

---

### Task 3: Feature builder (pure numpy)

**Files:**
- Create: `src/app/predictions/features.py`
- Create: `tests/predictions/test_features.py`

Builds the feature representation from raw order history. NO DB calls here — `features.py` is pure functions operating on plain Python lists/dicts (the service layer does the querying and hands rows in). This keeps it unit-testable and model-agnostic.

Feature design (spec §4.6 features, minus the heavy ones): `hour` (0–23), `dow` (0–6, Mon=0), `is_weekend`, `trailing demand` per (dish, dow, hour) bucket. Ramadan/holiday/weather flags are accepted as optional passthrough columns (default 0) so a future model can use them without an interface change.

**Step 1: Failing test**

```python
# tests/predictions/test_features.py
from datetime import UTC, datetime

from app.predictions.features import (
    DishHourObservation,
    build_observations,
    trailing_demand,
)


def _ts(y, m, d, h):
    return datetime(y, m, d, h, 0, tzinfo=UTC)


def test_build_observations_buckets_by_dish_dow_hour():
    # two lunch orders for dish 1 on the same Monday hour, one for dish 2
    order_items = [
        {"dish_id": 1, "qty": 2, "ordered_at": _ts(2026, 6, 1, 13)},  # Mon
        {"dish_id": 1, "qty": 1, "ordered_at": _ts(2026, 6, 1, 13)},
        {"dish_id": 2, "qty": 4, "ordered_at": _ts(2026, 6, 1, 13)},
    ]
    obs = build_observations(order_items)
    by_key = {(o.dish_id, o.dow, o.hour): o for o in obs}
    assert by_key[(1, 0, 13)].qty == 3   # Mon=dow 0, summed qty
    assert by_key[(2, 0, 13)].qty == 4
    assert all(isinstance(o, DishHourObservation) for o in obs)


def test_trailing_demand_averages_matching_buckets():
    obs = [
        DishHourObservation(dish_id=1, dow=0, hour=13, qty=3, date=_ts(2026, 6, 1, 13).date()),
        DishHourObservation(dish_id=1, dow=0, hour=13, qty=5, date=_ts(2026, 5, 25, 13).date()),
        DishHourObservation(dish_id=1, dow=0, hour=13, qty=4, date=_ts(2026, 5, 18, 13).date()),
    ]
    # mean of 3,5,4 = 4.0 for Monday 13:00 dish 1
    assert trailing_demand(obs, dish_id=1, dow=0, hour=13) == 4.0
    # unseen bucket → 0.0
    assert trailing_demand(obs, dish_id=1, dow=2, hour=9) == 0.0
```

**Step 2: Implement** `src/app/predictions/features.py`:
- `@dataclass(frozen=True) DishHourObservation(dish_id, dow, hour, qty, date)`.
- `build_observations(order_items: list[dict]) -> list[DishHourObservation]` — group by `(dish_id, date, dow, hour)`, sum `qty`. `dow = ordered_at.weekday()`, `hour = ordered_at.hour`. Use numpy only where it pays off; plain dict aggregation is fine and clearer here — numpy enters in `rolling.py`.
- `trailing_demand(obs, *, dish_id, dow, hour) -> float` — `np.mean` of `qty` across observations matching the bucket; `0.0` if none.
- `feature_vector(dish_id, dow, hour, *, is_ramadan=0, is_holiday=0, weather_bad=0) -> np.ndarray` — returns `[hour, dow, is_weekend, is_ramadan, is_holiday, weather_bad]` (is_weekend: Fri/Sat=1 for UAE → dow in {4,5}). Document the column order in a module constant `FEATURE_COLUMNS`.

**Step 3: Run green; ruff.**

**Step 4: Commit.** `git commit -m "feat: predictions feature builder (pure numpy observations + trailing demand)"`

---

### Task 4: ForecastModel port + RollingAverageModel + FakeForecastModel + factory

**Files:**
- Create: `src/app/predictions/port.py`, `src/app/predictions/rolling.py`, `src/app/predictions/fake.py`, `src/app/predictions/factory.py`
- Create: `tests/predictions/test_rolling.py`, `tests/predictions/test_port.py`

This is the **swap seam**. The Protocol is intentionally narrow so `LightGBMForecastModel` can implement it later with `pip install lightgbm` and ZERO call-site changes.

**Step 1: Failing tests**

```python
# tests/predictions/test_rolling.py
from datetime import UTC, datetime

from app.predictions.features import build_observations
from app.predictions.rolling import RollingAverageModel


def _ts(y, m, d, h):
    return datetime(y, m, d, h, 0, tzinfo=UTC)


def test_rolling_predicts_weekday_hour_mean_per_dish():
    items = [
        {"dish_id": 1, "qty": 3, "ordered_at": _ts(2026, 5, 4, 13)},   # Mon
        {"dish_id": 1, "qty": 5, "ordered_at": _ts(2026, 5, 11, 13)},  # Mon
        {"dish_id": 1, "qty": 4, "ordered_at": _ts(2026, 5, 18, 13)},  # Mon
    ]
    model = RollingAverageModel()
    model.fit(build_observations(items))
    pred = model.predict_dish_hour(dish_id=1, dow=0, hour=13)
    assert pred.expected_qty == 4.0  # mean(3,5,4)
    assert pred.model_version.startswith("rolling-")


def test_rolling_cold_start_falls_back_to_global_dish_mean():
    items = [{"dish_id": 1, "qty": 10, "ordered_at": _ts(2026, 5, 4, 19)}]  # only Mon 19:00
    model = RollingAverageModel()
    model.fit(build_observations(items))
    # unseen (Tue 09:00) bucket → fall back to dish's overall mean (10), not 0
    pred = model.predict_dish_hour(dish_id=1, dow=1, hour=9)
    assert pred.expected_qty == 10.0
    # unseen dish entirely → 0.0
    assert model.predict_dish_hour(dish_id=99, dow=1, hour=9).expected_qty == 0.0
```

```python
# tests/predictions/test_port.py
from app.predictions.factory import get_forecast_model
from app.predictions.fake import FakeForecastModel
from app.predictions.rolling import RollingAverageModel


def test_factory_returns_rolling_by_default(monkeypatch):
    from app.config import get_settings
    get_settings.cache_clear()
    assert isinstance(get_forecast_model(), RollingAverageModel)


def test_factory_fake_provider(monkeypatch):
    monkeypatch.setenv("APP_FORECAST_PROVIDER", "fake")
    from app.config import get_settings
    get_settings.cache_clear()
    assert isinstance(get_forecast_model(), FakeForecastModel)
    get_settings.cache_clear()


def test_fake_is_deterministic():
    m = FakeForecastModel(constant=7.0)
    m.fit([])
    assert m.predict_dish_hour(dish_id=1, dow=0, hour=12).expected_qty == 7.0
```

**Step 2: `port.py`**

```python
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.predictions.features import DishHourObservation


@dataclass(frozen=True)
class DishHourForecast:
    dish_id: int
    dow: int
    hour: int
    expected_qty: float
    model_version: str


@runtime_checkable
class ForecastModel(Protocol):
    """Swap seam: RollingAverageModel today; LightGBM/sklearn/prophet later, no call-site change."""

    def fit(self, observations: list[DishHourObservation]) -> None: ...

    def predict_dish_hour(self, *, dish_id: int, dow: int, hour: int) -> DishHourForecast: ...
```

**Step 3: `rolling.py`** — numpy implementation:
- `fit`: build two dicts — `bucket_mean[(dish, dow, hour)] = np.mean(qtys)` and `dish_mean[dish] = np.mean(all qtys for that dish)`. Store `self._fitted_at` for the version string `f"rolling-{date.isoformat()}"`.
- `predict_dish_hour`: return `bucket_mean` if present, else `dish_mean.get(dish, 0.0)` (cold-start fallback), wrapped in `DishHourForecast`.
- Pure numpy for the means; no pandas.

**Step 4: `fake.py`** — `FakeForecastModel(constant=0.0)`: `fit` no-op, `predict_dish_hour` returns `DishHourForecast(..., expected_qty=self.constant, model_version="fake-1")`. Deterministic; used in service/worker/router tests.

**Step 5: `factory.py`**

```python
from functools import lru_cache

from app.config import get_settings
from app.predictions.port import ForecastModel


@lru_cache
def get_forecast_model() -> ForecastModel:
    provider = get_settings().forecast_provider
    if provider == "rolling":
        from app.predictions.rolling import RollingAverageModel
        return RollingAverageModel()
    if provider == "fake":
        from app.predictions.fake import FakeForecastModel
        return FakeForecastModel()
    raise ValueError(f"Unknown forecast_provider: {provider!r}")
```

> NOTE: `@lru_cache` returns a singleton instance — `fit()` mutates it. The service must call `get_forecast_model.cache_clear()` (or instantiate the class directly via the factory's branch) before each nightly fit to avoid stale state across restaurants. Document this in the service docstring (Task 6). Simpler: the factory caches the *class choice*; have the service construct a fresh model per restaurant. Implementer's call — but tests above expect `get_forecast_model()` to return an instance, so keep the instance form and have the service create fresh instances per-restaurant in the worker loop, using the factory only to resolve which class.

**Step 6: Run green; ruff. Commit.** `git commit -m "feat: ForecastModel port + RollingAverageModel (numpy) + FakeForecastModel + factory"`

---

### Task 5: Accuracy math (MAPE, scoring, actuals backfill)

**Files:**
- Create: `src/app/predictions/accuracy.py`
- Create: `tests/predictions/test_accuracy.py`

Pure functions — no DB. The service/worker (Task 6) queries actual order counts and calls these.

**Step 1: Failing test**

```python
# tests/predictions/test_accuracy.py
import math

from app.predictions.accuracy import mape, accuracy_from_mape, score_prediction


def test_mape_basic():
    # predicted 100, actual 80 → APE 0.25
    assert math.isclose(mape([100], [80]), 0.25)
    # multiple points averaged
    assert math.isclose(mape([10, 20], [12, 18]), (0.2 + 0.1) / 2, rel_tol=1e-9)


def test_mape_skips_zero_actuals():
    # actual 0 would divide-by-zero → skipped; only the 100/80 pair counts
    assert math.isclose(mape([100, 5], [80, 0]), 0.25)


def test_accuracy_from_mape_clamped():
    assert accuracy_from_mape(0.18) == 0.82
    assert accuracy_from_mape(1.5) == 0.0   # never negative


def test_score_prediction_reads_order_count():
    predicted = {"order_count": 50, "revenue": "1500.00"}
    actual = {"order_count": 40, "revenue": "1300.00"}
    acc = score_prediction(predicted, actual)
    # uses order_count primary metric: APE = |50-40|/40 = 0.25 → accuracy 0.75
    assert math.isclose(acc, 0.75)
```

**Step 2: Implement** `accuracy.py`:
- `mape(predicted: list[float], actual: list[float]) -> float` — mean of `|p-a|/a` over pairs where `a != 0`; returns `0.0` if no valid pairs.
- `accuracy_from_mape(m: float) -> float` — `max(0.0, 1.0 - m)`.
- `score_prediction(predicted: dict, actual: dict) -> float` — APE on `order_count` (primary), returns `accuracy_from_mape`. (Dish-level multi-point MAPE is a follow-up; keep the single primary metric for run.accuracy now and store dish detail in JSONB.)

**Step 3: Run green; ruff. Commit.** `git commit -m "feat: predictions accuracy math (MAPE, accuracy, score_prediction)"`

---

### Task 6: Manager-override adjustment layer + LLM ForecastAdjuster port

**Files:**
- Create: `src/app/predictions/adjust.py`
- Modify: `src/app/llm/port.py` (add `ForecastAdjusterPort` Protocol), `src/app/llm/fake.py` (add `FakeForecastAdjuster`), `src/app/llm/claude.py` (add `ClaudeForecastAdjuster`), `src/app/llm/factory.py` (add `get_forecast_adjuster()`)
- Create: `tests/predictions/test_adjust.py`

Two layers per spec §4.6: (1) deterministic `apply_overrides()` merges any active `ManagerOverride.parsed_effect` into a predicted dict (pure); (2) the LLM `ForecastAdjuster` turns a manager's *plain-English* override text into a structured `parsed_effect` DSL — Fake is rule-based (no network), Claude calls haiku. The DSL is the same shape stored on `ManagerOverride.parsed_effect`.

`parsed_effect` DSL shape (validated): `{"horizon": "lunch"|null, "dow": 0-6|null, "order_count_delta": int, "order_count_mult": float, "revenue_mult": float, "dish_demand_delta": {dish_id: int}}` — all keys optional, deltas default 0, mults default 1.0.

**Step 1: Failing test**

```python
# tests/predictions/test_adjust.py
from app.llm.fake import FakeForecastAdjuster
from app.predictions.adjust import apply_overrides


def test_apply_overrides_delta_and_mult():
    predicted = {"order_count": 40, "revenue": "1200.00", "dish_demand": {"1": 10}}
    effects = [
        {"order_count_delta": 30, "dish_demand_delta": {"1": 5}},
        {"order_count_mult": 1.0, "revenue_mult": 1.5},
    ]
    out, reasoning = apply_overrides(predicted, effects)
    assert out["order_count"] == 70           # 40 + 30
    assert out["dish_demand"]["1"] == 15       # 10 + 5
    assert out["revenue"] == "1800.00"         # 1200 * 1.5, 2dp Decimal string
    assert "override" in reasoning.lower()


def test_apply_overrides_noop_when_empty():
    predicted = {"order_count": 40, "revenue": "1200.00", "dish_demand": {}}
    out, reasoning = apply_overrides(predicted, [])
    assert out == predicted
    assert reasoning == ""


def test_fake_adjuster_parses_corporate_order_text():
    adj = FakeForecastAdjuster()
    effect = adj.parse_override("big corporate order Thursday lunch, expect 30 extra")
    assert effect["dow"] == 3            # Thursday
    assert effect["horizon"] == "lunch"
    assert effect["order_count_delta"] == 30
```

**Step 2: `adjust.py`** — `apply_overrides(predicted: dict, effects: list[dict]) -> tuple[dict, str]`:
- deep-copy predicted; for each effect apply deltas then mults; money handled with `Decimal` quantized to 2dp returned as string; `dish_demand_delta` merges per dish_id key.
- build a human reasoning string listing applied effects (empty string when no effects).

**Step 3: LLM port additions.** In `llm/port.py`:

```python
class ForecastAdjusterPort(Protocol):
    def parse_override(self, text: str) -> dict:
        """Plain-English manager override -> parsed_effect DSL dict (see adjust.py shape)."""
        ...
```

`FakeForecastAdjuster.parse_override` (rule-based, no network): lowercase scan — weekday words → `dow`; {breakfast,lunch,dinner,midnight,morning,evening} → `horizon`; first integer near "extra"/"more"/"order" → `order_count_delta`; "double"/"twice" → `order_count_mult=2.0`. Return `{}` if nothing matched. `ClaudeForecastAdjuster.parse_override` calls `_get_anthropic_client()` with a JSON-only prompt returning the DSL; wrap parse errors → return `{}` (never raise into the forecast pipeline). `get_forecast_adjuster()` in `llm/factory.py` mirrors `get_describer()` (claude vs fake).

**Step 4: Run green; ruff. Commit.** `git commit -m "feat: forecast override DSL apply_overrides + LLM ForecastAdjuster (fake+claude)"`

---

### Task 7: Predictions service — run_forecast, prep-ahead suggestions, overrides, queries

**Files:**
- Create: `src/app/predictions/service.py`
- Create: `tests/predictions/test_service.py`

This is where DB meets model. The worker (Task 8) calls `run_forecast`; the router (Task 8) calls the query/override functions.

**Functions:**
- `async run_forecast(session, *, restaurant_id, target_date, horizon, model) -> PredictionRun` — query the trailing N (default 28) days of `order_items` joined to `orders` (status in delivered/confirmed-and-beyond, this restaurant) with their `ordered_at`; `build_observations`; `model.fit(obs)`; for the hours in the horizon window (mapping: `breakfast`=6–10, `lunch`=11–15, `dinner`=18–22, `midnight`=23–2, `next_1h`= next clock hour) sum `predict_dish_hour` across active dishes → `dish_demand` + `order_count` (sum of per-dish expected, rounded) + `revenue` (Σ qty×dish price, Decimal) + `avg_distance_km` (mean of trailing order distances). Apply active `ManagerOverride`s (those whose `[active_from,active_to)` covers target_date and matching horizon/dow) via `apply_overrides`; set `adjusted`/`reasoning`. Persist `PredictionRun` (predicted JSONB, model_version). `record_audit`. Caller commits. Upsert a `ModelRegistry` row with the fitted version + metrics.
- `async prep_ahead_suggestions(session, *, restaurant_id, run) -> list[dict]` — from a run's `dish_demand`, return top-K dishes (default 5) with expected qty ≥ threshold (default 3), each `{dish_id, dish_name, expected_qty, suggested_prep}` where `suggested_prep = ceil(expected_qty)`. Pure read.
- `async create_override(session, *, restaurant_id, text, adjuster, active_from, active_to) -> ManagerOverride` — `adjuster.parse_override(text)` → validate DSL keys → persist `ManagerOverride`. `record_audit`. Caller commits.
- `async latest_run(session, *, restaurant_id, horizon=None) -> PredictionRun | None` and `async list_runs(session, *, restaurant_id, limit=20)` — tenant-scoped, order by `target_date desc, created_at desc`.

**Step 1: Failing test** (uses `FakeForecastModel` so output is deterministic): seed a restaurant + 2 dishes + a handful of delivered orders/order_items across two Mondays; call `run_forecast` with `FakeForecastModel(constant=4.0)` for `horizon="lunch"`; assert a `PredictionRun` row is persisted, `predicted["dish_demand"]` has both dishes, `order_count` > 0, and `model_version == "fake-1"`. Then seed an active `ManagerOverride(order_count_delta=10)` and assert a re-run sets `adjusted=True` and bumps `order_count`. Test `prep_ahead_suggestions` returns the dish names + `suggested_prep`. (Use the per-restaurant fresh-model construction pattern noted in Task 4 Step 5.)

**Step 2: Implement** per the function contracts above. Reuse `app.menu.models.Dish` for names/prices (query via service — router never touches it). Money via `Decimal`/`Numeric(8,2)`.

**Step 3: Run green; ruff. Commit.** `git commit -m "feat: predictions service (run_forecast, prep-ahead, overrides, queries)"`

---

### Task 8: Predictions router + schemas + nightly Celery workers

**Files:**
- Create: `src/app/predictions/schemas.py`, `src/app/predictions/router.py`, `src/app/predictions/worker.py`
- Modify: `src/app/main.py` (mount `predictions_router`)
- Create: `tests/predictions/test_router.py`, `tests/predictions/test_worker.py`

**Schemas** (`ConfigDict(from_attributes=True)`): `DishForecastOut(dish_id, dish_name, expected_qty, suggested_prep)`, `PredictionRunOut(id, horizon, target_date, predicted, actual, accuracy, model_version, adjusted, reasoning, created_at)`, `PrepSuggestionOut(...)`, `ManagerOverrideIn(text, active_from, active_to)`, `ManagerOverrideOut(id, text, parsed_effect, active_from, active_to, enabled)`.

**Router** (`prefix="/api/v1/predictions"`, `tags=["predictions"]`, `Depends(current_restaurant)` everywhere; tenant-scope via `current_restaurant.id`):
- `GET /runs?horizon=&limit=` → `list_runs` → `list[PredictionRunOut]`.
- `GET /runs/latest?horizon=` → `latest_run` → `PredictionRunOut` or 404.
- `GET /runs/{run_id}/prep-ahead` → load run (tenant-scoped, 404), `prep_ahead_suggestions` → `list[PrepSuggestionOut]`.
- `POST /overrides` → `create_override` (parse via `get_forecast_adjuster()` dep) → commit → `ManagerOverrideOut`.

Mount in `main.py` (import + `include_router`, minimal).

**Worker** (`src/app/predictions/worker.py`) — uses `@shared_task` and imports `apps.workers.celery_app` so tasks bind to the redis broker (the Phase-2 wiring lesson; otherwise falls back to amqp → connection refused):
- `nightly_forecast_all()` — for each restaurant: open an async session (sync Celery task → run the async service via `asyncio.run` or the project's existing async-in-celery helper — match whatever Phase 4 workers use; if Phase 4 established a pattern, reuse it), construct a fresh forecast model per restaurant (factory resolves class), run `run_forecast` for each horizon for tomorrow's date, commit, and enqueue a manager prep-ahead WhatsApp summary via `enqueue_message` (a single TEXT listing top prep dishes; only if there are suggestions). Idempotent: skip if a run for (restaurant, target_date, horizon) already exists for this model_version today.
- `nightly_backfill_accuracy()` — for runs whose `target_date` is now in the past and `actual is None`: query real `order_count`/revenue for that date+horizon, set `actual` + `accuracy = score_prediction(...)`, commit. Feeds the MAPE dashboard.

**Step 1: Failing tests.**
- `test_router.py`: seed restaurant + a `PredictionRun`; with auth headers, `GET /runs/latest` returns 200 + the run; `POST /overrides` with `{"text": "double orders Friday dinner", ...}` returns 201/200 + persisted override with non-empty `parsed_effect`; cross-tenant run returns 404.
- `test_worker.py`: monkeypatch `APP_FORECAST_PROVIDER=fake`; seed minimal order history; call `nightly_forecast_all()` (synchronously, in-process — it should not require a live broker, just the DB); assert ≥1 `PredictionRun` persisted and a prep-ahead outbox row enqueued.

**Step 2: Implement. Step 3: Run green; ruff.**

**Step 4: Commit.** `git commit -m "feat: predictions router + schemas + nightly forecast/backfill Celery workers"`

---

## Marketing track (Tasks 9–17)

> READ `docs/research/meta-template-compliance.md` + `docs/research/whatsapp-cloud-api-notes.md` before starting. The constraints in the plan header are non-negotiable and enforced in code + tests.

### Task 9: Marketing tables + migration

**Files:**
- Replace placeholder: `src/app/marketing/models.py`
- Create: `alembic/versions/<hash>_marketing_tables.py`
- Create: `tests/marketing/test_models.py`

Spec §3 `marketing`. Tables: `wa_templates`, `campaigns`, `segments`, plus operational `marketing_sends` (per-recipient send ledger for cap + analytics) and `opt_outs` (STOP list). (`automations` + `recurring_message_state` are scoped to recurring promos — `recurring_message_state` is added in Task 17; full `automations` DSL deferred — note in post-phase.)

**Models** (all `TimestampMixin`, all `restaurant_id`):

```python
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class WaTemplate(Base, TimestampMixin):
    __tablename__ = "wa_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    meta_template_name: Mapped[str] = mapped_column(String(512))   # datestamped, ^[a-z0-9_]+$
    language: Mapped[str] = mapped_column(String(8), default="en")
    category: Mapped[str] = mapped_column(String(16), default="marketing")
    header: Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # {format, text|image_url}
    body: Mapped[str] = mapped_column(Text)
    footer: Mapped[str | None] = mapped_column(String(60), nullable=True)
    buttons: Mapped[list] = mapped_column(JSONB, default=list)
    # draft|pending_meta|approved|rejected|paused|disabled|sent|deleted
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    ephemeral: Mapped[bool] = mapped_column(default=True)   # daily specials auto-delete EOD
    meta_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("restaurant_id", "meta_template_name", "language",
                         name="uq_wa_template_name_lang"),
    )


class Segment(Base, TimestampMixin):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    plain_english: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[dict] = mapped_column(JSONB)   # validated DSL
    last_preview_count: Mapped[int | None] = mapped_column(nullable=True)


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))    # todays_special|recurring|automation
    template_id: Mapped[int | None] = mapped_column(ForeignKey("wa_templates.id"), nullable=True)
    segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id"), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    coupon_value: Mapped[str | None] = mapped_column(String(16), nullable=True)  # optional promo coupon
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # draft|scheduled|sending|sent|failed|cancelled
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)  # sent/delivered/read/converted counts


class MarketingSend(Base, TimestampMixin):
    __tablename__ = "marketing_sends"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    to_phone: Mapped[str] = mapped_column(String(32), index=True)
    # queued|sent|delivered|read|failed|suppressed_cap|suppressed_optout|suppressed_window
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    wa_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[int | None] = mapped_column(nullable=True)   # e.g. 131049
    converted_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True)   # attribution
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("campaign_id", "customer_id", name="uq_marketing_send_campaign_customer"),
        Index("ix_marketing_sends_phone_sent", "to_phone", "sent_at"),  # 24h cap lookups
    )


class OptOut(Base, TimestampMixin):
    __tablename__ = "opt_outs"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(16), default="stop_keyword")  # stop_keyword|manual|dncr
    __table_args__ = (
        UniqueConstraint("restaurant_id", "phone", name="uq_opt_out_restaurant_phone"),
    )
```

**Migration:** autogenerate, strip PostGIS noise, add `trg_<table>_updated_at` BEFORE UPDATE triggers for all five tables, `upgrade head`.

**Step 1: Failing test** — roundtrip each model; assert the two unique constraints fire (duplicate `(restaurant_id, meta_template_name, language)` and duplicate `(campaign_id, customer_id)` both raise `IntegrityError`). **Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: marketing tables (wa_templates, segments, campaigns, marketing_sends, opt_outs) + migration"`

---

### Task 10: Template naming (datestamped + 30-day blackout) + compliance linter

**Files:**
- Create: `src/app/marketing/naming.py`, `src/app/marketing/compliance.py`
- Create: `tests/marketing/test_naming.py`, `tests/marketing/test_compliance.py`

Both pure functions (no DB) — `naming.is_name_reusable` takes the deleted-name history as an argument so it stays unit-testable; the service passes DB rows in.

**naming.py:**
- `datestamped_name(prefix: str, *, on: date, suffix: int = 0) -> str` → `f"{prefix}_{on:%Y%m%d}"` + (`f"_{suffix}"` if suffix). Lowercase the prefix, replace non-`[a-z0-9_]` with `_`, collapse repeats, enforce `^[a-z0-9_]+$` and ≤512 chars (raise `ValueError` otherwise).
- `is_name_reusable(name: str, deleted_history: list[tuple[str, datetime]], *, now: datetime) -> bool` → False if `name` appears in history with `deleted_at` within the last **30 days**; True otherwise.
- `next_available_name(prefix, *, on, deleted_history, existing_names, now) -> str` → loop suffix 0,1,2… until a name is both reusable AND not in `existing_names`.

**compliance.py** — `lint_template(spec: dict) -> list[str]` returns a list of violation strings (empty = compliant). Enforce (from compliance doc §3 + §6):
- name matches `^[a-z0-9_]+$`, ≤512 chars.
- body present, ≤1024 chars; ≤5 lines recommended (warn if >5); no >2 consecutive newlines; no shortened-URL hosts (`bit.ly`,`tinyurl`,`t.co`,`goo.gl`); any URL must be `https://`.
- footer (if present) ≤60 chars, no emoji, no URL, no `{{`.
- header text (if present) ≤60 chars, no emoji, no newline.
- buttons: ≤10 total, ≤2 URL buttons, each label ≤25 chars, URL buttons full `https://`; at least one opt-out mechanism present (a QUICK_REPLY labelled stop/unsubscribe OR footer containing "STOP") → else violation `"missing opt-out mechanism"`.
- variables sequential `{{1}}..{{n}}` no gaps/repeats; not adjacent (`{{1}} {{2}}` with no static text between flagged); body must have static text (not mostly variables).
- emoji detection helper (regex over emoji unicode ranges) used for footer/header.

**Step 1: Failing tests** — `test_naming.py`: format correctness, suffix collision, 30-day blackout boundary (29 days ago → not reusable, 31 days → reusable). `test_compliance.py`: one assertion per rule — a clean spec returns `[]`; a spec with a `bit.ly` link, a 70-char footer, an emoji footer, an adjacent-variable body, 3 URL buttons, and a missing opt-out each yields the matching violation string.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: marketing template naming (datestamp + 30d blackout) + compliance linter"`

---

### Task 11: UAE send window + per-user 2/24h throttle

**Files:**
- Create: `src/app/marketing/window.py`, `src/app/marketing/throttle.py`
- Create: `tests/marketing/test_window.py`, `tests/marketing/test_throttle.py`

**window.py** (pure; uses `zoneinfo.ZoneInfo("Asia/Dubai")`, window hours come from settings so they're configurable):
- `is_within_uae_window(now_utc: datetime, *, start_hour=9, end_hour=18) -> bool` — convert to Asia/Dubai, True iff `start_hour <= local.hour < end_hour`.
- `next_window_open(now_utc: datetime, *, start_hour=9, end_hour=18) -> datetime` — next UTC instant at which the window opens (today if before start, else tomorrow start), returned in UTC.

**throttle.py** — `can_send_marketing(...)` decides per-recipient eligibility. Signature takes already-fetched facts (keeps it pure + unit-testable; the service does the DB queries):

```python
@dataclass(frozen=True)
class SendDecision:
    allowed: bool
    reason: str  # "" if allowed; else suppressed_window|suppressed_optout|suppressed_cap

def can_send_marketing(
    *, now_utc, sends_last_24h: int, opted_out: bool,
    within_window: bool, per_user_cap: int = 2,
) -> SendDecision: ...
```

Order of checks: opt-out → window → cap. Returns the first failing reason; `allowed=True` only if all pass.

**Step 1: Failing tests.**
- `test_window.py`: 08:59 Dubai → False; 09:00 → True; 17:59 → True; 18:00 → False; verify a UTC instant that is 09:30 Dubai (UTC+4 → 05:30 UTC) returns True. `next_window_open` from 20:00 Dubai → next day 09:00 Dubai in UTC.
- `test_throttle.py`: opted_out=True → suppressed_optout regardless; outside window → suppressed_window; `sends_last_24h=2, cap=2` → suppressed_cap; `sends_last_24h=1, cap=2`, in window, not opted out → allowed.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: UAE marketing send window + per-user 2/24h throttle (pure)"`

---

### Task 12: Opt-out (STOP keyword) primitives

**Files:**
- Create: `src/app/marketing/optout.py`
- Create: `tests/marketing/test_optout.py`

**optout.py:**
- `is_stop_keyword(text: str) -> bool` — case-insensitive, trimmed; matches `{"stop","unsubscribe","opt out","optout","stop promo","cancel"}` (and Arabic `"الغاء"`/`"توقف"` as a nice-to-have; English mandatory). Single-word exact or whole-message match (so "stop sending the biryani" still triggers — be lenient: any message whose stripped lowercase **equals** a keyword OR **starts with** "stop"/"unsubscribe").
- `async record_opt_out(session, *, restaurant_id, phone, source="stop_keyword") -> OptOut` — upsert `OptOut` (idempotent on `(restaurant_id, phone)` unique constraint — catch `IntegrityError`/use `ON CONFLICT DO NOTHING`); `record_audit`. Caller commits.
- `async is_opted_out(session, *, restaurant_id, phone) -> bool` — exists-query.

**Step 1: Failing test** — keyword matrix (`"STOP"`, `" stop "`, `"Unsubscribe"`, `"stop sending"` → True; `"stomp"`, `"please continue"` → False); `record_opt_out` then `is_opted_out` returns True; calling `record_opt_out` twice does not raise.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: marketing opt-out STOP keyword detection + record/is_opted_out"`

---

### Task 13: Audience segments — DSL compile + evaluate + LLM SegmentCompiler

**Files:**
- Create: `src/app/marketing/segments.py`
- Modify: `src/app/llm/port.py` (`SegmentCompilerPort`), `src/app/llm/fake.py` (`FakeSegmentCompiler`), `src/app/llm/claude.py` (`ClaudeSegmentCompiler`), `src/app/llm/factory.py` (`get_segment_compiler()`)
- Create: `tests/marketing/test_segments.py`

Segments are built from customer **tags/order history** (spec §4.7). Define a small **validated DSL** (NO arbitrary SQL/eval — security): a JSON tree of conditions translated to SQLAlchemy filters on `Customer` (+ aggregated order history).

DSL grammar (validated against an allowlist of fields/ops):
```json
{"all": [
  {"field": "total_spend", "op": "gte", "value": 200},
  {"field": "tag", "op": "contains", "value": "vip"},
  {"field": "order_count", "op": "gte", "value": 3},
  {"field": "last_order_days_ago", "op": "lte", "value": 30},
  {"field": "ordered_dish_id", "op": "eq", "value": 1, "min_count": 3}
]}
```
Top-level `all` (AND) / `any` (OR). Allowed fields: `total_spend, order_count, last_order_days_ago, tag, ordered_dish_id`. Allowed ops per field. Any unknown field/op → `ValueError` (reject, never execute).

**segments.py:**
- `validate_dsl(dsl: dict) -> None` — raises `ValueError` on any unknown field/op/structure.
- `async compile_segment(dsl: dict) -> ...` — returns a reusable SQLAlchemy `select(Customer.id).where(...)` builder scoped later by restaurant. Aggregates (`order_count`, `last_order_days_ago`, `ordered_dish_id ... min_count`) implemented via correlated subqueries / `EXISTS` against `orders`/`order_items` — NOT raw SQL string interpolation.
- `async evaluate_segment(session, *, restaurant_id, dsl) -> list[int]` — validate, compile, run scoped to restaurant, return matching `customer_id`s.
- `async preview_count(session, *, restaurant_id, dsl) -> int` — `len` of evaluate (or a `count()` query).

**LLM port:** `SegmentCompilerPort.compile(text: str) -> dict` (plain English → DSL). `FakeSegmentCompiler` rule-based: scans for "spend"/"aed" + number → `total_spend gte`; "ordered X N+ times" → `ordered_dish_id ... min_count` (X resolved by caller/service to dish_id; Fake may emit `{"field":"tag","op":"contains","value":<word>}` as a simple stand-in and the service validates); "last 30 days" → `last_order_days_ago lte 30`; "vip"/tag words → tag contains. `ClaudeSegmentCompiler.compile` calls haiku with a JSON-only DSL prompt, then `validate_dsl` (reject + raise on invalid — manager sees the error, no unsafe execution). `get_segment_compiler()` in factory.

**Step 1: Failing test** — seed restaurant + 3 customers with varying `total_spend`/`tags` + a couple of orders; `evaluate_segment` with `{"all":[{"field":"total_spend","op":"gte","value":200}]}` returns only the matching ids; `validate_dsl({"all":[{"field":"DROP","op":"eq","value":1}]})` raises `ValueError`; `FakeSegmentCompiler().compile("customers who spent over 200 aed")` yields a DSL that validates.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: audience segment DSL (validated compile/evaluate) + LLM SegmentCompiler"`

---

### Task 14: Template provider port — Mock + Meta adapter + factory

**Files:**
- Create: `src/app/marketing/template_port.py`, `src/app/marketing/template_mock.py`, `src/app/marketing/template_meta.py`, `src/app/marketing/template_factory.py`
- Create: `tests/marketing/test_template_provider.py`

**template_port.py:**
```python
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class TemplateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"
    DISABLED = "disabled"
    DELETED = "deleted"


@dataclass
class TemplateSpec:
    name: str
    language: str
    category: str           # "marketing"
    body: str
    header: dict | None = None
    footer: str | None = None
    buttons: list = field(default_factory=list)


@dataclass
class TemplateCreateResult:
    meta_template_id: str
    status: TemplateStatus
    rejection_reason: str | None = None


class TemplatePort(Protocol):
    async def create(self, spec: TemplateSpec) -> TemplateCreateResult: ...
    async def get_status(self, meta_template_id: str) -> TemplateCreateResult: ...
    async def delete(self, *, name: str, meta_template_id: str | None = None) -> bool: ...
```

**template_mock.py** — `MockTemplateProvider`: in-memory dict keyed by generated id; `create` runs `compliance.lint_template` and returns `REJECTED` (with the first violation as reason) if non-empty, else `APPROVED` immediately (deterministic; lets the full pipeline run in tests/dev with no network). `delete` marks deleted. Used whenever `marketing_send_dry_run` or `marketing_template_provider == "mock"`.

**template_meta.py** — `MetaTemplateProvider` (real Graph API, `httpx.AsyncClient`): `create` → `POST /{waba_id}/message_templates` with the components payload (see whatsapp-cloud-api-notes §5.1; image header via resumable-upload handle — stub the upload to accept a pre-uploaded `header_handle` for now and TODO the resumable flow); `get_status` → `GET /{waba_id}/message_templates?name=`; `delete` → `DELETE /{waba_id}/message_templates?name=`. Reads `wa_access_token`/`wa_business_account_id` from settings. **Guard:** constructor raises if `marketing_send_dry_run is True` — this provider must never be instantiated in tests; tests always use the mock.

**template_factory.py** — `get_template_provider()`: returns `MockTemplateProvider` when `marketing_template_provider == "mock"` OR `marketing_send_dry_run`; else `MetaTemplateProvider`. FastAPI/worker dependency.

**Step 1: Failing test** — `MockTemplateProvider`: a compliant `TemplateSpec` → `create` returns `APPROVED` + an id; `get_status(id)` returns `APPROVED`; `delete(name=...)` returns True. A spec with a `bit.ly` body → `create` returns `REJECTED` with a non-empty reason. Factory returns the mock under default (dry_run) settings.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: TemplatePort (Mock auto-approve + Meta adapter stub) + factory"`

---

### Task 15: Marketing service — campaigns, template submission, scheduled send, status, analytics

**Files:**
- Create: `src/app/marketing/service.py`
- Create: `tests/marketing/test_service.py`

The orchestration layer. Pulls together segments, templates, throttle, window, opt-out, outbox, coupons. All functions take `session`, are tenant-scoped, `record_audit`, caller commits.

**Functions:**
- `async create_segment(session, *, restaurant_id, name, dsl, plain_english=None) -> Segment` — `validate_dsl`, persist, store `last_preview_count = await preview_count(...)`.
- `async create_campaign(session, *, restaurant_id, type, template_id=None, segment_id=None, image_url=None, coupon_value=None, scheduled_at=None) -> Campaign` — validate refs belong to restaurant; status `draft` (or `scheduled` if `scheduled_at`).
- `async submit_template(session, *, restaurant_id, wa_template_id, provider) -> WaTemplate` — load template, run `lint_template` (raise `ValueError` with violations if any — manager fixes), assign a `next_available_name` (datestamped, blackout-checked against deleted `wa_templates` history for this restaurant), `provider.create(spec)` → store `meta_template_id` + `status` (pending/approved/rejected + reason). `record_audit`.
- `async run_campaign_send(session, *, campaign, provider, now_utc) -> dict` — the **core compliant send**. Steps:
  1. Guard: campaign template `status == approved`; else raise/skip.
  2. Resolve audience: `evaluate_segment` (or all opted-in customers if no segment).
  3. For each customer: fetch `sends_last_24h` (count `MarketingSend` by `to_phone` with `sent_at >= now-24h` across ALL campaigns this restaurant), `opted_out` (`is_opted_out`), `within_window` (`is_within_uae_window(now_utc, start, end)`). `can_send_marketing(...)`.
  4. If allowed: `enqueue_message(msg_type=TEMPLATE, payload={template_name, language, components, optional image header, STOP quick-reply})` + insert `MarketingSend(status="sent", sent_at=now)`. If a `coupon_value` set, `coupons.service.issue_coupon(...)` and inject the code as a body/button param.
  5. If suppressed: insert `MarketingSend(status=f"suppressed_{reason}")` — recorded for analytics, NOT enqueued.
  6. Idempotent per `(campaign_id, customer_id)` unique constraint (skip-on-conflict).
  7. Update `campaign.stats` counts + set campaign `status="sent"`. Return a summary dict `{queued, suppressed_cap, suppressed_optout, suppressed_window}`.
- `async record_send_status(session, *, wa_message_id, status, error_code=None) -> None` — called by the webhook status path: map Meta status (`sent|delivered|read|failed`) onto the matching `MarketingSend`; on `error_code == 131049` set status `suppressed_cap` (Meta's silent cap) — feeds the throttle's future decisions.
- `async record_conversion(session, *, restaurant_id, customer_id, order_id, window_hours=48) -> None` — attribution: if the customer has a `MarketingSend` with `sent_at` within `window_hours` before the order, set `converted_order_id`. Called from the ordering flow (best-effort hook; if Phase 3 ordering completion can't be touched now, expose the function and wire in Task 19/post-phase note).
- `async campaign_stats(session, *, restaurant_id, campaign_id) -> dict` — aggregate `MarketingSend` by status + conversion count + conversion rate.

**Step 1: Failing test** (mock provider, dry_run, `FakeSegmentCompiler`):
- `create_segment` + `create_campaign` with an approved mock template; seed 3 customers (1 opted-out, 1 already at 2 sends in last 24h, 1 clean) inside the UAE window (`now_utc` chosen to be 10:00 Dubai); call `run_campaign_send` → assert summary: 1 queued (+1 outbox row), 1 suppressed_optout, 1 suppressed_cap; assert `MarketingSend` rows reflect statuses; `campaign.status == "sent"`.
- Run again with `now_utc` at 20:00 Dubai → all `suppressed_window`, no outbox rows.
- `submit_template` on a `bit.ly`-body template raises `ValueError` (lint).
- `campaign_stats` returns the breakdown.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: marketing service (campaigns, template submit, compliant send, status, analytics)"`

---

### Task 16: Marketing router + schemas

**Files:**
- Create: `src/app/marketing/schemas.py`, `src/app/marketing/router.py`
- Modify: `src/app/main.py` (mount `marketing_router`)
- Create: `tests/marketing/test_router.py`

**Schemas** (`from_attributes`): `SegmentIn(name, plain_english?, dsl?)` (if `plain_english` given and no `dsl`, router compiles via `get_segment_compiler()`), `SegmentOut`, `SegmentPreviewOut(count)`, `TemplateIn(body, header?, footer?, buttons?, ephemeral=True)`, `TemplateOut`, `CampaignIn(type, template_id?, segment_id?, image_url?, coupon_value?, scheduled_at?)`, `CampaignOut`, `CampaignStatsOut(sent, delivered, read, suppressed_cap, suppressed_optout, suppressed_window, converted, conversion_rate)`.

**Router** (`prefix="/api/v1/marketing"`, `tags=["marketing"]`, `Depends(current_restaurant)`):
- `POST /segments` → create_segment (compile if plain_english) → `SegmentOut`.
- `POST /segments/preview` (body: dsl OR plain_english) → `preview_count` → `SegmentPreviewOut` (no persist — manager previews audience size before saving, per spec §4.7).
- `GET /segments/{id}/preview` → recompute live count for a saved segment.
- `POST /templates` → persist `WaTemplate` draft (run `lint_template`, return 422 with violations if non-compliant).
- `POST /templates/{id}/submit` → `submit_template(provider=get_template_provider())` → `TemplateOut`.
- `POST /campaigns` → create_campaign → `CampaignOut`.
- `GET /campaigns` → list (tenant-scoped) → `list[CampaignOut]`.
- `GET /campaigns/{id}/stats` → `campaign_stats` → `CampaignStatsOut`.
- (Manual immediate send: `POST /campaigns/{id}/send` → `run_campaign_send(now_utc=utcnow())` for the manager "send now" button; honors window/cap/opt-out exactly like the scheduler.)

Map `ValueError` (lint/DSL) → 422. Mount in `main.py`.

**Step 1: Failing test** — with auth headers: `POST /segments/preview` with a DSL returns a count; `POST /templates` with a clean body → 200, with a `bit.ly` body → 422; `POST /campaigns` → 200 + draft; `GET /campaigns/{id}/stats` → zeros; cross-tenant campaign → 404.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: marketing router + schemas (segments, templates, campaigns, stats)"`

---

### Task 17: Marketing Celery workers + recurring promo state

**Files:**
- Modify: `src/app/marketing/models.py` (add `RecurringMessageState`)
- Create: `alembic/versions/<hash>_recurring_message_state.py`
- Create: `src/app/marketing/worker.py`
- Modify: `alembic/env.py` / `tests/conftest.py` already register `app.marketing.models` (new table picked up automatically)
- Create: `tests/marketing/test_worker.py`

**RecurringMessageState model** (spec §3): `customer_id` (FK, unique), `restaurant_id`, `next_send_at` (DateTime tz), `suppressed_until` (nullable), `weekday` (int), `usual_send_local_time` (String "HH:MM"). Add `trg_..._updated_at` trigger in migration.

**worker.py** (`@shared_task`, imports `apps.workers.celery_app`):
- `scheduled_campaign_tick()` — every 5 min: find campaigns with `status="scheduled"` and `scheduled_at <= now`; for each, if `is_within_uae_window(now)` run `run_campaign_send(now_utc=now)` else leave for the next tick (do NOT send outside window). Provider = `get_template_provider()`.
- `poll_template_statuses()` — every 2 min: for `wa_templates` in `status="pending_meta"`, `provider.get_status(meta_template_id)` → update status/rejection_reason; on `approved`, if the template's campaign is `scheduled` and due, it becomes eligible for the next campaign tick.
- `recurring_promo_tick()` — hourly: per spec §4.7, find `RecurringMessageState` rows with `next_send_at <= now` and `suppressed_until` null-or-past; build/send the recurring promo (reuse `run_campaign_send`-style per-recipient compliance: window+cap+opt-out); then advance `next_send_at` to the same weekday next week at the customer's usual order time −15 min. Habit drift: recompute `usual_send_local_time` from `customers.usual_order_times` (recency-weighted) when present.
- `cleanup_ephemeral_templates()` — daily ~23:30 Dubai: for `wa_templates` where `ephemeral and status in (approved, sent)` and created today, `provider.delete(name=...)`, set `status="deleted"`, `deleted_at=now` (feeds the 30-day blackout history in `naming.is_name_reusable`).

**Step 1: Failing test** — monkeypatch dry-run/mock; seed a `scheduled` campaign with `scheduled_at` in the past and an approved mock template + 1 clean customer, with `now_utc` inside the Dubai window → `scheduled_campaign_tick()` enqueues 1 send and flips campaign to `sent`. With `now_utc` outside window → no send, campaign stays `scheduled`. `cleanup_ephemeral_templates()` marks an ephemeral approved template `deleted` with `deleted_at` set.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: marketing Celery workers (scheduled send, status poll, recurring, ephemeral cleanup) + recurring_message_state"`

---

### Task 18: Conversation STOP wiring (opt-out from inbound message)

**Files:**
- Modify: `src/app/conversation/engine.py`
- Create: `tests/conversation/test_engine_optout.py`

Per Meta + UAE rules, a customer texting "STOP" must be opted out **immediately, from any conversation state**. Add an early guard at the top of the engine dispatcher (before state routing): if the inbound is a TEXT and `marketing.optout.is_stop_keyword(text)` → `record_opt_out(restaurant_id, from_phone, source="stop_keyword")`, reply with a short confirmation ("You've been unsubscribed from promotions. Reply anytime to order."), and short-circuit (do not run normal state handling). This must NOT interfere with active ordering for non-STOP messages.

**Step 1: Failing test** — drive an inbound "STOP" through the engine for a customer phone; assert an `OptOut` row exists for `(restaurant_id, phone)`, a confirmation outbox row was enqueued, and the conversation state was not advanced into ordering. A normal "1x biryani" message still routes to item collection (regression guard).

**Step 2: implement** (minimal, additive — reuse the engine's existing `_send_text`/`_set_state` helpers; do not refactor unrelated flow). **Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "feat: inbound STOP keyword opt-out wired into conversation engine"`

---

### Task 19: Celery wiring — ml + marketing queues + beat schedule

**Files:**
- Modify: `apps/workers/celery_app.py`
- Create: `tests/workers/test_phase6_wiring.py`

Extend the existing Celery config (do NOT remove `outbox` wiring):
- `autodiscover_tasks([... , "app.predictions", "app.marketing"], related_name="worker")` (keep `app.outbox` and any Phase-4 dispatch/sla entries).
- `task_routes` add: `"predictions.*": {"queue": "ml"}`, `"marketing.*": {"queue": "marketing"}` — name the `@shared_task`s with explicit `name="predictions.nightly_forecast"` etc. so routing is deterministic.
- `beat_schedule` (Asia/Dubai tz already set):
  - `predictions.nightly_forecast` → crontab(hour=2, minute=0)
  - `predictions.nightly_backfill` → crontab(hour=1, minute=30)
  - `marketing.scheduled_campaign_tick` → crontab(minute="*/5")
  - `marketing.poll_template_statuses` → crontab(minute="*/2")
  - `marketing.recurring_promo_tick` → crontab(minute=0)  # hourly
  - `marketing.cleanup_ephemeral_templates` → crontab(hour=23, minute=30)

**Step 1: Failing test** — import `celery_app`; assert the tasks are registered (`"predictions.nightly_forecast" in celery_app.tasks`, `"marketing.scheduled_campaign_tick" in celery_app.tasks`), `task_routes` map predictions→ml and marketing→marketing, and the six beat entries exist.

**Step 2: implement. Step 3: green; ruff.**

**Step 4: Commit.** `git commit -m "chore: wire ml + marketing Celery queues, beat schedule (Asia/Dubai)"`

---

### Task 20: Phase 6 full-suite + smoke gate

**Files:** none new (verification + understanding.txt).

**Step 1: Full suite.** `.venv/bin/pytest` → ALL green (predictions + marketing + conversation opt-out + workers + every prior phase). Investigate any regression with superpowers:systematic-debugging — do not paper over.

**Step 2: Lint.** `.venv/bin/ruff check src apps tests` → clean.

**Step 3: Migrations sanity.**
```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic heads   # expect a single head
docker compose exec db psql -U app -d restaurant -c "\dt" | grep -E "prediction_runs|model_registry|manager_overrides|wa_templates|campaigns|segments|marketing_sends|opt_outs|recurring_message_state"
```
Expect all 9 new tables present, single alembic head.

**Step 4: App boot smoke.**
```bash
.venv/bin/uvicorn app.main:app --port 8000 &
sleep 3
curl -s localhost:8000/health            # {"status":"ok"}
curl -s localhost:8000/openapi.json | python3 -c "import sys,json; p=json.load(sys.stdin)['paths']; assert any('/api/v1/predictions' in k for k in p); assert any('/api/v1/marketing' in k for k in p); print('routes mounted')"
kill %1 2>/dev/null || true
```

**Step 5: Celery worker + beat smoke** (Ctrl-C / kill after a tick):
```bash
.venv/bin/celery -A apps.workers.celery_app:celery_app worker -Q ml,marketing --loglevel=info &
.venv/bin/celery -A apps.workers.celery_app:celery_app beat --loglevel=info &
sleep 6
# expect: worker registers ml + marketing queues; beat lists the 6 phase-6 schedules
kill %1 %2 2>/dev/null || true
```

**Step 6: End-to-end compliant-send smoke (dry-run, mock provider)** — a tiny script or pytest that: seeds a restaurant + approved mock template + segment + 1 opted-in customer, runs `run_campaign_send` at a Dubai-window `now_utc`, asserts exactly 1 TEMPLATE outbox row + 1 `MarketingSend(status="sent")` + `campaign.status="sent"`; then a second opted-out customer yields `suppressed_optout` and NO outbox row. This proves the window+cap+opt-out gate end-to-end with no network.

**Step 7: Commit.** `git commit -m "test: phase-6 full-suite + smoke gate green (predictions + marketing)"`

**Step 8: Update `understanding.txt`** with a dated bullet summarizing Phase 6 completion.

---

## Post-phase

Phase 6 done = the **predictions + marketing** layer is live and tested end-to-end:

- **Predictions** — pure-numpy `RollingAverageModel` (weekday×hour×dish rolling mean, cold-start → dish global mean) behind a `ForecastModel` Protocol that a future `LightGBMForecastModel` can implement with ZERO call-site changes; nightly per-restaurant per-horizon forecasts persisted to `prediction_runs` (order_count, revenue, dish_demand, avg_distance); LLM `ForecastAdjuster` turns manager plain-English overrides into a validated `parsed_effect` DSL applied deterministically (`adjusted`/`reasoning` shown on dashboard); prep-ahead suggestions pushed to the manager over WhatsApp; nightly accuracy backfill (MAPE → `accuracy`) feeding the dashboard.
- **Marketing** — validated audience-segment DSL (NO eval/raw SQL) compiled from customer tags/order history (LLM `SegmentCompiler` for plain English, preview-count before save); Meta template lifecycle with **datestamped names + 30-day reuse blackout**, a pure compliance linter (body/footer/header/button/emoji/URL/variable rules), and a `TemplatePort` (Mock auto-approve for tests/dev + Meta Graph adapter, dry-run-guarded); a fully compliant send path enforcing the **UAE 09:00–18:00 Asia/Dubai window**, the **Meta ~2-marketing-msgs/user/24h cap** (+131049 soft-suppression), and **mandatory STOP opt-out** (inbound STOP wired into the conversation engine, immediate, any state); Phase-4 coupon integration; per-recipient `marketing_sends` ledger driving sent/delivered/converted analytics with conversion attribution.
- **Wiring** — `ml` (nightly forecast 02:00 + accuracy backfill 01:30) and `marketing` (scheduled send */5, template poll */2, recurring hourly, ephemeral cleanup 23:30) Celery queues + beat, all Asia/Dubai.

New tables shipped: `prediction_runs`, `model_registry`, `manager_overrides`, `wa_templates`, `campaigns`, `segments`, `marketing_sends`, `opt_outs`, `recurring_message_state` — all `restaurant_id`-scoped multi-tenant with `trg_<table>_updated_at` triggers.

**Deliberately deferred (note for a later phase):**
- Real LightGBM model + weekly retrain (the port + registry are ready; just register `LightGBMForecastModel` and a retrain beat task).
- Full `automations` trigger/condition/action DSL (Klaviyo-style) — only segments + recurring + today's-special shipped; `automations` table stubbed.
- Meta resumable image-upload flow for IMAGE-header templates (adapter accepts a pre-uploaded `header_handle`; the upload helper is TODO).
- TDRA DNCR screening hook — `OptOut.source="dncr"` exists; the actual TDRA register integration is out of scope (legal/ops dependency).
- Ramadan/holiday/weather feature columns are passthrough (default 0) — wire a calendar/weather source when available; the feature interface already accepts them.

**Next plan: Phase 7 — hardening (real Meta adapter live test, LightGBM retrain, automations DSL) + production readiness.**
