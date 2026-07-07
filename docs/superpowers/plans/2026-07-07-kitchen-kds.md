# Kitchen/KDS Implementation Plan

> **For agentic workers:** Execute task-by-task, TDD, commit per task.

**Goal:** Native Kitchen Display System — station-scoped tickets, per-item bump/recall, printer job queue — backing the desktop shell's next screen.

**Architecture:** New `src/app/kds/` bounded context (models/schemas/service/router) following the existing module pattern (see `cod`/`wallet`). Station resolution: `dishes.station_id` → `category_station_defaults` lookup by `dishes.category` string → a restaurant's auto-created "Main" station. `print_jobs` mirrors `outbox_messages`' retry/dead-letter shape exactly.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, pytest — same stack as every other module.

## Global Constraints

- Multi-tenant: every new table carries `restaurant_id` + index.
- Audit every kitchen status transition via `record_audit(session, actor=..., entity="order_item", entity_id=str(item.id), action=..., restaurant_id=..., before=..., after=...)` — same transaction, never commits itself.
- No deletions: bump/recall are status transitions, never row deletes.
- TDD: failing test first.
- New `TimestampMixin` tables need a `BEFORE UPDATE` trigger `trg_<table>_updated_at` in the same migration (see `updated_at_triggers` migration for the pattern).
- New model modules imported in BOTH `alembic/env.py` and `tests/conftest.py`.
- Money: N/A this module (no currency fields except none needed). Time zone: UTC in DB, tz-aware datetimes.
- Commit per task, conventional-commit style.

---

### Task 1: Models + migration

**Files:**
- Create: `src/app/kds/__init__.py` (empty)
- Create: `src/app/kds/models.py`
- Modify: `src/app/menu/models.py` (add `station_id`, `prep_minutes` to `Dish`)
- Modify: `src/app/ordering/models.py` (add `kitchen_status`, `bumped_at`, `station_id_snapshot` to `OrderItem`)
- Modify: `alembic/env.py`, `tests/conftest.py` (import `app.kds.models`)
- Create: `alembic/versions/<rev>_kds_tables.py`

**Interfaces:**
- Produces: `KitchenStation`, `CategoryStationDefault`, `PrintJob` models; `Dish.station_id`/`prep_minutes`; `OrderItem.kitchen_status`/`bumped_at`/`station_id_snapshot`.

- [ ] Write `src/app/kds/models.py`:

```python
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class KitchenStation(Base, TimestampMixin):
    __tablename__ = "kitchen_stations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    printer_ip: Mapped[str | None] = mapped_column(String(64))
    printer_port: Mapped[int | None] = mapped_column(Integer)


class CategoryStationDefault(Base, TimestampMixin):
    __tablename__ = "category_station_defaults"
    __table_args__ = (UniqueConstraint("restaurant_id", "category"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    category: Mapped[str] = mapped_column(String(128))
    station_id: Mapped[int] = mapped_column(ForeignKey("kitchen_stations.id"))


class PrintJob(Base, TimestampMixin):
    __tablename__ = "print_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("kitchen_stations.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] Add to `src/app/menu/models.py`'s `Dish` class (near `category`):
```python
    station_id: Mapped[int | None] = mapped_column(ForeignKey("kitchen_stations.id"))
    prep_minutes: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
```
(check `Decimal`/`Numeric` already imported in that file; if not add `from decimal import Decimal` and extend the existing `sqlalchemy` import line.)

- [ ] Add to `src/app/ordering/models.py`'s `OrderItem` class:
```python
    kitchen_status: Mapped[str] = mapped_column(String(16), default="received")
    bumped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    station_id_snapshot: Mapped[int | None] = mapped_column(ForeignKey("kitchen_stations.id"))
```
(check `DateTime`/`datetime` already imported; add if not.)

- [ ] Add `import app.kds.models  # noqa: E402,F401` to `alembic/env.py` and `tests/conftest.py` next to the other model imports.

