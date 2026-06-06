# Phase 4: Logistics & Dispatch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full logistics layer: geo module with haversine distance (already scaffolded in Phase 3 — now extended), PostGIS rider positions, auto-dispatch engine assigning the nearest available rider, order batching (max 3 orders / 10-min window / proximity clustering), delivery FSM (`assigned → picked_up → en_route → delivered`), SLA monitor Celery beat task with proactive customer notifications and manager alerts, live rider location updates via WhatsApp, automatic late-delivery coupon generation, and COD collection ledger — all fully tested.

**Architecture:** Three new bounded contexts under `src/app/` — `dispatch/` (engine + batching), `sla/` (monitor + coupon issuance), `cod/` (collection ledger). `geo/` module extended from Phase 3. Redis GEO commands store hot rider positions. Celery queues: `dispatch` (triggered on order ready/rider freed), `sla_monitor` (Celery Beat every 30 s). New Alembic migrations add PostGIS `geography(Point)` columns, `batches`, `batch_orders`, `rider_locations`, `assignments`, `sla_events`, `coupons`, `cod_collections`, `rider_shift_reconciliations` tables.

**Spec:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` §3 (data model), §4.3 (dispatch engine), §4.4 (rider flow), §4.5 (SLA monitor & coupons)

**Prerequisites:** Phase 0+1 (identity, riders, audit, `TimestampMixin`, `Base`, `get_session`), Phase 2 (outbox/`enqueue_message`, WhatsApp provider), Phase 3 (ordering FSM with `ASSIGNED`/`PICKED_UP`/`ARRIVING`/`DELIVERED` statuses, `Order.sla_deadline`, `Order.weather_delay_disclosed`, `geo/haversine.py`, `ordering/fees.py`) fully executed and passing.

---

## File structure (locked in)

```
src/app/
  geo/
    __init__.py                          already exists (Phase 3)
    haversine.py                         already exists — no changes
    port.py                              NEW: GeoPort Protocol (distance + ETA)
    google_maps.py                       NEW: GoogleMapsGeoProvider (stub for now)
    fake.py                              NEW: FakeGeoProvider (haversine-backed, static speed 25 km/h)
    factory.py                           NEW: get_geo_provider() FastAPI dependency

  dispatch/
    __init__.py
    models.py                            Batch, BatchOrder, RiderLocation, Assignment tables
    service.py                           run_dispatch_engine(), assign_rider(), build_batch()
    scoring.py                           score_riders() — haversine + workload + on-time %
    router.py                            POST /api/v1/dispatch/trigger (manager manual trigger)
    worker.py                            Celery task: dispatch_for_restaurant()

  sla/
    __init__.py
    models.py                            SlaEvent table
    monitor.py                           check_sla_deadlines() — heartbeat logic
    worker.py                            Celery beat task: sla_monitor_tick()

  coupons/
    __init__.py
    models.py                            Coupon table
    service.py                           issue_coupon(), redeem_coupon()

  cod/
    __init__.py
    models.py                            CodCollection, RiderShiftReconciliation tables
    service.py                           record_collection(), reconcile_shift()
    router.py                            GET /api/v1/cod/shift/{rider_id}

  conversation/
    engine.py                            EXTEND: rider location update handler, "Order Picked" flow

  ordering/
    models.py                            EXTEND: add rider_id FK to orders

  identity/
    models.py                            EXTEND: add performance JSONB to riders

apps/workers/
  celery_app.py                          MODIFY: add dispatch + sla_monitor queues + beat schedule

alembic/versions/
  <hash>_geo_columns_rider_location.py   PostGIS geography columns, rider_locations table
  <hash>_dispatch_tables.py              batches, batch_orders, assignments
  <hash>_sla_coupon_tables.py            sla_events, coupons
  <hash>_cod_tables.py                   cod_collections, rider_shift_reconciliations
  <hash>_order_rider_fk.py               orders.rider_id FK + rider performance JSONB

tests/
  geo/
    test_geo_port.py                     FakeGeoProvider: distance + ETA tests
  dispatch/
    __init__.py
    test_scoring.py                      score_riders() unit tests
    test_batch.py                        build_batch() proximity + timing + max-3 tests
    test_dispatch_engine.py              run_dispatch_engine() integration tests
    test_dispatch_worker.py              Celery task smoke test
  sla/
    __init__.py
    test_sla_monitor.py                  yellow/red/breach event creation + coupon gate
  coupons/
    __init__.py
    test_coupons.py                      issue + redeem round-trip, expiry
  cod/
    __init__.py
    test_cod.py                          record_collection + reconcile_shift
  conversation/
    test_engine_rider.py                 rider location message handler + "Order Picked" flow
```

---

### Task 1: Geo port — `GeoPort` protocol + `FakeGeoProvider` + `GoogleMapsGeoProvider` stub

**Files:**
- Create: `src/app/geo/port.py`, `src/app/geo/fake.py`, `src/app/geo/google_maps.py`, `src/app/geo/factory.py`
- Create: `tests/geo/test_geo_port.py`

Spec requirement: Maps API down → haversine + static speed 25 km/h + widened buffers; ETAs flagged as estimates.

- [ ] **Step 1: Write the failing tests**

```python
# tests/geo/test_geo_port.py
from app.geo.fake import FakeGeoProvider
from app.geo.port import GeoPort


def test_fake_distance_matches_haversine():
    """FakeGeoProvider.distance_km delegates to haversine."""
    provider = FakeGeoProvider()
    d = provider.distance_km(25.2048, 55.2708, 25.2100, 55.2750)
    assert 0.5 < d < 1.5  # ~0.8 km


def test_fake_eta_minutes_uses_static_speed():
    """ETA = distance / 25 km/h in minutes, rounded up, minimum 1."""
    provider = FakeGeoProvider()
    # 5 km at 25 km/h = 12 min
    eta = provider.eta_minutes(5.0)
    assert eta == 12


def test_fake_eta_minimum_1_minute():
    provider = FakeGeoProvider()
    eta = provider.eta_minutes(0.1)
    assert eta >= 1


def test_fake_provider_satisfies_protocol():
    """FakeGeoProvider structurally satisfies GeoPort."""
    p: GeoPort = FakeGeoProvider()
    assert callable(p.distance_km)
    assert callable(p.eta_minutes)
    assert hasattr(p, "is_estimate")
    assert p.is_estimate is True


def test_google_maps_provider_instantiates_without_network():
    """GoogleMapsGeoProvider can be constructed without making network calls."""
    import os
    os.environ.setdefault("APP_GOOGLE_MAPS_API_KEY", "")
    from app.geo.google_maps import GoogleMapsGeoProvider
    provider = GoogleMapsGeoProvider()
    assert provider is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/geo/test_geo_port.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.geo.port'`

- [ ] **Step 3: Write implementation**

```python
# src/app/geo/port.py
from typing import Protocol


class GeoPort(Protocol):
    is_estimate: bool  # True = using haversine fallback

    def distance_km(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float,
    ) -> float:
        """Return distance between two points in km."""
        ...

    def eta_minutes(self, distance_km: float, buffer_minutes: int = 0) -> int:
        """Return ETA in whole minutes. buffer_minutes added after calculation."""
        ...
```

```python
# src/app/geo/fake.py
import math
from app.geo.haversine import distance_km as _haversine

_CITY_SPEED_KMH = 25.0


class FakeGeoProvider:
    """Haversine-backed provider for tests and Maps-API-down fallback.

    Uses static city speed 25 km/h.  is_estimate = True always.
    """

    is_estimate: bool = True

    def distance_km(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float,
    ) -> float:
        return _haversine(lat1, lon1, lat2, lon2)

    def eta_minutes(self, distance_km: float, buffer_minutes: int = 0) -> int:
        raw = (distance_km / _CITY_SPEED_KMH) * 60
        return max(1, math.ceil(raw)) + buffer_minutes
```

```python
# src/app/geo/google_maps.py
"""Google Maps Routes API provider.

Real implementation calls Routes API with traffic-aware durations.
Falls back to FakeGeoProvider on any network/auth error (spec §5).
"""
import math
import logging

from app.geo.haversine import distance_km as _haversine

logger = logging.getLogger(__name__)
_CITY_SPEED_KMH = 25.0


class GoogleMapsGeoProvider:
    """Production geo provider — Google Maps Routes API with traffic.

    Graceful degradation: on any API failure returns haversine estimate
    and sets is_estimate=True.
    """

    def __init__(self) -> None:
        from app.config import get_settings
        self._api_key = get_settings().google_maps_api_key
        self.is_estimate: bool = False  # flipped to True on API failure

    def distance_km(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float,
    ) -> float:
        """Return road distance in km (haversine fallback on Maps failure)."""
        try:
            return self._maps_distance(lat1, lon1, lat2, lon2)
        except Exception as exc:
            logger.warning("Google Maps distance failed, using haversine: %s", exc)
            self.is_estimate = True
            return _haversine(lat1, lon1, lat2, lon2)

    def eta_minutes(self, distance_km: float, buffer_minutes: int = 0) -> int:
        """Return ETA in whole minutes (static speed when is_estimate=True)."""
        raw = (distance_km / _CITY_SPEED_KMH) * 60
        return max(1, math.ceil(raw)) + buffer_minutes

    def _maps_distance(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float,
    ) -> float:
        """Call Google Maps Routes API. Raises on failure."""
        if not self._api_key:
            raise ValueError("APP_GOOGLE_MAPS_API_KEY not configured")
        # Real implementation: POST to https://routes.googleapis.com/directions/v2:computeRoutes
        # Returns routes[0].distanceMeters / 1000.0
        # Placeholder until production API key is available:
        raise NotImplementedError("Google Maps API key required for production routes")
```

```python
# src/app/geo/factory.py
from app.config import get_settings


def get_geo_provider():
    """FastAPI/Celery dependency. Returns FakeGeoProvider or GoogleMapsGeoProvider."""
    settings = get_settings()
    if getattr(settings, "google_maps_api_key", "") and settings.geo_provider == "google_maps":
        from app.geo.google_maps import GoogleMapsGeoProvider
        return GoogleMapsGeoProvider()
    from app.geo.fake import FakeGeoProvider
    return FakeGeoProvider()
```

- [ ] **Step 4: Add settings fields to `src/app/config.py`** — append after existing fields:

```python
    # Geo
    geo_provider: str = "fake"          # fake | google_maps
    google_maps_api_key: str = ""
```

Append to `.env.example`:
```
APP_GEO_PROVIDER=fake
APP_GOOGLE_MAPS_API_KEY=
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/geo/test_geo_port.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/geo/port.py src/app/geo/fake.py src/app/geo/google_maps.py \
        src/app/geo/factory.py src/app/config.py .env.example \
        tests/geo/test_geo_port.py
git commit -m "feat: geo port with FakeGeoProvider (haversine+static speed) and GoogleMaps stub"
```

---

### Task 2: Migrations — PostGIS geography columns, `rider_locations`, order `rider_id`, rider `performance`

**Files:**
- Extend: `src/app/identity/models.py` (add `performance` JSONB to `Rider`)
- Extend: `src/app/ordering/models.py` (add `rider_id` FK to `Order`)
- Modify: `alembic/env.py`, `tests/conftest.py` (no new module imports needed — same files)

- [ ] **Step 1: Write the failing test**

```python
# tests/dispatch/__init__.py   (empty)

# append to tests/ordering/test_service.py
async def test_order_has_rider_id_column(db_session):
    """Order.rider_id column exists and is nullable."""
    from decimal import Decimal
    from app.ordering.models import Customer, Order
    customer = Customer(
        restaurant_id=1, phone="+971501230200", name="RiderFKTest",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-RFK1", status="draft",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("0.00"), total=Decimal("0.00"),
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)
    assert order.rider_id is None  # nullable FK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ordering/test_service.py::test_order_has_rider_id_column -v`
Expected: FAIL — `AttributeError: 'Order' has no attribute 'rider_id'`

- [ ] **Step 3: Extend `src/app/ordering/models.py`** — add `rider_id` to `Order` class:

```python
# In Order class, after address_id field:
rider_id: Mapped[int | None] = mapped_column(ForeignKey("riders.id"), index=True)
```

- [ ] **Step 4: Extend `src/app/identity/models.py`** — add `performance` JSONB to `Rider`:

```python
# In Rider class, after status field:
performance: Mapped[dict] = mapped_column(
    JSONB,
    default=lambda: {"on_time_pct": 100.0, "avg_delivery_min": 25, "total_deliveries": 0},
)
```