- [ ] Generate migration: `.venv/bin/alembic revision --autogenerate -m "kds tables"`. Edit the generated file to add triggers for all 3 new tables plus the two altered tables' `updated_at` is unaffected (dishes/order_items already have their trigger from an earlier migration — only add triggers for the 3 NEW tables):
```python
def upgrade() -> None:
    # ... autogenerated create_table x3, add_column x5 ...
    for tbl in ("kitchen_stations", "category_station_defaults", "print_jobs"):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ("kitchen_stations", "category_station_defaults", "print_jobs"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")
    # ... autogenerated drop_column x5, drop_table x3 ...
```

- [ ] Run: `.venv/bin/alembic upgrade head` — must succeed with no errors.
- [ ] Run: `.venv/bin/pytest -q` (full suite) — must still be 100% green (no test touches these new nullable columns yet).
- [ ] Commit: `git add src/app/kds src/app/menu/models.py src/app/ordering/models.py alembic/ tests/conftest.py && git commit -m "feat: KDS tables (kitchen_stations, category_station_defaults, print_jobs)"`

---

### Task 2: Station resolution service

**Files:**
- Create: `src/app/kds/service.py`
- Test: `tests/kds/__init__.py` (empty), `tests/kds/test_service.py`

**Interfaces:**
- Consumes: `KitchenStation`, `CategoryStationDefault` (Task 1).
- Produces: `async def resolve_station(session, *, restaurant_id: int, dish) -> int` (returns station_id, creating a "Main" fallback station on first use per restaurant); `async def get_or_create_main_station(session, *, restaurant_id: int) -> KitchenStation`.

- [ ] Write `tests/kds/test_service.py`:
```python
import pytest
from app.kds.models import CategoryStationDefault, KitchenStation
from app.kds.service import resolve_station


@pytest.mark.anyio
async def test_resolve_station_uses_dish_override_first(db_session, restaurant):
    grill = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    cold = KitchenStation(restaurant_id=restaurant.id, name="Cold")
    db_session.add_all([grill, cold])
    await db_session.flush()
    db_session.add(CategoryStationDefault(restaurant_id=restaurant.id, category="Mains", station_id=cold.id))
    await db_session.commit()

    class FakeDish:
        station_id = grill.id
        category = "Mains"

    result = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    assert result == grill.id  # dish override wins over category default


@pytest.mark.anyio
async def test_resolve_station_falls_back_to_category_default(db_session, restaurant):
    cold = KitchenStation(restaurant_id=restaurant.id, name="Cold")
    db_session.add(cold)
    await db_session.flush()
    db_session.add(CategoryStationDefault(restaurant_id=restaurant.id, category="Salads", station_id=cold.id))
    await db_session.commit()

    class FakeDish:
        station_id = None
        category = "Salads"

    result = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    assert result == cold.id


@pytest.mark.anyio
async def test_resolve_station_falls_back_to_main_when_nothing_configured(db_session, restaurant):
    class FakeDish:
        station_id = None
        category = "Unmapped Category"

    result = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    main = db_session.get(KitchenStation, result)
    assert (await main).name == "Main"


@pytest.mark.anyio
async def test_resolve_station_reuses_existing_main_station(db_session, restaurant):
    class FakeDish:
        station_id = None
        category = None

    first = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    second = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    assert first == second  # doesn't create a duplicate "Main" station each call
```
- [ ] Run: `.venv/bin/pytest tests/kds/test_service.py -v` — expect FAIL (`ModuleNotFoundError: app.kds.service`).
- [ ] Write `src/app/kds/service.py`:
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kds.models import CategoryStationDefault, KitchenStation


async def get_or_create_main_station(session: AsyncSession, *, restaurant_id: int) -> KitchenStation:
    existing = await session.scalar(
        select(KitchenStation).where(
            KitchenStation.restaurant_id == restaurant_id, KitchenStation.name == "Main"
        )
    )
    if existing is not None:
        return existing
    station = KitchenStation(restaurant_id=restaurant_id, name="Main")
    session.add(station)
    await session.flush()
    return station