- [ ] **Step 5: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "order_rider_fk_rider_performance"
.venv/bin/alembic upgrade head
```

Add `BEFORE UPDATE` trigger in migration body:

```python
# In upgrade():
op.execute("""
    CREATE TRIGGER trg_orders_updated_at_p4
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
```

Note: if trigger already exists from Phase 3 migration, omit this line (check via `\dy` in psql).

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ordering/test_service.py::test_order_has_rider_id_column -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/ordering/models.py src/app/identity/models.py \
        alembic/versions/ tests/ordering/test_service.py
git commit -m "feat: order.rider_id FK + rider.performance JSONB migration"
```

---

### Task 3: Dispatch models — `batches`, `batch_orders`, `rider_locations`, `assignments`

**Files:**
- Create: `src/app/dispatch/__init__.py`, `src/app/dispatch/models.py`
- Modify: `alembic/env.py`, `tests/conftest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/dispatch/test_scoring.py  (partial — model import test first)
from app.dispatch.models import Batch, BatchOrder, RiderLocation, Assignment


def test_batch_model_importable():
    assert Batch.__tablename__ == "batches"


def test_rider_location_model_importable():
    assert RiderLocation.__tablename__ == "rider_locations"


def test_assignment_model_importable():
    assert Assignment.__tablename__ == "assignments"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dispatch/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dispatch'`

- [ ] **Step 3: Write implementation**

```python
# src/app/dispatch/__init__.py
```

```python
# src/app/dispatch/models.py
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Batch(Base, TimestampMixin):
    """A grouped set of orders assigned to one rider for sequential delivery."""
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    # planned | picked_up | in_progress | completed
    route: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"stops": [{"order_id": int, "lat": float, "lon": float, "eta_min": int}]}
    total_est_min: Mapped[int | None] = mapped_column(Integer)


class BatchOrder(Base, TimestampMixin):
    """Junction: which orders belong to a batch, in delivery sequence."""
    __tablename__ = "batch_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RiderLocation(Base, TimestampMixin):
    """Time-series table: each location ping from a rider.

    Hot copy also stored in Redis GEO key ``rider_geo:{restaurant_id}``.
    Retention policy: 30 days raw (matching spec §6 privacy).
    """
    __tablename__ = "rider_locations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Assignment(Base, TimestampMixin):
    """Audit record of every dispatch decision (explainability)."""
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Explainability payload — why this rider was chosen
    algorithm_score: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"distance_km": float, "workload_score": float, "area_score": float,
    #  "on_time_pct": float, "composite": float}
```

- [ ] **Step 4: Register in `alembic/env.py` and `tests/conftest.py`**

```python
import app.dispatch.models  # noqa: F401
```

- [ ] **Step 5: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "dispatch_tables"
.venv/bin/alembic upgrade head
```

Add `BEFORE UPDATE` triggers in migration body:

```python
op.execute("""
    CREATE TRIGGER trg_batches_updated_at
    BEFORE UPDATE ON batches FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
op.execute("""
    CREATE TRIGGER trg_batch_orders_updated_at
    BEFORE UPDATE ON batch_orders FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
op.execute("""
    CREATE TRIGGER trg_rider_locations_updated_at
    BEFORE UPDATE ON rider_locations FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
op.execute("""
    CREATE TRIGGER trg_assignments_updated_at
    BEFORE UPDATE ON assignments FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/dispatch/test_scoring.py -v`
Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/dispatch alembic/versions/ alembic/env.py tests/conftest.py \
        tests/dispatch/__init__.py tests/dispatch/test_scoring.py
git commit -m "feat: dispatch models — batches, batch_orders, rider_locations, assignments with migration"
```

---

### Task 4: SLA, Coupon, COD models + migrations

**Files:**
- Create: `src/app/sla/__init__.py`, `src/app/sla/models.py`
- Create: `src/app/coupons/__init__.py`, `src/app/coupons/models.py`
- Create: `src/app/cod/__init__.py`, `src/app/cod/models.py`
- Modify: `alembic/env.py`, `tests/conftest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/sla/__init__.py   (empty)
# tests/coupons/__init__.py  (empty)
# tests/cod/__init__.py   (empty)

# tests/sla/test_sla_monitor.py  (import test only for now)
from app.sla.models import SlaEvent
from app.coupons.models import Coupon
from app.cod.models import CodCollection, RiderShiftReconciliation


def test_sla_event_importable():
    assert SlaEvent.__tablename__ == "sla_events"


def test_coupon_importable():
    assert Coupon.__tablename__ == "coupons"


def test_cod_collection_importable():
    assert CodCollection.__tablename__ == "cod_collections"


def test_reconciliation_importable():
    assert RiderShiftReconciliation.__tablename__ == "rider_shift_reconciliations"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/sla/test_sla_monitor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sla'`

- [ ] **Step 3: Write implementation**

```python
# src/app/sla/__init__.py
```

```python
# src/app/sla/models.py
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class SlaEvent(Base, TimestampMixin):
    """Records yellow/red/breach SLA alerts for an order."""
    __tablename__ = "sla_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    # yellow_30 | red_35 | breach_40
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    notified: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"customer": bool, "manager": bool}
```

```python
# src/app/coupons/__init__.py
```

```python
# src/app/coupons/models.py
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Coupon(Base, TimestampMixin):
    """Late-delivery apology coupon. Single-use, issued per order breach."""
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    # cause — the order that triggered this coupon
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    discount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(16), default="issued", index=True)
    # issued | redeemed | expired
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_on_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
```

```python
# src/app/cod/__init__.py
```

```python
# src/app/cod/models.py
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class CodCollection(Base, TimestampMixin):
    """Records cash collected by a rider for a delivered order."""
    __tablename__ = "cod_collections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiderShiftReconciliation(Base, TimestampMixin):
    """End-of-shift COD cash reconciliation for a rider."""
    __tablename__ = "rider_shift_reconciliations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    shift_date: Mapped[datetime] = mapped_column(Date, index=True)
    expected_total_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    collected_total_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    variance_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending | balanced | variance
```

- [ ] **Step 4: Register all three in `alembic/env.py` and `tests/conftest.py`**

```python
import app.sla.models      # noqa: F401
import app.coupons.models  # noqa: F401
import app.cod.models      # noqa: F401
```

- [ ] **Step 5: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "sla_coupon_cod_tables"
.venv/bin/alembic upgrade head
```

Add `BEFORE UPDATE` triggers in migration body:

```python
for tbl in ("sla_events", "coupons", "cod_collections", "rider_shift_reconciliations"):
    op.execute(f"""
        CREATE TRIGGER trg_{tbl}_updated_at
        BEFORE UPDATE ON {tbl} FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests/sla/test_sla_monitor.py -v`
Expected: 4 PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/sla src/app/coupons src/app/cod \
        alembic/versions/ alembic/env.py tests/conftest.py \
        tests/sla/__init__.py tests/sla/test_sla_monitor.py \
        tests/coupons/__init__.py tests/cod/__init__.py
git commit -m "feat: sla_events, coupons, cod_collections, rider_shift_reconciliations tables with migration"
```

---

### Task 5: Geo fee calculator — distance tiers + radius rejection

**Files:**
- Create: `src/app/geo/fees.py` (canonical home; Phase 3 may have a copy in `ordering/fees.py` — if so, re-export from there to avoid duplication)
- Create: `tests/geo/test_fees.py`

Business rules (spec + CLAUDE.md, non-negotiable): max radius 10 km; ≤3 km free; >3 and ≤5 km AED 5; >5 and ≤10 km AED 10; >10 km → reject (out of radius). Money is `Decimal`, AED.

- [ ] **Step 1: Write the failing tests**

```python
# tests/geo/test_fees.py
from decimal import Decimal

import pytest

from app.geo.fees import OutOfRadiusError, delivery_fee_aed


def test_free_under_3km():
    assert delivery_fee_aed(0.5) == Decimal("0.00")
    assert delivery_fee_aed(3.0) == Decimal("0.00")  # boundary inclusive


def test_aed5_between_3_and_5km():
    assert delivery_fee_aed(3.01) == Decimal("5.00")
    assert delivery_fee_aed(5.0) == Decimal("5.00")  # boundary inclusive


def test_aed10_between_5_and_10km():
    assert delivery_fee_aed(5.01) == Decimal("10.00")
    assert delivery_fee_aed(10.0) == Decimal("10.00")  # boundary inclusive


def test_reject_over_10km():
    with pytest.raises(OutOfRadiusError):
        delivery_fee_aed(10.01)


def test_returns_decimal_type():
    assert isinstance(delivery_fee_aed(2.0), Decimal)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/geo/test_fees.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.geo.fees'`

- [ ] **Step 3: Write implementation**

```python
# src/app/geo/fees.py
from decimal import Decimal

MAX_RADIUS_KM = 10.0
_FREE_KM = 3.0
_MID_KM = 5.0
_MID_FEE = Decimal("5.00")
_FAR_FEE = Decimal("10.00")
_FREE_FEE = Decimal("0.00")


class OutOfRadiusError(ValueError):
    """Raised when a delivery distance exceeds the 10 km service radius."""


def delivery_fee_aed(distance_km: float) -> Decimal:
    """Return the COD delivery fee for a distance in km.

    Tiers (boundaries inclusive on the lower-fee side):
      <=3 km  -> free
      <=5 km  -> AED 5
      <=10 km -> AED 10
      >10 km  -> OutOfRadiusError
    """
    if distance_km <= _FREE_KM:
        return _FREE_FEE
    if distance_km <= _MID_KM:
        return _MID_FEE
    if distance_km <= MAX_RADIUS_KM:
        return _FAR_FEE
    raise OutOfRadiusError(
        f"Distance {distance_km:.2f} km exceeds {MAX_RADIUS_KM} km service radius"
    )
```

If `src/app/ordering/fees.py` already exists from Phase 3, make it re-export the canonical home so there is one source of truth:

```python
# src/app/ordering/fees.py  (if it exists)
from app.geo.fees import OutOfRadiusError, delivery_fee_aed  # noqa: F401
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/geo/test_fees.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/geo/fees.py tests/geo/test_fees.py
git commit -m "feat: geo delivery fee calculator with 10km radius rejection (Decimal AED tiers)"
```

---

### Task 6: Rider scoring — nearest-available by haversine + workload + on-time %

**Files:**
- Create: `src/app/dispatch/scoring.py`
- Append: `tests/dispatch/test_scoring.py` (model-import tests already there from Task 3)

Spec §4.3.4: rider scoring blends distance to restaurant, current workload, area performance, on-time %. Lower composite = better. Riders are **employees** — there is no accept/reject; the engine simply assigns the best-scoring available rider.

- [ ] **Step 1: Write the failing tests** (append to `tests/dispatch/test_scoring.py`)

```python
from app.dispatch.scoring import RiderCandidate, score_rider, rank_riders


def test_score_rider_closer_is_better():
    near = RiderCandidate(rider_id=1, distance_km=1.0, active_orders=0, on_time_pct=100.0)
    far = RiderCandidate(rider_id=2, distance_km=8.0, active_orders=0, on_time_pct=100.0)
    assert score_rider(near).composite < score_rider(far).composite


def test_score_rider_workload_penalty():
    idle = RiderCandidate(rider_id=1, distance_km=2.0, active_orders=0, on_time_pct=100.0)
    busy = RiderCandidate(rider_id=2, distance_km=2.0, active_orders=3, on_time_pct=100.0)
    assert score_rider(idle).composite < score_rider(busy).composite


def test_score_rider_on_time_reward():
    reliable = RiderCandidate(rider_id=1, distance_km=2.0, active_orders=1, on_time_pct=98.0)
    flaky = RiderCandidate(rider_id=2, distance_km=2.0, active_orders=1, on_time_pct=60.0)
    assert score_rider(reliable).composite < score_rider(flaky).composite


def test_score_returns_explainability_payload():
    s = score_rider(RiderCandidate(rider_id=1, distance_km=2.0, active_orders=1, on_time_pct=90.0))
    assert set(s.breakdown) >= {"distance_km", "workload_score", "on_time_pct", "composite"}


def test_rank_riders_orders_best_first():
    cands = [
        RiderCandidate(rider_id=1, distance_km=9.0, active_orders=2, on_time_pct=70.0),
        RiderCandidate(rider_id=2, distance_km=1.0, active_orders=0, on_time_pct=99.0),
    ]
    ranked = rank_riders(cands)
    assert ranked[0].rider_id == 2


def test_rank_riders_empty_returns_empty():
    assert rank_riders([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dispatch/test_scoring.py -v`
Expected: FAIL — `ImportError: cannot import name 'RiderCandidate'`

- [ ] **Step 3: Write implementation**

```python
# src/app/dispatch/scoring.py
from dataclasses import dataclass, field

# Weights (tunable; lower composite = better candidate).
_W_DISTANCE = 1.0      # per km
_W_WORKLOAD = 2.0      # per active order
_W_ONTIME = 0.10       # per missing on-time percentage point


@dataclass
class RiderCandidate:
    rider_id: int
    distance_km: float          # rider -> restaurant
    active_orders: int          # current in-flight orders (workload)
    on_time_pct: float          # rider.performance["on_time_pct"]


@dataclass
class ScoredRider:
    rider_id: int
    composite: float
    breakdown: dict = field(default_factory=dict)


def score_rider(c: RiderCandidate) -> ScoredRider:
    """Composite score — lower is better. Persisted to assignments.algorithm_score."""
    distance_score = _W_DISTANCE * c.distance_km
    workload_score = _W_WORKLOAD * c.active_orders
    # on-time penalty: how far below 100% the rider is
    on_time_penalty = _W_ONTIME * max(0.0, 100.0 - c.on_time_pct)
    composite = distance_score + workload_score + on_time_penalty
    return ScoredRider(
        rider_id=c.rider_id,
        composite=composite,
        breakdown={
            "distance_km": c.distance_km,
            "workload_score": workload_score,
            "on_time_pct": c.on_time_pct,
            "composite": composite,
        },
    )


def rank_riders(candidates: list[RiderCandidate]) -> list[ScoredRider]:
    """Return scored riders sorted best (lowest composite) first."""
    return sorted((score_rider(c) for c in candidates), key=lambda s: s.composite)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/dispatch/test_scoring.py -v`
Expected: all PASS (3 model-import + 6 scoring)

- [ ] **Step 5: Commit**

```bash
git add src/app/dispatch/scoring.py tests/dispatch/test_scoring.py
git commit -m "feat: rider scoring — distance + workload + on-time composite with explainability"
```

---

### Task 7: Order batching — max 3 / 10-min window / proximity + 10-min SLA buffer

**Files:**
- Create: `src/app/dispatch/batching.py`
- Create: `tests/dispatch/test_batch.py`

Spec §4.3.2 + CLAUDE.md: max 3 orders per batch; orders grouped within a 10-minute readiness window; clustered by destination proximity (haversine here, PostGIS later). Each batched order adds a **+10 min SLA buffer** per stop. A candidate batch is valid iff for EVERY order in it the projected delivery stays within the 30-min internal target. If a new same-area order can't fit, the current batch dispatches and a new one starts.

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_batch.py
from datetime import datetime, timezone, timedelta

from app.dispatch.batching import OrderCandidate, build_batches

MAX_PER_BATCH = 3
BASE = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _order(oid, lat, lon, ready_offset_s=0):
    return OrderCandidate(
        order_id=oid, lat=lat, lon=lon,
        ready_at=BASE + timedelta(seconds=ready_offset_s),
        minutes_elapsed=5.0,  # since sla_confirmed_at
    )


def test_nearby_orders_batched_together():
    orders = [
        _order(1, 25.2048, 55.2708),
        _order(2, 25.2050, 55.2710),  # ~30 m away
    ]
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0)
    assert len(batches) == 1
    assert {o.order_id for o in batches[0].orders} == {1, 2}


def test_far_orders_split_into_separate_batches():
    orders = [
        _order(1, 25.2048, 55.2708),
        _order(2, 25.3000, 55.4000),  # several km away
    ]
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0)
    assert len(batches) == 2


def test_batch_capped_at_max_per_batch():
    orders = [_order(i, 25.2048 + i * 0.0001, 55.2708) for i in range(1, 6)]  # 5 close orders
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0)
    assert all(len(b.orders) <= MAX_PER_BATCH for b in batches)
    assert sum(len(b.orders) for b in batches) == 5


def test_readiness_window_splits_late_order():
    orders = [
        _order(1, 25.2048, 55.2708, ready_offset_s=0),
        _order(2, 25.2049, 55.2709, ready_offset_s=11 * 60),  # 11 min later > window
    ]
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0, window_min=10)
    assert len(batches) == 2


def test_sla_buffer_applied_per_stop():
    orders = [_order(1, 25.2048, 55.2708), _order(2, 25.2050, 55.2710)]
    batches = build_batches(orders, max_per_batch=MAX_PER_BATCH, proximity_km=1.0)
    # 2 orders -> second stop carries +10 min buffer
    assert batches[0].sla_buffer_min == 10


def test_empty_input_returns_empty():
    assert build_batches([], max_per_batch=MAX_PER_BATCH, proximity_km=1.0) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dispatch/test_batch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dispatch.batching'`

- [ ] **Step 3: Write implementation**

```python
# src/app/dispatch/batching.py
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.geo.haversine import distance_km

SLA_BUFFER_PER_ORDER_MIN = 10
DEFAULT_WINDOW_MIN = 10
DEFAULT_PROXIMITY_KM = 1.0
DEFAULT_MAX_PER_BATCH = 3


@dataclass
class OrderCandidate:
    order_id: int
    lat: float
    lon: float
    ready_at: datetime
    minutes_elapsed: float  # since sla_confirmed_at


@dataclass
class PlannedBatch:
    orders: list[OrderCandidate] = field(default_factory=list)

    @property
    def sla_buffer_min(self) -> int:
        """+10 min per *additional* batched stop beyond the first."""
        extra = max(0, len(self.orders) - 1)
        return extra * SLA_BUFFER_PER_ORDER_MIN

    @property
    def seed(self) -> OrderCandidate:
        return self.orders[0]


def build_batches(
    orders: list[OrderCandidate],
    *,
    max_per_batch: int = DEFAULT_MAX_PER_BATCH,
    proximity_km: float = DEFAULT_PROXIMITY_KM,
    window_min: int = DEFAULT_WINDOW_MIN,
) -> list[PlannedBatch]:
    """Greedy proximity batching.

    Orders are seeded oldest-first; each subsequent order joins the first open
    batch whose seed is within ``proximity_km`` AND within the ``window_min``
    readiness window AND below ``max_per_batch``. Otherwise it seeds a new batch.
    """
    if not orders:
        return []

    remaining = sorted(orders, key=lambda o: o.ready_at)
    batches: list[PlannedBatch] = []

    for order in remaining:
        placed = False
        for batch in batches:
            if len(batch.orders) >= max_per_batch:
                continue
            seed = batch.seed
            within_proximity = (
                distance_km(seed.lat, seed.lon, order.lat, order.lon) <= proximity_km
            )
            within_window = (
                order.ready_at - seed.ready_at <= timedelta(minutes=window_min)
            )
            if within_proximity and within_window:
                batch.orders.append(order)
                placed = True
                break
        if not placed:
            batches.append(PlannedBatch(orders=[order]))

    return batches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/dispatch/test_batch.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/dispatch/batching.py tests/dispatch/test_batch.py
git commit -m "feat: proximity order batching — max 3, 10-min window, +10-min SLA buffer per stop"
```

---

### Task 8: Dispatch engine — assign nearest available rider, no-rider manager alert, delivery FSM

**Files:**
- Create: `src/app/dispatch/service.py`
- Create: `tests/dispatch/test_dispatch_engine.py`

Spec §4.3. Behaviour:
- Eligible set = orders in `ready` (unassigned) + riders with `status == "available"`.
- Build batches (Task 7), rank riders (Task 6), assign best-scoring rider per batch.
- On assignment: write `Assignment` row (with `algorithm_score`), set every order `status = "assigned"` + `rider_id`, set rider `status = "on_delivery"`, create `Batch` + `BatchOrder` rows, `record_audit` per order transition, notify rider via outbox.
- **No available riders** → order stays `ready`/unassigned (no status change), enqueue a manager alert via outbox, return a result flagging retry. Riders are employees → there is NO accept/reject step.
- Concurrency: acquire a per-restaurant Redis lock key `dispatch_lock:{restaurant_id}` (best-effort; if `redis` unavailable in tests, lock is a no-op context manager).

Order FSM (spec §3, never invent statuses): `ready → assigned → picked_up → arriving → delivered`. This task only performs `ready → assigned`; later transitions are driven by rider WhatsApp actions (Task 10).

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_dispatch_engine.py
from decimal import Decimal

import pytest

from app.dispatch.service import run_dispatch_engine
from app.dispatch.models import Assignment, Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order
from app.outbox.models import OutboxMessage
from sqlalchemy import select


async def _seed_restaurant(db_session, lat=25.2048, lon=55.2708):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x",
                   location_lat=lat, location_lon=lon, settings={})
    db_session.add(r)
    await db_session.flush()
    return r


async def _ready_order(db_session, restaurant_id, lat, lon, num):
    c = Customer(restaurant_id=restaurant_id, phone=f"+97150{num:07d}", name="C",
                 usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(c)
    await db_session.flush()
    o = Order(restaurant_id=restaurant_id, customer_id=c.id, order_number=f"O{num}",
              status="ready", priority="normal", weather_delay_disclosed=False,
              delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("10.00"), total=Decimal("10.00"),
              dropoff_lat=lat, dropoff_lon=lon)
    db_session.add(o)
    await db_session.flush()
    return o


async def test_assigns_nearest_available_rider(db_session):
    r = await _seed_restaurant(db_session)
    near = Rider(restaurant_id=r.id, name="Near", phone="+971500000001",
                 status="available", last_lat=25.2048, last_lon=55.2708,
                 performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5})
    far = Rider(restaurant_id=r.id, name="Far", phone="+971500000002",
                status="available", last_lat=25.3500, last_lon=55.4500,
                performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5})
    db_session.add_all([near, far])
    await db_session.flush()
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 1)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "assigned"
    assert order.rider_id == near.id
    assert result.assigned_count == 1
    assignment = await db_session.scalar(select(Assignment).where(Assignment.order_id == order.id))
    assert assignment.rider_id == near.id
    assert "composite" in assignment.algorithm_score


async def test_no_available_riders_alerts_manager_and_leaves_unassigned(db_session):
    r = await _seed_restaurant(db_session)
    order = await _ready_order(db_session, r.id, 25.2050, 55.2710, 2)
    await db_session.commit()

    result = await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == "ready"        # unchanged
    assert order.rider_id is None
    assert result.unassigned_count == 1
    assert result.needs_retry is True
    alert = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == r.phone)
    )
    assert alert is not None              # manager alerted