async def resolve_station(session: AsyncSession, *, restaurant_id: int, dish) -> int:
    """dish override -> category default -> auto-created 'Main' fallback."""
    if dish.station_id is not None:
        return dish.station_id
    if dish.category:
        default = await session.scalar(
            select(CategoryStationDefault).where(
                CategoryStationDefault.restaurant_id == restaurant_id,
                CategoryStationDefault.category == dish.category,
            )
        )
        if default is not None:
            return default.station_id
    main = await get_or_create_main_station(session, restaurant_id=restaurant_id)
    return main.id
```
- [ ] Run: `.venv/bin/pytest tests/kds/test_service.py -v` — expect PASS (4/4).
- [ ] Commit: `git add src/app/kds/service.py tests/kds && git commit -m "feat: KDS station resolution (dish override -> category default -> Main fallback)"`

---

### Task 3: Ticket creation on order confirm + print_jobs enqueue

**Files:**
- Modify: `src/app/kds/service.py` (add `create_tickets_for_order`)
- Modify: `src/app/ordering/service.py` — find the function that transitions an order to `confirmed` (grep `def finalize_confirmation` or the FSM transition call site) and call the new function there, same transaction
- Test: `tests/kds/test_ticket_creation.py`

**Interfaces:**
- Consumes: `resolve_station` (Task 2); `Order`, `OrderItem`, `Dish` (existing).
- Produces: `async def create_tickets_for_order(session, *, restaurant_id: int, order) -> None` — sets each `order_item.kitchen_status='received'` + `station_id_snapshot`, enqueues one `PrintJob` per distinct station touched (payload = a simple text ticket: order number + item lines for that station).

- [ ] Write `tests/kds/test_ticket_creation.py`:
```python
import pytest
from sqlalchemy import select
from app.kds.models import KitchenStation, PrintJob
from app.kds.service import create_tickets_for_order
from app.menu.models import Dish, Menu
from app.ordering.models import Customer, Order, OrderItem
from decimal import Decimal


@pytest.mark.anyio
async def test_create_tickets_sets_status_and_snapshot_and_enqueues_print_jobs(db_session, restaurant):
    grill = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    db_session.add(grill)
    await db_session.flush()

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), category="Grills", is_available=True,
        name_normalized="kebab", station_id=grill.id,
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000099", name="Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="T-0001",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=1,
    )
    db_session.add(item)
    await db_session.commit()

    await create_tickets_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.commit()

    await db_session.refresh(item)
    assert item.kitchen_status == "received"
    assert item.station_id_snapshot == grill.id

    jobs = (await db_session.scalars(
        select(PrintJob).where(PrintJob.order_id == order.id)
    )).all()
    assert len(jobs) == 1
    assert jobs[0].station_id == grill.id
    assert jobs[0].status == "pending"
    assert "Kebab" in jobs[0].payload
    assert "T-0001" in jobs[0].payload
```
- [ ] Run: FAIL (`create_tickets_for_order` doesn't exist).
- [ ] Add to `src/app/kds/service.py`:
```python
from collections import defaultdict
from datetime import datetime, timezone

from app.kds.models import PrintJob
from app.menu.models import Dish
from app.ordering.models import OrderItem


async def create_tickets_for_order(session: AsyncSession, *, restaurant_id: int, order) -> None:
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    by_station: dict[int, list[OrderItem]] = defaultdict(list)
    for item in items:
        dish = await session.get(Dish, item.dish_id)
        station_id = await resolve_station(session, restaurant_id=restaurant_id, dish=dish)
        item.kitchen_status = "received"
        item.station_id_snapshot = station_id
        by_station[station_id].append(item)

    for station_id, station_items in by_station.items():
        lines = "\n".join(
            f"{i.qty}x {i.dish_name}" + (f" ({i.variant_name})" if i.variant_name else "")
            for i in station_items
        )
        payload = f"Order {order.order_number}\n{lines}"
        session.add(PrintJob(
            restaurant_id=restaurant_id, station_id=station_id, order_id=order.id,
            payload=payload, status="pending",
        ))