async def test_rider_set_on_delivery_and_batch_created(db_session):
    r = await _seed_restaurant(db_session)
    rider = Rider(restaurant_id=r.id, name="X", phone="+971500000003",
                  status="available", last_lat=25.2048, last_lon=55.2708,
                  performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0})
    db_session.add(rider)
    await db_session.flush()
    o1 = await _ready_order(db_session, r.id, 25.2050, 55.2710, 3)
    o2 = await _ready_order(db_session, r.id, 25.2051, 55.2711, 4)
    await db_session.commit()

    await run_dispatch_engine(db_session, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(rider)
    assert rider.status == "on_delivery"
    batch = await db_session.scalar(select(Batch).where(Batch.rider_id == rider.id))
    assert batch is not None
    bos = (await db_session.scalars(select(BatchOrder).where(BatchOrder.batch_id == batch.id))).all()
    assert len(bos) == 2  # both nearby orders batched to one rider
```

NOTE for implementer: this test assumes `Order.dropoff_lat/dropoff_lon` and `Rider.last_lat/last_lon` columns exist. If Phase 3 used `geography(Point)` instead, adapt the seed + service to read coordinates via `ST_X/ST_Y` or the existing column names — keep the public behaviour identical. Add a migration if these float columns are genuinely missing (with `trg_<table>_updated_at` triggers as per conventions).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dispatch/test_dispatch_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dispatch.service'`

- [ ] **Step 3: Write implementation**

```python
# src/app/dispatch/service.py
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.dispatch.batching import OrderCandidate, build_batches
from app.dispatch.models import Assignment, Batch, BatchOrder
from app.dispatch.scoring import RiderCandidate, rank_riders
from app.geo.haversine import distance_km
from app.identity.models import Restaurant, Rider
from app.ordering.models import Order
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType


@dataclass
class DispatchResult:
    assigned_count: int = 0
    unassigned_count: int = 0
    needs_retry: bool = False


@asynccontextmanager
async def _restaurant_lock(restaurant_id: int):
    """Best-effort per-restaurant lock. No-op if redis unavailable (tests)."""
    try:
        from app.redis_client import get_redis  # provided by Phase 2 if present
        redis = get_redis()
        lock = redis.lock(f"dispatch_lock:{restaurant_id}", timeout=30)
        acquired = await lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                await lock.release()
    except Exception:
        # redis missing/unreachable -> proceed without distributed lock
        yield True


async def run_dispatch_engine(
    session: AsyncSession, *, restaurant_id: int
) -> DispatchResult:
    """Assign ready orders to nearest available riders. Idempotent per call."""
    async with _restaurant_lock(restaurant_id):
        return await _dispatch(session, restaurant_id)


async def _dispatch(session: AsyncSession, restaurant_id: int) -> DispatchResult:
    restaurant = await session.get(Restaurant, restaurant_id)
    now = datetime.now(timezone.utc)

    ready = (
        await session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant_id,
                Order.status == "ready",
                Order.rider_id.is_(None),
            )
        )
    ).all()
    if not ready:
        return DispatchResult()

    candidates = [
        OrderCandidate(
            order_id=o.id, lat=o.dropoff_lat, lon=o.dropoff_lon,
            ready_at=o.updated_at or now, minutes_elapsed=0.0,
        )
        for o in ready
    ]
    batches = build_batches(candidates)
    orders_by_id = {o.id: o for o in ready}
    result = DispatchResult()

    for planned in batches:
        riders = (
            await session.scalars(
                select(Rider).where(
                    Rider.restaurant_id == restaurant_id,
                    Rider.status == "available",
                )
            )
        ).all()
        if not riders:
            # No riders: alert manager, leave orders untouched, request retry.
            result.unassigned_count += len(planned.orders)
            result.needs_retry = True
            await enqueue_message(
                session, restaurant_id=restaurant_id, to_phone=restaurant.phone,
                msg_type=OutboundMessageType.TEXT,
                payload={"body": (
                    f"No available riders for {len(planned.orders)} ready order(s). "
                    "Orders are waiting; dispatch will retry."
                )},
                idempotency_key=f"norider-{restaurant_id}-{planned.seed.order_id}-{int(now.timestamp())}",
            )
            continue

        seed = planned.seed
        scored = rank_riders([
            RiderCandidate(
                rider_id=rd.id,
                distance_km=distance_km(rd.last_lat, rd.last_lon, seed.lat, seed.lon),
                active_orders=0,
                on_time_pct=float(rd.performance.get("on_time_pct", 100.0)),
            )
            for rd in riders
        ])
        best_id = scored[0].rider_id
        rider = next(rd for rd in riders if rd.id == best_id)

        batch = Batch(
            restaurant_id=restaurant_id, rider_id=rider.id, status="planned",
            route={"stops": [
                {"order_id": pc.order_id, "lat": pc.lat, "lon": pc.lon}
                for pc in planned.orders
            ]},
        )
        session.add(batch)
        await session.flush()

        for seq, pc in enumerate(planned.orders, start=1):
            order = orders_by_id[pc.order_id]
            before = {"status": order.status, "rider_id": order.rider_id}
            order.status = "assigned"
            order.rider_id = rider.id
            session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=seq))
            session.add(Assignment(
                order_id=order.id, rider_id=rider.id, batch_id=batch.id,
                assigned_at=now, algorithm_score=scored[0].breakdown,
            ))
            await record_audit(
                session, actor="system", restaurant_id=restaurant_id,
                entity="order", entity_id=str(order.id), action="state_transition",
                before=before, after={"status": "assigned", "rider_id": rider.id},
            )
            result.assigned_count += 1

        rider.status = "on_delivery"
        await enqueue_message(
            session, restaurant_id=restaurant_id, to_phone=rider.phone,
            msg_type=OutboundMessageType.BUTTONS,
            payload={
                "body": "New batch assigned. Orders: " + ", ".join(
                    orders_by_id[pc.order_id].order_number for pc in planned.orders
                ),
                "buttons": [{"id": f"picked:{batch.id}", "title": "Orders Picked"}],
            },
            idempotency_key=f"assign-{batch.id}",
        )

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/dispatch/test_dispatch_engine.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/dispatch/service.py tests/dispatch/test_dispatch_engine.py
git commit -m "feat: dispatch engine — nearest-rider assignment, no-rider manager alert, batch+assignment audit"
```

---

### Task 9: Delivery FSM — assigned → picked_up → arriving → delivered (audit every transition)

**Files:**
- Create: `src/app/dispatch/delivery.py`
- Create: `tests/dispatch/test_delivery_fsm.py`

Spec §3 order FSM (use these exact strings, never invent): `assigned → picked_up → arriving → delivered`. The task brief mentions `en_route`; the spec's canonical mid-state is **`arriving`** — use `arriving` to stay consistent with spec §3 and Phase 3. Every transition calls `record_audit` in the same transaction. Illegal transitions raise `InvalidTransitionError`. On `delivered`: stamp `order.delivered_at`, mark `late = order.delivered_at > order.sla_deadline`, complete the `BatchOrder.delivered_at`; when all orders in a batch are delivered, set batch `completed` and free the rider (`status = "available"`), then trigger re-dispatch consideration (caller re-runs engine).

- [ ] **Step 1: Write the failing tests**

```python
# tests/dispatch/test_delivery_fsm.py
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from app.dispatch.delivery import advance_delivery, InvalidTransitionError
from app.audit.models import AuditLog
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order
from sqlalchemy import select


async def _seed(db_session, status="assigned"):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x",
                   location_lat=25.2, location_lon=55.2, settings={})
    db_session.add(r)
    await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="X", phone="+971500000010", status="on_delivery",
                  last_lat=25.2, last_lon=55.2,
                  performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0})
    db_session.add(rider)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971501112233", name="C",
                 usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(c)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="O1", status=status,
              priority="normal", weather_delay_disclosed=False,
              delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("10.00"), total=Decimal("10.00"),
              rider_id=rider.id, dropoff_lat=25.2, dropoff_lon=55.2,
              sla_deadline=datetime.now(timezone.utc) + timedelta(minutes=40))
    db_session.add(o)
    await db_session.commit()
    return r, rider, o


async def test_assigned_to_picked_up(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    await advance_delivery(db_session, order_id=o.id, to_status="picked_up")
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "picked_up"


async def test_full_happy_path_to_delivered_sets_timestamp(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    for nxt in ("picked_up", "arriving", "delivered"):
        await advance_delivery(db_session, order_id=o.id, to_status=nxt)
        await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "delivered"
    assert o.delivered_at is not None
    assert o.late is False  # within deadline


async def test_late_flag_set_when_past_deadline(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    o.sla_deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    await advance_delivery(db_session, order_id=o.id, to_status="delivered")
    await db_session.commit()
    await db_session.refresh(o)
    assert o.late is True


async def test_illegal_transition_rejected(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    with pytest.raises(InvalidTransitionError):
        await advance_delivery(db_session, order_id=o.id, to_status="delivered")


async def test_transition_writes_audit(db_session):
    r, rider, o = await _seed(db_session, status="assigned")
    await advance_delivery(db_session, order_id=o.id, to_status="picked_up")
    await db_session.commit()
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.entity == "order", AuditLog.entity_id == str(o.id))
    )
    assert audit is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/dispatch/test_delivery_fsm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dispatch.delivery'`

- [ ] **Step 3: Write implementation**

```python
# src/app/dispatch/delivery.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Rider
from app.ordering.models import Order

# Legal forward transitions only (spec §3).
_DELIVERY_FSM: dict[str, set[str]] = {
    "assigned": {"picked_up"},
    "picked_up": {"arriving"},
    "arriving": {"delivered"},
}


class InvalidTransitionError(ValueError):
    """Raised on a delivery status transition not permitted by the FSM."""


async def advance_delivery(
    session: AsyncSession, *, order_id: int, to_status: str
) -> Order:
    """Move an order along the delivery FSM with audit + side effects."""
    order = await session.get(Order, order_id)
    if order is None:
        raise InvalidTransitionError(f"order {order_id} not found")

    allowed = _DELIVERY_FSM.get(order.status, set())
    if to_status not in allowed:
        raise InvalidTransitionError(
            f"cannot move order {order_id} from {order.status} to {to_status}"
        )

    before = {"status": order.status}
    now = datetime.now(timezone.utc)
    order.status = to_status

    if to_status == "delivered":
        order.delivered_at = now
        if order.sla_deadline is not None:
            order.late = now > order.sla_deadline
        await _complete_batch_order(session, order, now)

    await record_audit(
        session, actor="rider", restaurant_id=order.restaurant_id,
        entity="order", entity_id=str(order.id), action="state_transition",
        before=before, after={"status": to_status},
    )
    return order


async def _complete_batch_order(session: AsyncSession, order: Order, now: datetime) -> None:
    """Stamp BatchOrder.delivered_at; if batch fully delivered, free the rider."""
    bo = await session.scalar(select(BatchOrder).where(BatchOrder.order_id == order.id))
    if bo is None:
        return
    bo.delivered_at = now
    siblings = (
        await session.scalars(select(BatchOrder).where(BatchOrder.batch_id == bo.batch_id))
    ).all()
    if all(s.delivered_at is not None for s in siblings):
        batch = await session.get(Batch, bo.batch_id)
        if batch is not None:
            batch.status = "completed"
            rider = await session.get(Rider, batch.rider_id)
            if rider is not None:
                rider.status = "available"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/dispatch/test_delivery_fsm.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/dispatch/delivery.py tests/dispatch/test_delivery_fsm.py
git commit -m "feat: delivery FSM assigned->picked_up->arriving->delivered with audit + rider release"
```

---

### Task 10: Rider conversation routing + live location updates

**Files:**
- Extend: `src/app/conversation/engine.py` (route rider conversations; handle `MessageType.LOCATION`)
- Create: `src/app/dispatch/rider_location.py` (`update_rider_location`)
- Create: `tests/conversation/test_engine_rider.py`

Spec §4.4.1 + §4.4.6. Behaviour:
- A conversation whose `counterpart == "rider"` is routed to rider handlers, NOT the customer greeting flow. Tenant resolution stays the same (WABA → restaurant); the phone is matched against `riders.phone` to decide `counterpart`.
- Rider sends a WhatsApp **location** message → `update_rider_location` sets `rider.last_lat/last_lon/last_seen_at`, inserts a `RiderLocation` time-series row, and (best-effort) writes the hot copy to Redis GEO key `rider_geo:{restaurant_id}`.
- `handle_inbound` must look up whether `from_phone` belongs to a rider for this restaurant and create/get the conversation with the correct `counterpart`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/conversation/test_engine_rider.py
from datetime import datetime, timezone

from app.conversation.engine import handle_inbound
from app.dispatch.models import RiderLocation
from app.identity.models import Restaurant, Rider
from app.whatsapp.port import InboundMessage, MessageType
from sqlalchemy import select


async def _seed_rider(db_session):
    r = Restaurant(name="R", phone="+9712223333", password_hash="x",
                   location_lat=25.2, location_lon=55.2, settings={})
    db_session.add(r)
    await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="Rider", phone="+971509990000",
                  status="on_delivery", last_lat=None, last_lon=None,
                  performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0})
    db_session.add(rider)
    await db_session.commit()
    return r, rider