```
- [ ] Run: PASS.
- [ ] Find the order-confirm call site: `grep -n "def finalize_confirmation" src/app/ordering/service.py`. Read the function, find where `order.status` is set to `confirmed` (or the FSM `transition(... "confirmed")` call), and add immediately after (same transaction, before any commit in that function):
```python
    from app.kds.service import create_tickets_for_order
    await create_tickets_for_order(session, restaurant_id=order.restaurant_id, order=order)
```
(Read the actual function first — match indentation/imports to what's already there; don't guess blind. If `finalize_confirmation` doesn't exist under that name, grep for where `OrderStatus.CONFIRMED` or `"confirmed"` is assigned to `order.status` and hook there instead.)
- [ ] Run full ordering suite: `.venv/bin/pytest tests/ordering/ tests/kds/ -q` — must be green, no regression in existing confirm-flow tests.
- [ ] Commit: `git add src/app/kds/service.py src/app/ordering/service.py tests/kds/test_ticket_creation.py && git commit -m "feat: create kitchen tickets + print jobs when an order is confirmed"`

---

### Task 4: Schemas + router (stations, tickets, bump/recall, print-job polling)

**Files:**
- Create: `src/app/kds/schemas.py`
- Create: `src/app/kds/router.py`
- Modify: `src/app/main.py` (register `kds_router`)
- Test: `tests/kds/test_router.py`

**Interfaces:**
- Consumes: `resolve_station`, `create_tickets_for_order` (Tasks 2-3); `record_audit` (existing `app.audit.service`).
- Produces: the 6 endpoints listed in the spec's §4.

- [ ] Write `src/app/kds/schemas.py`:
```python
from pydantic import BaseModel, ConfigDict


class StationIn(BaseModel):
    name: str
    printer_ip: str | None = None
    printer_port: int | None = None


class StationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    printer_ip: str | None
    printer_port: int | None


class TicketItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    dish_name: str
    variant_name: str | None
    qty: int
    kitchen_status: str
    notes: str | None


class PrintJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    station_id: int
    order_id: int
    payload: str
    status: str
```

- [ ] Write `tests/kds/test_router.py`:
```python
import pytest


@pytest.mark.anyio
async def test_create_station_and_list(client, auth_headers):
    resp = await client.post(
        "/api/v1/kds/stations", json={"name": "Grill"}, headers=auth_headers,
    )
    assert resp.status_code == 201
    station_id = resp.json()["id"]

    listing = await client.get("/api/v1/kds/stations", headers=auth_headers)
    assert listing.status_code == 200
    assert any(s["id"] == station_id for s in listing.json())


@pytest.mark.anyio
async def test_bump_then_recall_item(client, auth_headers, db_session, restaurant):
    from app.kds.models import KitchenStation
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem
    from decimal import Decimal

    station = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    db_session.add(station)
    await db_session.flush()
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), category="Grills", is_available=True,
        name_normalized="kebab", station_id=station.id,
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000098", name="Test2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="T-0002",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=1, kitchen_status="received",
        station_id_snapshot=station.id,
    )
    db_session.add(item)
    await db_session.commit()

    bump = await client.patch(f"/api/v1/kds/items/{item.id}/bump", headers=auth_headers)
    assert bump.status_code == 200
    assert bump.json()["kitchen_status"] == "ready"

    tickets = await client.get(
        f"/api/v1/kds/stations/{station.id}/tickets", headers=auth_headers
    )
    assert all(t["id"] != item.id for t in tickets.json())  # bumped item no longer "active"

    recall = await client.patch(f"/api/v1/kds/items/{item.id}/recall", headers=auth_headers)
    assert recall.status_code == 200
    assert recall.json()["kitchen_status"] == "received"
```
- [ ] Run: FAIL (module/router doesn't exist).
- [ ] Write `src/app/kds/router.py`:
```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.kds.models import KitchenStation, PrintJob
from app.kds.schemas import PrintJobOut, StationIn, StationOut, TicketItemOut
from app.ordering.models import OrderItem