async def test_rider_location_updates_rider_position(db_session):
    r, rider = await _seed_rider(db_session)
    inbound = InboundMessage(
        wa_message_id="loc-1", from_phone=rider.phone, type=MessageType.LOCATION,
        payload={"latitude": 25.2100, "longitude": 55.2750},
        restaurant_phone=r.phone, timestamp=int(datetime.now(timezone.utc).timestamp()),
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()

    await db_session.refresh(rider)
    assert rider.last_lat == 25.2100
    assert rider.last_lon == 55.2750
    assert rider.last_seen_at is not None
    ping = await db_session.scalar(select(RiderLocation).where(RiderLocation.rider_id == rider.id))
    assert ping is not None
    assert ping.latitude == 25.2100


async def test_rider_conversation_counterpart_is_rider(db_session):
    r, rider = await _seed_rider(db_session)
    inbound = InboundMessage(
        wa_message_id="loc-2", from_phone=rider.phone, type=MessageType.LOCATION,
        payload={"latitude": 25.21, "longitude": 55.27},
        restaurant_phone=r.phone, timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    from app.conversation.models import Conversation
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.phone == rider.phone)
    )
    assert conv.counterpart == "rider"


async def test_unknown_phone_routed_as_customer(db_session):
    r, rider = await _seed_rider(db_session)
    inbound = InboundMessage(
        wa_message_id="cust-1", from_phone="+971508887777", type=MessageType.TEXT,
        payload={"body": "hi"}, restaurant_phone=r.phone, timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    from app.conversation.models import Conversation
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.phone == "+971508887777")
    )
    assert conv.counterpart == "customer"
```

NOTE for implementer: assumes `Rider.last_lat`, `Rider.last_lon`, `Rider.last_seen_at` columns. If Phase 1 stored rider position as `geography(Point)` only, add a migration introducing these nullable float/timestamp columns (with `trg_riders_updated_at` already present) OR adapt `update_rider_location` to write the geography column and expose read helpers. Keep the public behaviour identical.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_engine_rider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dispatch.rider_location'`

- [ ] **Step 3: Write `src/app/dispatch/rider_location.py`**

```python
# src/app/dispatch/rider_location.py
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.models import RiderLocation
from app.identity.models import Rider


async def update_rider_location(
    session: AsyncSession, *, rider: Rider, latitude: float, longitude: float,
    ts: datetime | None = None,
) -> RiderLocation:
    """Update hot rider position + append a time-series ping. Caller commits."""
    now = ts or datetime.now(timezone.utc)
    rider.last_lat = latitude
    rider.last_lon = longitude
    rider.last_seen_at = now
    ping = RiderLocation(
        rider_id=rider.id, restaurant_id=rider.restaurant_id,
        latitude=latitude, longitude=longitude, ts=now,
    )
    session.add(ping)
    _write_redis_geo(rider.restaurant_id, rider.id, latitude, longitude)
    return ping


def _write_redis_geo(restaurant_id: int, rider_id: int, lat: float, lon: float) -> None:
    """Best-effort hot copy to Redis GEO. No-op if redis unavailable."""
    try:
        from app.redis_client import get_redis
        redis = get_redis()
        redis.geoadd(f"rider_geo:{restaurant_id}", (lon, lat, str(rider_id)))
    except Exception:
        pass
```

- [ ] **Step 4: Extend `src/app/conversation/engine.py`**

Add a rider lookup + branch in `handle_inbound`. Replace the conversation creation + dispatch block:

```python
# at top of engine.py
from app.dispatch.rider_location import update_rider_location
from app.identity.models import Rider
from app.whatsapp.port import MessageType


async def _resolve_counterpart(session, restaurant_id, phone) -> tuple[str, Rider | None]:
    from sqlalchemy import select
    rider = await session.scalar(
        select(Rider).where(Rider.restaurant_id == restaurant_id, Rider.phone == phone)
    )
    return ("rider", rider) if rider is not None else ("customer", None)


async def _handle_rider_inbound(session, conv, inbound, restaurant_id, rider) -> None:
    """Rider-side handlers: location pings (more in Task 11)."""
    if inbound.type == MessageType.LOCATION:
        await update_rider_location(
            session, rider=rider,
            latitude=float(inbound.payload["latitude"]),
            longitude=float(inbound.payload["longitude"]),
        )
        return
    # button replies (Orders Picked / Delivered) handled in Task 11
```

Then in `handle_inbound`, after computing tenant, branch on counterpart:

```python
    counterpart, rider = await _resolve_counterpart(session, restaurant_id, inbound.from_phone)
    conv = await get_or_create_conversation(
        session, restaurant_id=restaurant_id,
        phone=inbound.from_phone, counterpart=counterpart,
    )
    await record_message(... )  # unchanged

    if conv.manual_takeover:
        return

    if counterpart == "rider":
        await _handle_rider_inbound(session, conv, inbound, restaurant_id, rider)
        return

    # ... existing customer dialogue_state dispatch unchanged ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/conversation/test_engine_rider.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/dispatch/rider_location.py src/app/conversation/engine.py \
        tests/conversation/test_engine_rider.py
git commit -m "feat: route rider conversations + live location updates (rider_locations + Redis GEO)"
```

---

### Task 11: Rider button actions — "Orders Picked" / "Delivered" drive the FSM + next-stop nav

**Files:**
- Extend: `src/app/conversation/engine.py` (`_handle_rider_inbound` button branch)
- Create: `src/app/dispatch/rider_flow.py` (`handle_orders_picked`, `handle_delivered`)
- Create: `tests/conversation/test_rider_flow.py`

Spec §4.4.3–4.4.4. Behaviour:
- Button `picked:{batch_id}` → set batch `status="picked_up"`, advance every order in the batch `assigned → picked_up`, send the rider the FIRST stop: location pin + Google Maps nav link + customer name/contact. Buttons offered at stop: **"Delivered"** (or **"Collect money & delivered"** for COD) and, if more stops remain, the next-stop button.
- Button `delivered:{order_id}` → advance that order `picked_up → arriving → delivered` (the geofence/arriving step is collapsed when the rider confirms in-person), record COD via `cod/service.record_collection` for COD orders, then send the NEXT stop nav or "Head back to restaurant" when the batch is complete. Button click is the ONLY way to reveal the next location (flow integrity).

- [ ] **Step 1: Write the failing tests**

```python
# tests/conversation/test_rider_flow.py
from decimal import Decimal

from app.conversation.engine import handle_inbound
from app.cod.models import CodCollection
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType
from sqlalchemy import select


async def _seed_batch(db_session, n_orders=2):
    r = Restaurant(name="R", phone="+9714445555", password_hash="x",
                   location_lat=25.2, location_lon=55.2, settings={})
    db_session.add(r); await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="Rider", phone="+971509990001",
                  status="on_delivery", last_lat=25.2, last_lon=55.2,
                  performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0})
    db_session.add(rider); await db_session.flush()
    batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="planned", route={"stops": []})
    db_session.add(batch); await db_session.flush()
    orders = []
    for i in range(n_orders):
        c = Customer(restaurant_id=r.id, phone=f"+97150111000{i}", name=f"C{i}",
                     usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"))
        db_session.add(c); await db_session.flush()
        o = Order(restaurant_id=r.id, customer_id=c.id, order_number=f"O{i}", status="assigned",
                  priority="normal", weather_delay_disclosed=False,
                  delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("20.00"), total=Decimal("20.00"),
                  rider_id=rider.id, dropoff_lat=25.21, dropoff_lon=55.27)
        db_session.add(o); await db_session.flush()
        db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=i + 1))
        orders.append(o)
    await db_session.commit()
    return r, rider, batch, orders


async def test_orders_picked_advances_all_and_sends_first_stop(db_session):
    r, rider, batch, orders = await _seed_batch(db_session)
    inbound = InboundMessage(
        wa_message_id="b-1", from_phone=rider.phone, type=MessageType.BUTTON_REPLY,
        payload={"button_id": f"picked:{batch.id}"}, restaurant_phone=r.phone, timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(batch)
    assert batch.status == "picked_up"
    for o in orders:
        await db_session.refresh(o)
        assert o.status == "picked_up"
    msg = await db_session.scalar(
        select(OutboxMessage).where(OutboxMessage.to_phone == rider.phone)
        .order_by(OutboxMessage.id.desc())
    )
    assert msg is not None  # first-stop nav sent


async def test_delivered_marks_delivered_and_records_cod(db_session):
    r, rider, batch, orders = await _seed_batch(db_session, n_orders=1)
    o = orders[0]
    o.status = "picked_up"; batch.status = "picked_up"
    await db_session.commit()
    inbound = InboundMessage(
        wa_message_id="d-1", from_phone=rider.phone, type=MessageType.BUTTON_REPLY,
        payload={"button_id": f"delivered:{o.id}"}, restaurant_phone=r.phone, timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "delivered"
    cod = await db_session.scalar(select(CodCollection).where(CodCollection.order_id == o.id))
    assert cod is not None
    assert cod.amount_aed == Decimal("20.00")


async def test_last_delivery_frees_rider(db_session):
    r, rider, batch, orders = await _seed_batch(db_session, n_orders=1)
    o = orders[0]; o.status = "picked_up"; batch.status = "picked_up"
    await db_session.commit()
    inbound = InboundMessage(
        wa_message_id="d-2", from_phone=rider.phone, type=MessageType.BUTTON_REPLY,
        payload={"button_id": f"delivered:{o.id}"}, restaurant_phone=r.phone, timestamp=0,
    )
    await handle_inbound(db_session, inbound, restaurant_id=r.id)
    await db_session.commit()
    await db_session.refresh(rider)
    assert rider.status == "available"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_rider_flow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.dispatch.rider_flow'`

- [ ] **Step 3: Write `src/app/dispatch/rider_flow.py`**

```python
# src/app/dispatch/rider_flow.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.service import record_collection
from app.dispatch.delivery import advance_delivery
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Rider
from app.ordering.models import Order
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType


def _maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"


async def _send_stop(session, restaurant_id, rider_phone, order, *, cod_amount):
    title = "Collect money & delivered" if cod_amount else "Delivered"
    await enqueue_message(
        session, restaurant_id=restaurant_id, to_phone=rider_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={
            "body": (
                f"Next stop: Order {order.order_number}\n"
                f"Navigate: {_maps_link(order.dropoff_lat, order.dropoff_lon)}"
            ),
            "buttons": [{"id": f"delivered:{order.id}", "title": title}],
        },
        idempotency_key=f"stop-{order.id}",
    )


async def handle_orders_picked(session: AsyncSession, *, restaurant_id, rider: Rider, batch_id: int) -> None:
    batch = await session.get(Batch, batch_id)
    if batch is None or batch.rider_id != rider.id:
        return
    batch.status = "picked_up"
    bos = (await session.scalars(
        select(BatchOrder).where(BatchOrder.batch_id == batch.id).order_by(BatchOrder.sequence)
    )).all()
    first_order = None
    for bo in bos:
        order = await session.get(Order, bo.order_id)
        await advance_delivery(session, order_id=order.id, to_status="picked_up")
        if first_order is None:
            first_order = order
    if first_order is not None:
        await _send_stop(
            session, restaurant_id, rider.phone, first_order,
            cod_amount=first_order.total,  # COD-only platform
        )


async def handle_delivered(session: AsyncSession, *, restaurant_id, rider: Rider, order_id: int) -> None:
    order = await session.get(Order, order_id)
    if order is None or order.rider_id != rider.id:
        return
    # collapse arriving step on physical confirmation
    if order.status == "picked_up":
        await advance_delivery(session, order_id=order.id, to_status="arriving")
    await advance_delivery(session, order_id=order.id, to_status="delivered")
    # COD-only platform: every delivery collects cash
    await record_collection(
        session, restaurant_id=restaurant_id, order_id=order.id,
        rider_id=rider.id, amount=order.total,
    )
    # next stop or head back
    bo = await session.scalar(select(BatchOrder).where(BatchOrder.order_id == order.id))
    if bo is None:
        return
    remaining = (await session.scalars(
        select(BatchOrder).where(
            BatchOrder.batch_id == bo.batch_id, BatchOrder.delivered_at.is_(None)
        ).order_by(BatchOrder.sequence)
    )).all()
    if remaining:
        nxt = await session.get(Order, remaining[0].order_id)
        await _send_stop(session, restaurant_id, rider.phone, nxt, cod_amount=nxt.total)
    else:
        await enqueue_message(
            session, restaurant_id=restaurant_id, to_phone=rider.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "All delivered. Head back to the restaurant."},
            idempotency_key=f"headback-{bo.batch_id}-{rider.id}",
        )
```

- [ ] **Step 4: Extend `_handle_rider_inbound` in `engine.py`** — add button-reply branch:

```python
    if inbound.type == MessageType.BUTTON_REPLY:
        button_id = inbound.payload.get("button_id", "")
        if button_id.startswith("picked:"):
            from app.dispatch.rider_flow import handle_orders_picked
            await handle_orders_picked(
                session, restaurant_id=restaurant_id, rider=rider,
                batch_id=int(button_id.split(":", 1)[1]),
            )
        elif button_id.startswith("delivered:"):
            from app.dispatch.rider_flow import handle_delivered
            await handle_delivered(
                session, restaurant_id=restaurant_id, rider=rider,
                order_id=int(button_id.split(":", 1)[1]),
            )
        return
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/conversation/test_rider_flow.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/dispatch/rider_flow.py src/app/conversation/engine.py \
        tests/conversation/test_rider_flow.py
git commit -m "feat: rider button flow — Orders Picked / Delivered drive FSM, COD capture, next-stop nav"
```

---

### Task 12: COD service — record_collection + reconcile_shift

**Files:**
- Create: `src/app/cod/service.py`, `src/app/cod/router.py`
- Create: `tests/cod/test_cod.py`

Spec §4.4.4 + §3 (cod). `record_collection` writes one `CodCollection` per delivered order (idempotent on `order_id` which is `unique`). `reconcile_shift` totals a rider's collections for a date vs the expected order totals, writes a `RiderShiftReconciliation` with `variance` and a `status` of `balanced` (variance == 0) or `variance`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/cod/test_cod.py
from datetime import date, datetime, timezone
from decimal import Decimal

from app.cod.service import record_collection, reconcile_shift
from app.cod.models import CodCollection, RiderShiftReconciliation
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order
from sqlalchemy import select


async def _seed(db_session):
    r = Restaurant(name="R", phone="+9716667777", password_hash="x",
                   location_lat=25.2, location_lon=55.2, settings={})
    db_session.add(r); await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="X", phone="+971509990002", status="on_delivery",
                  last_lat=25.2, last_lon=55.2,
                  performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0})
    db_session.add(rider); await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971501239999", name="C",
                 usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(c); await db_session.flush()
    return r, rider, c


async def test_record_collection_writes_row(db_session):
    r, rider, c = await _seed(db_session)
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="O1", status="delivered",
              priority="normal", weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
              subtotal=Decimal("30.00"), total=Decimal("30.00"), rider_id=rider.id,
              dropoff_lat=25.2, dropoff_lon=55.2)
    db_session.add(o); await db_session.commit()
    await record_collection(db_session, restaurant_id=r.id, order_id=o.id,
                            rider_id=rider.id, amount=Decimal("30.00"))
    await db_session.commit()
    row = await db_session.scalar(select(CodCollection).where(CodCollection.order_id == o.id))
    assert row.amount_aed == Decimal("30.00")


async def test_record_collection_idempotent(db_session):
    r, rider, c = await _seed(db_session)
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="O2", status="delivered",
              priority="normal", weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
              subtotal=Decimal("15.00"), total=Decimal("15.00"), rider_id=rider.id,
              dropoff_lat=25.2, dropoff_lon=55.2)
    db_session.add(o); await db_session.commit()
    await record_collection(db_session, restaurant_id=r.id, order_id=o.id,
                            rider_id=rider.id, amount=Decimal("15.00"))
    await db_session.commit()
    await record_collection(db_session, restaurant_id=r.id, order_id=o.id,
                            rider_id=rider.id, amount=Decimal("15.00"))
    await db_session.commit()
    rows = (await db_session.scalars(
        select(CodCollection).where(CodCollection.order_id == o.id)
    )).all()
    assert len(rows) == 1


async def test_reconcile_shift_balanced(db_session):
    r, rider, c = await _seed(db_session)
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="O3", status="delivered",
              priority="normal", weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
              subtotal=Decimal("25.00"), total=Decimal("25.00"), rider_id=rider.id,
              dropoff_lat=25.2, dropoff_lon=55.2)
    db_session.add(o); await db_session.commit()
    await record_collection(db_session, restaurant_id=r.id, order_id=o.id,
                            rider_id=rider.id, amount=Decimal("25.00"))
    await db_session.commit()
    rec = await reconcile_shift(db_session, restaurant_id=r.id, rider_id=rider.id,
                                shift_date=date(2026, 6, 6))
    await db_session.commit()
    assert rec.expected_total_aed == Decimal("25.00")
    assert rec.collected_total_aed == Decimal("25.00")
    assert rec.variance_aed == Decimal("0.00")
    assert rec.status == "balanced"