router = APIRouter(prefix="/api/v1/kds", tags=["kds"])


@router.post("/stations", response_model=StationOut, status_code=status.HTTP_201_CREATED)
async def create_station(
    body: StationIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    station = KitchenStation(restaurant_id=restaurant.id, **body.model_dump())
    session.add(station)
    await session.commit()
    await session.refresh(station)
    return station


@router.get("/stations", response_model=list[StationOut])
async def list_stations(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(KitchenStation).where(KitchenStation.restaurant_id == restaurant.id)
    )
    return list(rows)


@router.get("/stations/{station_id}/tickets", response_model=list[TicketItemOut])
async def station_tickets(
    station_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(OrderItem).where(
            OrderItem.station_id_snapshot == station_id,
            OrderItem.kitchen_status != "bumped",
        )
    )
    return list(rows)


@router.patch("/items/{item_id}/bump", response_model=TicketItemOut)
async def bump_item(
    item_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(OrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    before = {"kitchen_status": item.kitchen_status}
    item.kitchen_status = "ready"
    item.bumped_at = datetime.now(timezone.utc)
    await record_audit(
        session, actor="kitchen", entity="order_item", entity_id=str(item.id),
        action="bump", restaurant_id=restaurant.id, before=before,
        after={"kitchen_status": item.kitchen_status},
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.patch("/items/{item_id}/recall", response_model=TicketItemOut)
async def recall_item(
    item_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    item = await session.get(OrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    before = {"kitchen_status": item.kitchen_status}
    item.kitchen_status = "received"
    item.bumped_at = None
    await record_audit(
        session, actor="kitchen", entity="order_item", entity_id=str(item.id),
        action="recall", restaurant_id=restaurant.id, before=before,
        after={"kitchen_status": item.kitchen_status},
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/print-jobs/pending", response_model=list[PrintJobOut])
async def pending_print_jobs(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(PrintJob).where(
            PrintJob.restaurant_id == restaurant.id, PrintJob.status == "pending",
        )
    )
    return list(rows)


@router.patch("/print-jobs/{job_id}/status", response_model=PrintJobOut)
async def update_print_job_status(
    job_id: int,
    new_status: str,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(PrintJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="print job not found")
    job.status = new_status
    if new_status == "failed":
        job.attempts += 1
    await session.commit()
    await session.refresh(job)
    return job
```
- [ ] Register in `src/app/main.py`: add `from app.kds.router import router as kds_router` near the other module imports, and `app.include_router(kds_router)` near `app.include_router(cod_router)`.
- [ ] Run: `.venv/bin/pytest tests/kds/ -v` — PASS (all router + service tests).
- [ ] Run full suite: `.venv/bin/pytest -q && .venv/bin/ruff check src apps tests` — must be 100% green, ruff clean.
- [ ] Commit: `git add src/app/kds/schemas.py src/app/kds/router.py src/app/main.py tests/kds/test_router.py && git commit -m "feat: KDS station/ticket/bump/recall/print-job REST API"`

---

### Task 5: Desktop KDS screen (frontend)

**Files:**
- Create: `frontend/src/lib/kdsApi.ts`
- Create: `frontend/src/screens/KdsScreen.tsx`
- Create: `frontend/src/screens/KdsScreen.test.tsx`
- Modify: `frontend/src/App.tsx` (add `/kds/:stationId` route)

**Interfaces:**
- Consumes: `apiClient` (existing, already bridge-aware from the desktop shell foundation).
- Produces: `<KdsScreen />` — polls the ticket list every 5s, renders items grouped visually, bump button per item.

- [ ] Write `frontend/src/lib/kdsApi.ts`:
```typescript
import { apiClient } from "./apiClient";

export interface KdsTicketItem {
  id: number;
  order_id: number;
  dish_name: string;
  variant_name: string | null;
  qty: number;
  kitchen_status: string;
  notes: string | null;
}

export function fetchStationTickets(stationId: number) {
  return apiClient.get<KdsTicketItem[]>(`/api/v1/kds/stations/${stationId}/tickets`);
}

export function bumpItem(itemId: number) {
  return apiClient.patch<KdsTicketItem>(`/api/v1/kds/items/${itemId}/bump`);
}
```

- [ ] Write `frontend/src/screens/KdsScreen.test.tsx`:
```typescript
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KdsScreen } from "./KdsScreen";

describe("KdsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (init?.method === "PATCH") {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 1, kitchen_status: "ready" }), { status: 200 }),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify([
              { id: 1, order_id: 10, dish_name: "Kebab", variant_name: null, qty: 2, kitchen_status: "received", notes: null },
            ]),
            { status: 200 },
          ),
        );
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows a ticket and bumps it", async () => {
    render(
      <MemoryRouter initialEntries={["/kds/1"]}>
        <Routes>
          <Route path="/kds/:stationId" element={<KdsScreen />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText(/kebab/i)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /bump/i }));
    await waitFor(() => expect(screen.queryByText(/kebab/i)).not.toBeInTheDocument());
  });
});
```
- [ ] Run: FAIL (`KdsScreen` doesn't exist).
- [ ] Write `frontend/src/screens/KdsScreen.tsx`:
```tsx
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { bumpItem, fetchStationTickets, type KdsTicketItem } from "../lib/kdsApi";