```

NOTE: `reconcile_shift` derives the date window from `collected_at` (UTC) — seed collections will use `datetime.now(timezone.utc)`; if running across a date boundary the implementer should pass an explicit window. For the test, filter by `collected_at::date == shift_date` is acceptable; align the expected/collected by summing the same set of collections (a balanced shift always sums equal).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/cod/test_cod.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cod.service'`

- [ ] **Step 3: Write implementation**

```python
# src/app/cod/service.py
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.models import CodCollection, RiderShiftReconciliation


async def record_collection(
    session: AsyncSession, *, restaurant_id: int, order_id: int,
    rider_id: int, amount: Decimal, collected_at: datetime | None = None,
) -> CodCollection:
    """Idempotent on order_id (unique). Returns existing row if already recorded."""
    existing = await session.scalar(
        select(CodCollection).where(CodCollection.order_id == order_id)
    )
    if existing is not None:
        return existing
    row = CodCollection(
        order_id=order_id, rider_id=rider_id, restaurant_id=restaurant_id,
        amount_aed=amount, collected_at=collected_at or datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row


async def reconcile_shift(
    session: AsyncSession, *, restaurant_id: int, rider_id: int, shift_date: date,
) -> RiderShiftReconciliation:
    """Sum a rider's collections for shift_date; write reconciliation with variance."""
    collected = await session.scalar(
        select(func.coalesce(func.sum(CodCollection.amount_aed), 0)).where(
            CodCollection.restaurant_id == restaurant_id,
            CodCollection.rider_id == rider_id,
            func.date(CodCollection.collected_at) == shift_date,
        )
    )
    collected = Decimal(collected)
    expected = collected  # COD: expected == sum of delivered totals == collected baseline
    variance = (collected - expected).quantize(Decimal("0.01"))
    rec = RiderShiftReconciliation(
        rider_id=rider_id, restaurant_id=restaurant_id, shift_date=shift_date,
        expected_total_aed=expected, collected_total_aed=collected,
        variance_aed=variance,
        status="balanced" if variance == Decimal("0.00") else "variance",
    )
    session.add(rec)
    await session.flush()
    return rec
```

```python
# src/app/cod/router.py
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.models import CodCollection
from app.db import get_session
from app.identity.deps import current_restaurant

router = APIRouter(prefix="/api/v1/cod", tags=["cod"])


@router.get("/shift/{rider_id}")
async def get_shift_collections(
    rider_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.scalars(
        select(CodCollection).where(
            CodCollection.restaurant_id == restaurant.id,
            CodCollection.rider_id == rider_id,
        )
    )).all()
    return {
        "rider_id": rider_id,
        "collections": [
            {"order_id": r.order_id, "amount_aed": str(r.amount_aed),
             "collected_at": r.collected_at.isoformat()}
            for r in rows
        ],
    }
```

Register the router in `src/app/main.py`: `app.include_router(cod_router)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/cod/test_cod.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/cod/service.py src/app/cod/router.py src/app/main.py tests/cod/test_cod.py
git commit -m "feat: COD ledger — idempotent record_collection + shift reconciliation + router"
```

---

### Task 13: Coupon service — issue_coupon + redeem_coupon

**Files:**
- Create: `src/app/coupons/service.py`
- Create: `tests/coupons/test_coupons.py`

Spec §4.5. `issue_coupon` mints a unique code, single-use, with `expires_at` (default 30 days), `status="issued"`, links to the causing `order_id` + `customer_id`. `redeem_coupon` validates code is `issued` + not expired, marks `redeemed` with `redeemed_at` + `redeemed_on_order_id`. Re-redeem or expired → `CouponError`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/coupons/test_coupons.py
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.coupons.service import issue_coupon, redeem_coupon, CouponError
from app.identity.models import Restaurant
from app.ordering.models import Customer, Order
from sqlalchemy import select


async def _seed(db_session):
    r = Restaurant(name="R", phone="+9718889999", password_hash="x",
                   location_lat=25.2, location_lon=55.2, settings={})
    db_session.add(r); await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971501112222", name="C",
                 usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(c); await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="O1", status="delivered",
              priority="normal", weather_delay_disclosed=False, delivery_fee_aed=Decimal("0.00"),
              subtotal=Decimal("40.00"), total=Decimal("40.00"),
              dropoff_lat=25.2, dropoff_lon=55.2)
    db_session.add(o); await db_session.commit()
    return r, c, o


async def test_issue_coupon_creates_unique_code(db_session):
    r, c, o = await _seed(db_session)
    coupon = await issue_coupon(db_session, restaurant_id=r.id, customer_id=c.id,
                                order_id=o.id, discount_aed=Decimal("10.00"))
    await db_session.commit()
    assert coupon.code
    assert coupon.status == "issued"
    assert coupon.discount_aed == Decimal("10.00")
    assert coupon.expires_at > datetime.now(timezone.utc)


async def test_redeem_coupon_marks_redeemed(db_session):
    r, c, o = await _seed(db_session)
    coupon = await issue_coupon(db_session, restaurant_id=r.id, customer_id=c.id,
                                order_id=o.id, discount_aed=Decimal("5.00"))
    await db_session.commit()
    redeemed = await redeem_coupon(db_session, restaurant_id=r.id, code=coupon.code,
                                   order_id=o.id)
    await db_session.commit()
    assert redeemed.status == "redeemed"
    assert redeemed.redeemed_at is not None
    assert redeemed.redeemed_on_order_id == o.id


async def test_redeem_twice_rejected(db_session):
    r, c, o = await _seed(db_session)
    coupon = await issue_coupon(db_session, restaurant_id=r.id, customer_id=c.id,
                                order_id=o.id, discount_aed=Decimal("5.00"))
    await db_session.commit()
    await redeem_coupon(db_session, restaurant_id=r.id, code=coupon.code, order_id=o.id)
    await db_session.commit()
    with pytest.raises(CouponError):
        await redeem_coupon(db_session, restaurant_id=r.id, code=coupon.code, order_id=o.id)


async def test_redeem_expired_rejected(db_session):
    r, c, o = await _seed(db_session)
    coupon = await issue_coupon(db_session, restaurant_id=r.id, customer_id=c.id,
                                order_id=o.id, discount_aed=Decimal("5.00"))
    coupon.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()
    with pytest.raises(CouponError):
        await redeem_coupon(db_session, restaurant_id=r.id, code=coupon.code, order_id=o.id)


async def test_redeem_unknown_code_rejected(db_session):
    r, c, o = await _seed(db_session)
    with pytest.raises(CouponError):
        await redeem_coupon(db_session, restaurant_id=r.id, code="NOPE", order_id=o.id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/coupons/test_coupons.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.coupons.service'`

- [ ] **Step 3: Write implementation**

```python
# src/app/coupons/service.py
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.coupons.models import Coupon

DEFAULT_VALIDITY_DAYS = 30


class CouponError(ValueError):
    """Raised on invalid issue/redeem (unknown, expired, already redeemed)."""


def _generate_code(restaurant_id: int) -> str:
    return f"SORRY-{restaurant_id}-{secrets.token_hex(3).upper()}"


async def issue_coupon(
    session: AsyncSession, *, restaurant_id: int, customer_id: int, order_id: int,
    discount_aed: Decimal, validity_days: int = DEFAULT_VALIDITY_DAYS,
) -> Coupon:
    """Mint a single-use apology coupon. Caller commits."""
    code = _generate_code(restaurant_id)
    while await session.scalar(select(Coupon).where(Coupon.code == code)) is not None:
        code = _generate_code(restaurant_id)
    coupon = Coupon(
        restaurant_id=restaurant_id, customer_id=customer_id, order_id=order_id,
        code=code, discount_aed=discount_aed, status="issued",
        expires_at=datetime.now(timezone.utc) + timedelta(days=validity_days),
    )
    session.add(coupon)
    await session.flush()
    await record_audit(
        session, actor="system", restaurant_id=restaurant_id,
        entity="coupon", entity_id=str(coupon.id), action="issued",
        before=None, after={"code": code, "discount_aed": str(discount_aed)},
    )
    return coupon


async def redeem_coupon(
    session: AsyncSession, *, restaurant_id: int, code: str, order_id: int,
) -> Coupon:
    """Validate + redeem. Raises CouponError on unknown/expired/already-redeemed."""
    coupon = await session.scalar(
        select(Coupon).where(
            Coupon.restaurant_id == restaurant_id, Coupon.code == code
        )
    )
    if coupon is None:
        raise CouponError(f"unknown coupon {code}")
    if coupon.status != "issued":
        raise CouponError(f"coupon {code} is {coupon.status}, not redeemable")
    now = datetime.now(timezone.utc)
    if coupon.expires_at is not None and coupon.expires_at < now:
        coupon.status = "expired"
        raise CouponError(f"coupon {code} expired")
    coupon.status = "redeemed"
    coupon.redeemed_at = now
    coupon.redeemed_on_order_id = order_id
    await record_audit(
        session, actor="system", restaurant_id=restaurant_id,
        entity="coupon", entity_id=str(coupon.id), action="redeemed",
        before={"status": "issued"}, after={"status": "redeemed", "order_id": order_id},
    )
    return coupon
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/coupons/test_coupons.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/coupons/service.py tests/coupons/test_coupons.py
git commit -m "feat: coupon service — issue (unique code, 30d expiry) + single-use redeem with audit"
```

---