export function KdsScreen() {
  const { stationId } = useParams<{ stationId: string }>();
  const [items, setItems] = useState<KdsTicketItem[]>([]);

  async function reload() {
    if (!stationId) return;
    const rows = await fetchStationTickets(Number(stationId));
    setItems(rows);
  }

  useEffect(() => {
    reload();
    const interval = setInterval(reload, 5000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationId]);

  async function handleBump(itemId: number) {
    await bumpItem(itemId);
    setItems((prev) => prev.filter((i) => i.id !== itemId));
  }

  return (
    <div>
      {items.map((item) => (
        <div key={item.id}>
          <span>
            {item.qty}x {item.dish_name}
            {item.variant_name ? ` (${item.variant_name})` : ""}
          </span>
          <button type="button" onClick={() => handleBump(item.id)}>
            Bump
          </button>
        </div>
      ))}
    </div>
  );
}
```
- [ ] Add the route in `frontend/src/App.tsx` (find the existing `<Routes>` block, add alongside other screen routes): `<Route path="/kds/:stationId" element={<KdsScreen />} />` + the matching import.
- [ ] Run: `cd frontend && npx vitest run src/screens/KdsScreen.test.tsx` — PASS.
- [ ] Run full frontend suite: `npm test -- --run` — must stay 100% green.
- [ ] Commit: `git add frontend/src/lib/kdsApi.ts frontend/src/screens/KdsScreen.tsx frontend/src/screens/KdsScreen.test.tsx frontend/src/App.tsx && git commit -m "feat: desktop KDS screen (station tickets + bump)"`

---

## Self-Review

**Spec coverage:** §2 data model → Task 1. §3 flow (ticket creation, bump/recall, print delivery boundary) → Tasks 2-4; real ESC/POS printer driver + Electron-side polling loop (spec §3 step 4) is **deferred** — this plan delivers the `print_jobs` queue + `GET/PATCH .../print-jobs/...` API only; wiring the Electron main process's `native/printer.ts` stub to actually poll and print is a follow-up task once real printer hardware is available to test against (the stub exists from the desktop-shell-foundation phase precisely for this). §4 API surface → Task 4 (all 6 endpoints). §5 testing → unit (Task 2), integration (Task 3), a router-level test substitutes for full E2E (no simulator wiring in this plan — out of scope, existing simulator doesn't know about kitchen stations yet).

**Placeholder scan:** none found — every step has real code.

**Type consistency:** `resolve_station`/`create_tickets_for_order` signatures match between Tasks 2-3; `KdsTicketItem`/`TicketItemOut` field names match between frontend Task 5 and backend Task 4.
