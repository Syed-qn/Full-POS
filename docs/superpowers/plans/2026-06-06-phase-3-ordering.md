# Phase 3: Ordering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Full customer ordering flow over WhatsApp: fuzzy dish matching, multi-turn item collection, address capture and confirmation, order FSM with transactional state, order modification, cancellation with resale, status replies, and an end-to-end simulator smoke test.

**Architecture:** New `ordering/` bounded context under `src/app/` — models, FSM module, matching, fee calculator, geo helpers, and LLM ports. Conversation engine (Phase 2) extended with new dialogue states that drive all ordering turns. All transitions audited; money is `Decimal`/`Numeric(8,2)` AED throughout.

**Spec:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` §3, §4.2, §4.5

**Prerequisites:** Phase 0+1 (identity, menu, audit, `record_audit`, `get_session`, `current_restaurant`, `TimestampMixin`, `Base`) and Phase 2 (conversation engine with `handle_inbound` signature, `enqueue_message`, `get_or_create_conversation`, `OutboundMessageType`, `MockProvider` pipeline tests) fully executed.

---

## File structure (locked in)

```
src/app/
  geo/
    __init__.py
    haversine.py              pure-function distance_km(lat1, lon1, lat2, lon2) -> float
  ordering/
    __init__.py
    models.py                 Customer, CustomerAddress, Order, OrderItem SQLAlchemy tables
    schemas.py                Pydantic I/O for API responses
    fsm.py                    OrderFSM: explicit transition map, transition(), illegal raises
    matching.py               normalize_name(), find_dish_matches() — pg_trgm + LLM arbiter fallback
    fees.py                   calculate_fee(distance_km, settings) -> Decimal
    service.py                create_order(), add_item(), get_or_create_customer(),
                              upsert_address(), cancel_order(), modify_order()
    router.py                 GET /api/v1/orders/{id}, GET /api/v1/orders (manager list)

  llm/
    port.py                   EXTEND: DescriberPort, IntentClassifierPort, ArbiterPort protocols
    fake.py                   EXTEND: FakeDescriber, FakeIntentClassifier, FakeArbiter
    claude.py                 EXTEND: ClaudeDescriber, ClaudeIntentClassifier, ClaudeArbiter
    factory.py                EXTEND: get_describer(), get_intent_classifier(), get_arbiter()

  conversation/
    engine.py                 EXTEND: collecting_items, address_capture, receiver_details,
                              order_confirmation, order_modification, order_status states

  alembic/versions/
    <hash>_customers_addresses.py
    <hash>_orders_order_items.py
    <hash>_pg_trgm_name_normalized.py

tests/
  ordering/
    __init__.py
    test_fsm.py
    test_matching.py
    test_fees.py
    test_service.py
    test_modification.py
    test_cancellation.py
    test_status_reply.py
  geo/
    __init__.py
    test_haversine.py
  llm/
    test_llm_ordering_ports.py   (append to existing llm tests)
  conversation/
    test_engine_ordering.py      (new file, ordering dialogue states)
  test_simulator_ordering.py     end-to-end smoke via /simulator/send
```

---

### Task 1: `customers` + `customer_addresses` tables

**Files:**
- Create: `src/app/ordering/__init__.py`, `src/app/ordering/models.py` (Customer + CustomerAddress only)
- Modify: `alembic/env.py`, `tests/conftest.py` (register `app.ordering.models`)

- [ ] **Step 1: Write the failing test**

```python
# tests/ordering/__init__.py  (empty)

# tests/ordering/test_service.py  (partial — customer tables only for now)
from sqlalchemy import select
from app.ordering.models import Customer, CustomerAddress


async def test_customer_table_has_expected_columns(db_session):
    c = Customer(
        restaurant_id=1,
        phone="+971501234567",
        name="Ali Hassan",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend="0.00",
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    assert c.id is not None
    assert c.total_orders == 0


async def test_customer_address_table_has_expected_columns(db_session):
    c = Customer(
        restaurant_id=1, phone="+971501234568", name="Sara",
        usual_order_times={}, tags={}, total_orders=0, total_spend="0.00",
    )
    db_session.add(c)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=c.id,
        latitude=25.2048,
        longitude=55.2708,
        room_apartment="111",
        building="1-2",
        receiver_name="Sara",
        additional_details="Blue door",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()
    await db_session.refresh(addr)
    assert addr.id is not None
    assert addr.confirmed is True
    assert addr.last_used_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ordering/test_service.py::test_customer_table_has_expected_columns -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ordering'`

- [ ] **Step 3: Write implementation**

```python
# src/app/ordering/__init__.py
```

```python
# src/app/ordering/models.py  (Customer + CustomerAddress section)
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    Integer, Numeric, String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    first_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # {"0": "12:00", "5": "19:30"} — keyed by weekday int 0=Mon
    usual_order_times: Mapped[dict] = mapped_column(JSONB, default=dict)
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    total_spend: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))


class CustomerAddress(Base, TimestampMixin):
    __tablename__ = "customer_addresses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    # lat/lng stored as plain floats; PostGIS geography column added in logistics phase
    latitude: Mapped[float | None] = mapped_column()
    longitude: Mapped[float | None] = mapped_column()
    room_apartment: Mapped[str | None] = mapped_column(String(128))
    building: Mapped[str | None] = mapped_column(String(128))
    receiver_name: Mapped[str | None] = mapped_column(String(128))
    additional_details: Mapped[str | None] = mapped_column(String(512))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Register in `alembic/env.py` and `tests/conftest.py`** — add:

```python
import app.ordering.models  # noqa: F401
```

- [ ] **Step 5: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "customers_customer_addresses"
.venv/bin/alembic upgrade head
```

Add `BEFORE UPDATE` triggers for both tables in the generated migration body (pattern from existing `updated_at_triggers` migration):

```python
op.execute("""
    CREATE TRIGGER trg_customers_updated_at
    BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
op.execute("""
    CREATE TRIGGER trg_customer_addresses_updated_at
    BEFORE UPDATE ON customer_addresses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ordering/test_service.py -v`
Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/ordering/__init__.py src/app/ordering/models.py \
        alembic/versions/ alembic/env.py tests/conftest.py \
        tests/ordering/__init__.py tests/ordering/test_service.py
git commit -m "feat: customers + customer_addresses tables with migration"
```

---

### Task 2: `orders` + `order_items` tables + `OrderFSM` module

**Files:**
- Extend: `src/app/ordering/models.py` (add Order, OrderItem)
- Create: `src/app/ordering/fsm.py`
- Create: `tests/ordering/test_fsm.py`

- [ ] **Step 1: Write the failing FSM tests**

```python
# tests/ordering/test_fsm.py
import pytest
from app.ordering.fsm import OrderFSM, OrderStatus, IllegalTransitionError


def test_draft_to_pending_confirmation_allowed():
    assert OrderFSM.next_states(OrderStatus.DRAFT) == {OrderStatus.PENDING_CONFIRMATION, OrderStatus.CANCELLED}


def test_pending_confirmation_to_confirmed():
    OrderFSM.validate(OrderStatus.PENDING_CONFIRMATION, OrderStatus.CONFIRMED)  # should not raise


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransitionError):
        OrderFSM.validate(OrderStatus.DRAFT, OrderStatus.DELIVERED)


def test_illegal_transition_from_delivered():
    with pytest.raises(IllegalTransitionError):
        OrderFSM.validate(OrderStatus.DELIVERED, OrderStatus.CONFIRMED)


def test_on_resale_to_resold_allowed():
    OrderFSM.validate(OrderStatus.ON_RESALE, OrderStatus.RESOLD)


def test_on_resale_to_written_off_allowed():
    OrderFSM.validate(OrderStatus.ON_RESALE, OrderStatus.WRITTEN_OFF)


def test_all_statuses_have_entries_in_transition_map():
    """Every OrderStatus must appear as a key in the transition map."""
    for status in OrderStatus:
        assert status in OrderFSM.TRANSITIONS, f"{status} missing from TRANSITIONS"


async def test_transition_helper_audits_and_mutates(db_session):
    """transition() applies new status and writes an audit log row."""
    from decimal import Decimal
    from sqlalchemy import select
    from app.audit.models import AuditLog
    from app.ordering.models import Customer, Order
    from app.ordering.fsm import transition

    customer = Customer(
        restaurant_id=1, phone="+971501230001", name="Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    order = Order(
        restaurant_id=1,
        customer_id=customer.id,
        order_number="R1-0001",
        status=OrderStatus.DRAFT,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("0.00"),
        total=Decimal("0.00"),
    )
    db_session.add(order)
    await db_session.flush()

    await transition(db_session, order, OrderStatus.PENDING_CONFIRMATION, actor="system")
    await db_session.commit()

    assert order.status == OrderStatus.PENDING_CONFIRMATION

    log = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(r.action == "order_status_transition" for r in log)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ordering/test_fsm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ordering.fsm'`

- [ ] **Step 3: Write `src/app/ordering/fsm.py`**

```python
# src/app/ordering/fsm.py
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.ordering.models import Order


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    ARRIVING = "arriving"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    UNDELIVERABLE = "undeliverable"
    ON_RESALE = "on_resale"
    RESOLD = "resold"
    WRITTEN_OFF = "written_off"


class IllegalTransitionError(Exception):
    """Raised when a state transition is not permitted by the FSM."""


class OrderFSM:
    # Explicit adjacency map — every status present as a key.
    TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
        OrderStatus.DRAFT: {
            OrderStatus.PENDING_CONFIRMATION,
            OrderStatus.CANCELLED,
        },
        OrderStatus.PENDING_CONFIRMATION: {
            OrderStatus.CONFIRMED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.CONFIRMED: {
            OrderStatus.PREPARING,
            OrderStatus.CANCELLED,
        },
        OrderStatus.PREPARING: {
            OrderStatus.READY,
            # post-cooking cancellation → on_resale (FSM allows it; service layer decides)
            OrderStatus.ON_RESALE,
        },
        OrderStatus.READY: {
            OrderStatus.ASSIGNED,
        },
        OrderStatus.ASSIGNED: {
            OrderStatus.PICKED_UP,
        },
        OrderStatus.PICKED_UP: {
            OrderStatus.ARRIVING,
            OrderStatus.UNDELIVERABLE,
        },
        OrderStatus.ARRIVING: {
            OrderStatus.DELIVERED,
            OrderStatus.UNDELIVERABLE,
        },
        OrderStatus.DELIVERED: set(),
        OrderStatus.CANCELLED: set(),
        OrderStatus.UNDELIVERABLE: set(),
        OrderStatus.ON_RESALE: {
            OrderStatus.RESOLD,
            OrderStatus.WRITTEN_OFF,
        },
        OrderStatus.RESOLD: set(),
        OrderStatus.WRITTEN_OFF: set(),
    }

    @classmethod
    def next_states(cls, current: OrderStatus) -> set[OrderStatus]:
        return cls.TRANSITIONS.get(current, set())

    @classmethod
    def validate(cls, current: OrderStatus, new: OrderStatus) -> None:
        """Raise IllegalTransitionError if the transition is not in the map."""
        allowed = cls.TRANSITIONS.get(current, set())
        if new not in allowed:
            raise IllegalTransitionError(
                f"Cannot transition order from {current!r} to {new!r}. "
                f"Allowed: {sorted(s.value for s in allowed)}"
            )


async def transition(
    session: "AsyncSession",
    order: "Order",
    new_status: OrderStatus,
    actor: str,
    extra_audit: dict | None = None,
) -> None:
    """Validate, apply, and audit a single order status transition.

    The caller MUST commit the session after this returns.
    """
    from app.audit.service import record_audit

    OrderFSM.validate(order.status, new_status)  # raises on illegal
    before = order.status
    order.status = new_status
    await record_audit(
        session,
        actor=actor,
        restaurant_id=order.restaurant_id,
        entity="order",
        entity_id=str(order.id),
        action="order_status_transition",
        before={"status": str(before), **(extra_audit or {})},
        after={"status": str(new_status)},
    )
```

- [ ] **Step 4: Extend `src/app/ordering/models.py`** — append Order + OrderItem classes:

```python
# append to src/app/ordering/models.py

from sqlalchemy import Text


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")

    address_id: Mapped[int | None] = mapped_column(ForeignKey("customer_addresses.id"))
    additional_details: Mapped[str | None] = mapped_column(Text)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    delivery_fee_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    distance_km: Mapped[float | None] = mapped_column()

    weather_delay_disclosed: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late: Mapped[bool | None] = mapped_column(Boolean)

    coupon_id: Mapped[int | None] = mapped_column(BigInteger)

    # Resale fields
    resale_of_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    # SHA-256 hex of phone + address used to exclude original customer from resale
    exclusion_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    cancellation_reason: Mapped[str | None] = mapped_column(String(256))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    # Snapshot fields — captured at order time, not FK-joined at read time
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    dish_number: Mapped[int] = mapped_column(Integer)
    dish_name: Mapped[str] = mapped_column(String(256))
    price_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(String(512))  # verbatim special request
```

- [ ] **Step 5: Generate + apply migration**

```bash
.venv/bin/alembic revision --autogenerate -m "orders_order_items"
.venv/bin/alembic upgrade head
```

Add `BEFORE UPDATE` triggers in the migration:

```python
op.execute("""
    CREATE TRIGGER trg_orders_updated_at
    BEFORE UPDATE ON orders FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
op.execute("""
    CREATE TRIGGER trg_order_items_updated_at
    BEFORE UPDATE ON order_items FOR EACH ROW EXECUTE FUNCTION set_updated_at();
""")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ordering/test_fsm.py -v`
Expected: 8 PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/ordering/models.py src/app/ordering/fsm.py \
        alembic/versions/ tests/ordering/test_fsm.py
git commit -m "feat: orders + order_items tables + OrderFSM with explicit transition map and audit helper"
```

---

### Task 3: `pg_trgm` extension + `name_normalized` column + `ordering/matching.py`

**Files:**
- Create: `src/app/ordering/matching.py`
- Create: `tests/ordering/test_matching.py`
- Alembic migration for pg_trgm extension + `name_normalized` column on `dishes`

- [ ] **Step 1: Write the failing tests**

```python
# tests/ordering/test_matching.py
import pytest
from decimal import Decimal
from app.ordering.matching import normalize_name, find_dish_matches, MatchResult


def test_normalize_name_lowercases_and_strips():
    assert normalize_name("  Chicken BIRYANI  ") == "chicken biryani"


def test_normalize_name_removes_punctuation():
    assert normalize_name("Chkn. Biryani!") == "chkn biryani"


async def test_find_dish_matches_single_strong_match(db_session):
    """Single match above 0.6 with gap > 0.15 → MatchResult.DIRECT."""
    from app.ordering.matching import MatchConfidence
    # Seed an active menu with one dish
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=1,
        dish_number=110, name="Chicken Biryani",
        price_aed=Decimal("22.00"), category="Rice", is_available=True,
        name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.commit()

    results = await find_dish_matches(db_session, restaurant_id=1, query="chikn biryani")
    assert results.confidence == MatchConfidence.DIRECT
    assert len(results.candidates) == 1
    assert results.candidates[0].dish_number == 110


async def test_find_dish_matches_by_exact_number(db_session):
    from app.ordering.matching import MatchConfidence
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=1,
        dish_number=201, name="Mutton Karahi",
        price_aed=Decimal("35.00"), category="Curries", is_available=True,
        name_normalized="mutton karahi",
    )
    db_session.add(dish)
    await db_session.commit()

    results = await find_dish_matches(db_session, restaurant_id=1, query="201")
    assert results.confidence == MatchConfidence.DIRECT
    assert results.candidates[0].dish_number == 201


async def test_find_dish_matches_none_returns_no_match(db_session):
    from app.ordering.matching import MatchConfidence
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=1,
        dish_number=301, name="Mango Lassi",
        price_aed=Decimal("10.00"), category="Drinks", is_available=True,
        name_normalized="mango lassi",
    ))
    await db_session.commit()

    results = await find_dish_matches(db_session, restaurant_id=1, query="xyz zyx zzz")
    assert results.confidence == MatchConfidence.NO_MATCH
    assert results.candidates == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ordering/test_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ordering.matching'`

- [ ] **Step 3: Generate + apply `pg_trgm` + `name_normalized` migration**

```bash
.venv/bin/alembic revision -m "pg_trgm_name_normalized"
```

Edit the generated migration:

```python
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.add_column("dishes", sa.Column("name_normalized", sa.String(256), nullable=True))
    op.execute("""
        UPDATE dishes SET name_normalized = lower(regexp_replace(name, '[^a-zA-Z0-9 ]', '', 'g'))
        WHERE name_normalized IS NULL;
    """)
    op.execute("""
        CREATE INDEX ix_dishes_name_normalized_trgm
        ON dishes USING gin (name_normalized gin_trgm_ops);
    """)

def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_dishes_name_normalized_trgm;")
    op.drop_column("dishes", "name_normalized")
```

```bash
.venv/bin/alembic upgrade head
```

- [ ] **Step 4: Add `name_normalized` column to `Dish` model in `src/app/menu/models.py`** — append:

```python
name_normalized: Mapped[str | None] = mapped_column(String(256))
```

- [ ] **Step 5: Write `src/app/ordering/matching.py`**

```python
# src/app/ordering/matching.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import select, text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.models import Dish, Menu

_SINGLE_THRESHOLD = 0.6
_GAP_THRESHOLD = 0.15


def normalize_name(raw: str) -> str:
    """Lowercase, strip, remove non-alphanumeric (except spaces)."""
    cleaned = re.sub(r"[^a-zA-Z0-9 ]", "", raw)
    return cleaned.strip().lower()


class MatchConfidence(StrEnum):
    DIRECT = "direct"        # 1 strong match; gap large enough
    AMBIGUOUS = "ambiguous"  # 2+ candidates within threshold of each other
    NO_MATCH = "no_match"    # nothing above floor


@dataclass
class MatchResult:
    confidence: MatchConfidence
    candidates: list[Dish] = field(default_factory=list)


async def _active_menu_id(session: "AsyncSession", restaurant_id: int) -> int | None:
    row = await session.scalar(
        select(Menu.id).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    return row


async def find_dish_matches(
    session: "AsyncSession",
    restaurant_id: int,
    query: str,
) -> MatchResult:
    """Return a MatchResult for the customer's dish query.

    Flow:
    1. If query is a bare integer → exact dish_number lookup.
    2. Otherwise → pg_trgm similarity on name_normalized, ranked DESC.
    3. Apply DIRECT / AMBIGUOUS / NO_MATCH rules.
    """
    query = query.strip()
    menu_id = await _active_menu_id(session, restaurant_id)
    if menu_id is None:
        return MatchResult(confidence=MatchConfidence.NO_MATCH)

    # --- Number lookup ---
    if re.fullmatch(r"\d+", query):
        dish = await session.scalar(
            select(Dish).where(
                Dish.menu_id == menu_id,
                Dish.dish_number == int(query),
                Dish.is_available == True,  # noqa: E712
            )
        )
        if dish:
            return MatchResult(confidence=MatchConfidence.DIRECT, candidates=[dish])
        return MatchResult(confidence=MatchConfidence.NO_MATCH)

    # --- Trigram similarity ---
    normalized_query = normalize_name(query)
    rows = (
        await session.execute(
            text("""
                SELECT d.id, similarity(d.name_normalized, :q) AS sim
                FROM dishes d
                WHERE d.menu_id = :mid
                  AND d.is_available = true
                  AND d.name_normalized IS NOT NULL
                  AND similarity(d.name_normalized, :q) > 0.3
                ORDER BY sim DESC
                LIMIT 5
            """),
            {"q": normalized_query, "mid": menu_id},
        )
    ).fetchall()

    if not rows:
        return MatchResult(confidence=MatchConfidence.NO_MATCH)

    top_sim: float = rows[0].sim
    if top_sim < _SINGLE_THRESHOLD:
        return MatchResult(confidence=MatchConfidence.NO_MATCH)

    # Load top dish objects
    top_ids = [r.id for r in rows]
    dishes_map: dict[int, Dish] = {}
    for dish in (await session.scalars(select(Dish).where(Dish.id.in_(top_ids)))).all():
        dishes_map[dish.id] = dish

    top_dish = dishes_map[rows[0].id]

    if len(rows) == 1 or (top_sim - rows[1].sim) > _GAP_THRESHOLD:
        return MatchResult(confidence=MatchConfidence.DIRECT, candidates=[top_dish])

    # Multiple close candidates → AMBIGUOUS (return up to 3)
    candidates = [dishes_map[r.id] for r in rows[:3] if r.id in dishes_map]
    return MatchResult(confidence=MatchConfidence.AMBIGUOUS, candidates=candidates)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ordering/test_matching.py -v`
Expected: 4 PASS (normalize tests pass immediately; DB tests pass after migration)

- [ ] **Step 7: Commit**

```bash
git add src/app/ordering/matching.py src/app/menu/models.py \
        alembic/versions/ tests/ordering/test_matching.py
git commit -m "feat: pg_trgm extension + name_normalized backfill + dish matching with DIRECT/AMBIGUOUS/NO_MATCH"
```

---

### Task 4: `geo/haversine.py` + `ordering/fees.py`

**Files:**
- Create: `src/app/geo/__init__.py`, `src/app/geo/haversine.py`
- Create: `src/app/ordering/fees.py`
- Create: `tests/geo/__init__.py`, `tests/geo/test_haversine.py`
- Create: `tests/ordering/test_fees.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/geo/__init__.py  (empty)

# tests/geo/test_haversine.py
from app.geo.haversine import distance_km


def test_same_point_is_zero():
    assert distance_km(25.2048, 55.2708, 25.2048, 55.2708) == 0.0


def test_known_distance_dubai_to_deira():
    # Dubai Mall area (~25.1972, 55.2796) to Deira (~25.2697, 55.3094) ≈ 8.5 km
    d = distance_km(25.1972, 55.2796, 25.2697, 55.3094)
    assert 7.5 < d < 9.5


def test_distance_is_symmetric():
    d1 = distance_km(25.2048, 55.2708, 25.1500, 55.2200)
    d2 = distance_km(25.1500, 55.2200, 25.2048, 55.2708)
    assert abs(d1 - d2) < 0.001


def test_distance_gt_10km():
    # Dubai to Abu Dhabi ≈ 130 km
    d = distance_km(25.2048, 55.2708, 24.4539, 54.3773)
    assert d > 10.0
```

```python
# tests/ordering/test_fees.py
from decimal import Decimal
import pytest
from app.ordering.fees import calculate_fee, UndeliverableError


def test_fee_within_3km_is_free():
    assert calculate_fee(2.5) == Decimal("0.00")


def test_fee_exactly_3km_is_free():
    assert calculate_fee(3.0) == Decimal("0.00")


def test_fee_between_3_and_5km_is_5():
    assert calculate_fee(4.0) == Decimal("5.00")


def test_fee_exactly_5km_is_5():
    assert calculate_fee(5.0) == Decimal("5.00")


def test_fee_above_5km_is_10():
    assert calculate_fee(7.5) == Decimal("10.00")


def test_fee_exactly_10km_is_10():
    assert calculate_fee(10.0) == Decimal("10.00")


def test_beyond_10km_raises_undeliverable():
    with pytest.raises(UndeliverableError):
        calculate_fee(10.1)


def test_custom_tiers_from_settings():
    # Override tiers via settings dict — restaurant can configure different thresholds
    custom = {"tiers": [{"max_km": 5.0, "fee": "0.00"}, {"max_km": 10.0, "fee": "8.00"}]}
    assert calculate_fee(4.0, settings=custom) == Decimal("0.00")
    assert calculate_fee(8.0, settings=custom) == Decimal("8.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/geo/test_haversine.py tests/ordering/test_fees.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/app/geo/haversine.py`**

```python
# src/app/geo/__init__.py
```

```python
# src/app/geo/haversine.py
from math import asin, cos, radians, sin, sqrt

_EARTH_RADIUS_KM = 6371.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in kilometres using the haversine formula."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(a))
```

- [ ] **Step 4: Write `src/app/ordering/fees.py`**

```python
# src/app/ordering/fees.py
from decimal import Decimal

_DEFAULT_TIERS = [
    {"max_km": 3.0, "fee": "0.00"},
    {"max_km": 5.0, "fee": "5.00"},
    {"max_km": 10.0, "fee": "10.00"},
]
_MAX_RADIUS_KM = 10.0


class UndeliverableError(Exception):
    """Raised when distance exceeds the maximum delivery radius."""


def calculate_fee(distance_km: float, settings: dict | None = None) -> Decimal:
    """Return delivery fee in AED for the given distance.

    Args:
        distance_km: haversine distance from restaurant to delivery address.
        settings: optional dict with key ``"tiers"`` (list of {max_km, fee} dicts,
                  sorted ascending by max_km). Defaults to spec §1 tiers.

    Raises:
        UndeliverableError: distance > max tier max_km.
    """
    tiers = (settings or {}).get("tiers", _DEFAULT_TIERS)
    max_radius = max(t["max_km"] for t in tiers)

    if distance_km > max_radius:
        raise UndeliverableError(
            f"Distance {distance_km:.2f} km exceeds maximum delivery radius "
            f"{max_radius:.1f} km."
        )

    for tier in sorted(tiers, key=lambda t: t["max_km"]):
        if distance_km <= tier["max_km"]:
            return Decimal(tier["fee"])

    raise UndeliverableError(f"No fee tier matched for {distance_km:.2f} km.")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/geo/test_haversine.py tests/ordering/test_fees.py -v`
Expected: 8 + 8 = all PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/geo tests/geo \
        src/app/ordering/fees.py tests/ordering/test_fees.py
git commit -m "feat: haversine distance helper + delivery fee calculator with configurable tiers"
```

---

### Task 5: LLM port additions — Describer, IntentClassifier, Arbiter

**Files:**
- Extend: `src/app/llm/port.py` (add 3 new Protocol classes)
- Extend: `src/app/llm/fake.py` (add Fake implementations)
- Extend: `src/app/llm/claude.py` (add Claude implementations)
- Extend: `src/app/llm/factory.py` (add get_describer, get_intent_classifier, get_arbiter)
- Create: `tests/llm/test_llm_ordering_ports.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/llm/test_llm_ordering_ports.py
import pytest
from app.llm.fake import FakeDescriber, FakeIntentClassifier, FakeArbiter
from app.llm.port import DescriberPort, IntentClassifierPort, ArbiterPort


def test_fake_describer_returns_max_3_lines():
    describer = FakeDescriber()
    result = describer.describe("Chicken Biryani", "Fragrant basmati rice cooked with tender chicken.")
    lines = [l for l in result.strip().split("\n") if l.strip()]
    assert 1 <= len(lines) <= 3


def test_fake_describer_never_includes_price():
    describer = FakeDescriber()
    result = describer.describe("Chicken Biryani", "Fragrant basmati rice with chicken.", price_hint="22.00")
    assert "22" not in result
    assert "AED" not in result


def test_fake_intent_classifier_returns_known_intent():
    classifier = FakeIntentClassifier()
    # known intents: "order_item", "dish_question", "cancel", "modify", "status", "other"
    intent = classifier.classify("I want to cancel my order")
    assert intent in {"order_item", "dish_question", "cancel", "modify", "status", "other"}


async def test_fake_arbiter_returns_one_of_candidates():
    arbiter = FakeArbiter()
    from decimal import Decimal
    from app.menu.models import Dish, Menu
    # Create minimal Dish-like objects
    class MockDish:
        dish_number = 110
        name = "Chicken Biryani"
        price_aed = Decimal("22.00")

    candidates = [MockDish()]
    result = await arbiter.arbitrate("chkn biry", candidates)
    assert result is candidates[0]


def test_describer_protocol_satisfied_by_fake():
    """FakeDescriber satisfies DescriberPort Protocol (structural check)."""
    d: DescriberPort = FakeDescriber()
    assert callable(d.describe)


def test_intent_classifier_protocol_satisfied_by_fake():
    c: IntentClassifierPort = FakeIntentClassifier()
    assert callable(c.classify)


def test_arbiter_protocol_satisfied_by_fake():
    a: ArbiterPort = FakeArbiter()
    assert callable(a.arbitrate)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/llm/test_llm_ordering_ports.py -v`
Expected: FAIL — `ImportError: cannot import name 'FakeDescriber'`

- [ ] **Step 3: Extend `src/app/llm/port.py`** — append after existing protocol:

```python
# append to src/app/llm/port.py

class DescriberPort(Protocol):
    def describe(self, name: str, raw_description: str, price_hint: str | None = None) -> str:
        """Return ≤3-line customer-facing description. NEVER include price."""
        ...


class IntentClassifierPort(Protocol):
    def classify(self, text: str) -> str:
        """Return one of: order_item | dish_question | cancel | modify | status | other."""
        ...


class ArbiterPort(Protocol):
    async def arbitrate(self, query: str, candidates: list) -> object | None:
        """Given ambiguous matches, return the single best Dish or None."""
        ...
```

- [ ] **Step 4: Extend `src/app/llm/fake.py`** — append:

```python
# append to src/app/llm/fake.py

class FakeDescriber:
    """Test double: returns a deterministic 1-line description, never includes price."""

    def describe(self, name: str, raw_description: str, price_hint: str | None = None) -> str:
        # Truncate raw description to 80 chars; strip price-like patterns
        import re
        safe = re.sub(r"\b(?:AED|aed|\d+\.\d{2})\b", "", raw_description).strip()
        return f"{name}. {safe[:80]}"


class FakeIntentClassifier:
    """Test double: rule-based classification for known test phrases."""

    _RULES = [
        ({"cancel"}, "cancel"),
        ({"modify", "change"}, "modify"),
        ({"where", "status", "order"}, "status"),
        ({"what is", "describe", "tell me about"}, "dish_question"),
        ({"want", "order", "add", "get"}, "order_item"),
    ]

    def classify(self, text: str) -> str:
        lower = text.lower()
        for keywords, intent in self._RULES:
            if any(k in lower for k in keywords):
                return intent
        return "other"


class FakeArbiter:
    """Test double: always returns the first candidate (deterministic)."""

    async def arbitrate(self, query: str, candidates: list) -> object | None:
        return candidates[0] if candidates else None
```

- [ ] **Step 5: Extend `src/app/llm/claude.py`** — append thin Claude implementations:

```python
# append to src/app/llm/claude.py

import re as _re


class ClaudeDescriber:
    """Production describer via Claude API. Max 3 lines, never includes price."""

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    def describe(self, name: str, raw_description: str, price_hint: str | None = None) -> str:
        prompt = (
            f"Write a customer-facing description for this dish:\n"
            f"Name: {name}\n"
            f"Details: {raw_description}\n\n"
            f"Rules: maximum 3 lines, no price, no currency amounts, "
            f"no 'AED', factual and appetising."
        )
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=128,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        # Safety strip — remove any price-like patterns that slipped through
        safe = _re.sub(r"\b(?:AED|aed|\d+\.\d{2})\b", "", raw).strip()
        return safe


class ClaudeIntentClassifier:
    """Production intent classifier via Claude API."""

    _VALID = frozenset({"order_item", "dish_question", "cancel", "modify", "status", "other"})

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    def classify(self, text: str) -> str:
        prompt = (
            f"Classify this WhatsApp message from a restaurant customer.\n"
            f"Message: {text!r}\n\n"
            f"Reply with exactly one word from: "
            f"order_item, dish_question, cancel, modify, status, other"
        )
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=16,
            messages=[{"role": "user", "content": prompt}],
        )
        result = message.content[0].text.strip().lower()
        return result if result in self._VALID else "other"


class ClaudeArbiter:
    """Production arbiter: given ambiguous dish candidates, returns best match."""

    def __init__(self) -> None:
        from app.llm.factory import _get_anthropic_client
        self._client = _get_anthropic_client()

    async def arbitrate(self, query: str, candidates: list) -> object | None:
        if not candidates:
            return None
        options = "\n".join(
            f"{i + 1}. {c.dish_number}. {c.name}" for i, c in enumerate(candidates)
        )
        prompt = (
            f"A customer typed: {query!r}\n"
            f"These menu items might match:\n{options}\n\n"
            f"Which number (1-{len(candidates)}) is the best match? "
            f"Reply with just the number, or 0 if none match."
        )
        import anthropic
        message = self._client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=8,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except ValueError:
            pass
        return None
```

- [ ] **Step 6: Extend `src/app/llm/factory.py`** — append getter functions:

```python
# append to src/app/llm/factory.py

def get_describer():
    """FastAPI/test dependency — returns FakeDescriber or ClaudeDescriber."""
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeDescriber
        return ClaudeDescriber()
    from app.llm.fake import FakeDescriber
    return FakeDescriber()


def get_intent_classifier():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeIntentClassifier
        return ClaudeIntentClassifier()
    from app.llm.fake import FakeIntentClassifier
    return FakeIntentClassifier()


def get_arbiter():
    settings = get_settings()
    if settings.llm_provider == "claude":
        from app.llm.claude import ClaudeArbiter
        return ClaudeArbiter()
    from app.llm.fake import FakeArbiter
    return FakeArbiter()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/llm/test_llm_ordering_ports.py -v`
Expected: 7 PASS

- [ ] **Step 8: Commit**

```bash
git add src/app/llm/port.py src/app/llm/fake.py src/app/llm/claude.py src/app/llm/factory.py \
        tests/llm/test_llm_ordering_ports.py
git commit -m "feat: LLM ordering ports — DescriberPort, IntentClassifierPort, ArbiterPort with Fake and Claude impls"
```

---

### Task 6: Conversation engine — `collecting_items`, `address_capture`, `receiver_details`, `order_confirmation` states

**Files:**
- Extend: `src/app/conversation/engine.py`
- Extend: `src/app/ordering/service.py` (get_or_create_customer, create_draft_order, add_item, finalize_confirmation)
- Create: `tests/conversation/test_engine_ordering.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/conversation/test_engine_ordering.py
from decimal import Decimal
import pytest
from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.ordering.models import Customer, Order, OrderItem
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str = "wamid.o1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


def _loc_msg(lat: float, lon: float, wa_id: str = "wamid.loc1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.LOCATION,
        payload={"latitude": lat, "longitude": lon},
        restaurant_phone="+97141234567",
        timestamp=1717660801,
    )


def _btn(btn_id: str, wa_id: str = "wamid.btn1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.BUTTON_REPLY,
        payload={"id": btn_id, "title": "Yes"},
        restaurant_phone="+97141234567",
        timestamp=1717660802,
    )


async def _seed_restaurant_and_menu(db_session):
    """Seed restaurant (id=1 assumed from conftest) + an active menu with 2 dishes."""
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=1, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=1, dish_number=201,
        name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


async def test_item_collection_direct_match_asks_confirmation(db_session):
    """After menu_sent state, typing a dish name triggers a direct-match confirmation ask."""
    await _seed_restaurant_and_menu(db_session)

    # Greeting → menu_sent
    await handle_inbound(db_session, _msg("hi", "wamid.greet"), restaurant_id=1)
    await db_session.commit()

    # Send dish name
    await handle_inbound(db_session, _msg("chicken biryani", "wamid.item1"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    # Last outbox message should confirm the dish
    last_body = rows[-1].payload["body"]
    assert "110" in last_body or "Chicken Biryani" in last_body


async def test_item_collection_qty_parsing(db_session):
    """Quantity prefixes 2x, x2, 'two' are all parsed to qty=2."""
    await _seed_restaurant_and_menu(db_session)
    await handle_inbound(db_session, _msg("hi", "wamid.greet2"), restaurant_id=1)
    await db_session.commit()

    # Force state to collecting_items with a draft order
    from app.conversation.models import Conversation
    from sqlalchemy import select as sa_select
    conv = (await db_session.execute(
        sa_select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()
    conv.state = {**conv.state, "dialogue_state": "collecting_items", "draft_order_id": None}
    await db_session.commit()

    await handle_inbound(db_session, _msg("2x chicken biryani", "wamid.qty1"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert rows  # at least a confirmation message sent


async def test_location_pin_within_radius_advances_to_address_text(db_session):
    """A pin within 10 km of restaurant is accepted; bot asks for text address."""
    await _seed_restaurant_and_menu(db_session)

    from app.conversation.models import Conversation
    from sqlalchemy import select as sa_select

    # Seed conversation in address_capture state
    await handle_inbound(db_session, _msg("hi", "wamid.greet3"), restaurant_id=1)
    await db_session.commit()
    conv = (await db_session.execute(
        sa_select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()
    conv.state = {**conv.state, "dialogue_state": "address_capture"}
    await db_session.commit()

    # Send pin near restaurant (restaurant at 25.2048, 55.2708)
    await handle_inbound(db_session, _loc_msg(25.2100, 55.2750, "wamid.pin1"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"].lower()
    assert "room" in last or "apartment" in last or "building" in last


async def test_location_pin_beyond_radius_sends_undeliverable(db_session):
    """A pin > 10 km from restaurant sends 'Sorry not deliverable'."""
    await _seed_restaurant_and_menu(db_session)

    from app.conversation.models import Conversation
    from sqlalchemy import select as sa_select

    await handle_inbound(db_session, _msg("hi", "wamid.greet4"), restaurant_id=1)
    await db_session.commit()
    conv = (await db_session.execute(
        sa_select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()
    conv.state = {**conv.state, "dialogue_state": "address_capture"}
    await db_session.commit()

    # Abu Dhabi pin — far from Dubai
    await handle_inbound(db_session, _loc_msg(24.4539, 54.3773, "wamid.far1"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"].lower()
    assert "deliverable" in last or "sorry" in last


async def test_order_confirmation_message_includes_totals_and_eta(db_session):
    """order_confirmation state sends a message with subtotal, fee, COD, ETA 40 min."""
    await _seed_restaurant_and_menu(db_session)

    from app.conversation.models import Conversation
    from app.ordering.models import Customer, CustomerAddress, Order
    from sqlalchemy import select as sa_select

    # Seed a customer + address + confirmed order
    customer = Customer(
        restaurant_id=1, phone="+971501110001", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="101", building="Tower A",
        receiver_name="Ali", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-0001", status="pending_confirmation",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id, distance_km=1.5,
    )
    db_session.add(order)
    await db_session.flush()
    await db_session.commit()

    # Trigger confirmation state via engine
    await handle_inbound(db_session, _msg("hi", "wamid.greet5"), restaurant_id=1)
    await db_session.commit()
    conv = (await db_session.execute(
        sa_select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()
    conv.state = {
        **conv.state,
        "dialogue_state": "order_confirmation",
        "pending_order_id": order.id,
    }
    await db_session.commit()

    await handle_inbound(db_session, _btn("confirm_order", "wamid.conf1"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"]
    assert "40" in last or "AED" in last or "COD" in last.upper()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py -v`
Expected: FAIL — engine does not yet handle ordering states

- [ ] **Step 3: Write `src/app/ordering/service.py`** (partial — customer + draft order + item helpers)

```python
# src/app/ordering/service.py
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.ordering.fsm import OrderFSM, OrderStatus, transition


async def get_or_create_customer(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
) -> Customer:
    existing = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == phone,
        )
    )
    if existing:
        return existing
    customer = Customer(
        restaurant_id=restaurant_id,
        phone=phone,
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    session.add(customer)
    await session.flush()
    return customer


async def get_last_address(
    session: AsyncSession,
    customer_id: int,
) -> CustomerAddress | None:
    return await session.scalar(
        select(CustomerAddress)
        .where(
            CustomerAddress.customer_id == customer_id,
            CustomerAddress.confirmed == True,  # noqa: E712
        )
        .order_by(CustomerAddress.last_used_at.desc().nullslast())
        .limit(1)
    )


async def upsert_address(
    session: AsyncSession,
    *,
    customer_id: int,
    latitude: float | None,
    longitude: float | None,
    room_apartment: str,
    building: str,
    receiver_name: str | None = None,
    additional_details: str | None = None,
) -> CustomerAddress:
    addr = CustomerAddress(
        customer_id=customer_id,
        latitude=latitude,
        longitude=longitude,
        room_apartment=room_apartment,
        building=building,
        receiver_name=receiver_name,
        additional_details=additional_details,
        confirmed=False,
    )
    session.add(addr)
    await session.flush()
    return addr


async def create_draft_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
) -> Order:
    # Generate per-restaurant order number: count existing + 1
    from sqlalchemy import func
    count = await session.scalar(
        select(func.count()).select_from(Order).where(Order.restaurant_id == restaurant_id)
    ) or 0
    order_number = f"R{restaurant_id}-{count + 1:04d}"
    order = Order(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_number=order_number,
        status=OrderStatus.DRAFT,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("0.00"),
        total=Decimal("0.00"),
    )
    session.add(order)
    await session.flush()
    return order


async def add_item(
    session: AsyncSession,
    *,
    order: Order,
    dish,  # Dish ORM object
    qty: int = 1,
    notes: str | None = None,
) -> OrderItem:
    item = OrderItem(
        order_id=order.id,
        dish_id=dish.id,
        dish_number=dish.dish_number,
        dish_name=dish.name,
        price_aed=dish.price_aed,
        qty=qty,
        notes=notes,
    )
    session.add(item)
    # Recalculate order totals
    existing = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    subtotal = sum(i.price_aed * i.qty for i in existing) + dish.price_aed * qty
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()
    return item


def parse_qty_and_text(text: str) -> tuple[int, str]:
    """Parse quantity prefixes from free text. Returns (qty, remaining_text).

    Handles: "2x chicken", "x2 chicken", "two chicken", "chicken" (qty=1).
    """
    text = text.strip()
    # Numeric prefix: "2x ...", "x2 ..."
    m = re.match(r"^(\d+)\s*[xX]\s*(.+)$", text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    m = re.match(r"^[xX]\s*(\d+)\s+(.+)$", text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    # Word numbers
    word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    lower = text.lower()
    for word, val in word_map.items():
        if lower.startswith(word + " "):
            return val, text[len(word):].strip()
    return 1, text


async def finalize_confirmation(
    session: AsyncSession,
    *,
    order: Order,
    actor: str = "customer",
) -> None:
    """Move order draft → pending_confirmation → confirmed, set SLA clock."""
    from app.ordering.fsm import transition as fsm_transition
    if order.status == OrderStatus.DRAFT:
        await fsm_transition(session, order, OrderStatus.PENDING_CONFIRMATION, actor=actor)
    await fsm_transition(session, order, OrderStatus.CONFIRMED, actor=actor)
    now = datetime.now(timezone.utc)
    order.sla_confirmed_at = now
    order.sla_deadline = now + timedelta(minutes=40)
    order.promised_eta = order.sla_deadline
```

- [ ] **Step 4: Extend `src/app/conversation/engine.py`** — add ordering state handlers

Add the following state functions after the existing `_handle_greeting` function, then update the `handle_inbound` dispatcher:

```python
# Additional imports at top of engine.py:
# from app.ordering.service import (
#     get_or_create_customer, create_draft_order, add_item, finalize_confirmation,
#     parse_qty_and_text, get_last_address, upsert_address,
# )
# from app.ordering.matching import find_dish_matches, MatchConfidence
# from app.ordering.fees import calculate_fee, UndeliverableError
# from app.geo.haversine import distance_km as haversine_distance
# from app.ordering.fsm import OrderStatus
# from app.ordering.models import Order, CustomerAddress


async def _handle_collecting_items(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Parse dish name/number + qty from free text, confirm or disambiguate."""
    from app.menu.models import Dish
    from app.ordering.matching import find_dish_matches, MatchConfidence
    from app.ordering.service import (
        add_item, create_draft_order, get_or_create_customer, parse_qty_and_text,
    )
    from app.ordering.models import Order

    text = inbound.payload.get("text", "")
    qty, dish_query = parse_qty_and_text(text)

    # "What is X?" dish question — hand to describer
    if dish_query.lower().startswith("what is "):
        item_name = dish_query[8:].strip()
        from app.llm.factory import get_describer
        describer = get_describer()
        desc = describer.describe(item_name, "")
        key = f"dish-desc-{conv.id}-{inbound.wa_message_id}"
        await enqueue_message(
            session, restaurant_id=restaurant_id,
            to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
            payload={"body": desc}, idempotency_key=key,
        )
        return

    result = await find_dish_matches(session, restaurant_id=restaurant_id, query=dish_query)

    if result.confidence == MatchConfidence.NO_MATCH:
        # Ask for dish number
        key = f"no-match-{conv.id}-{inbound.wa_message_id}"
        await enqueue_message(
            session, restaurant_id=restaurant_id,
            to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
            payload={"body": "Sorry, I didn't find that dish. Please reply with the dish number from the menu."},
            idempotency_key=key,
        )
        return

    if result.confidence == MatchConfidence.AMBIGUOUS:
        options = " or ".join(
            f"{d.dish_number}. {d.name} — AED {d.price_aed}" for d in result.candidates[:3]
        )
        key = f"ambiguous-{conv.id}-{inbound.wa_message_id}"
        await enqueue_message(
            session, restaurant_id=restaurant_id,
            to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
            payload={"body": f"Do you mean {options}?"},
            idempotency_key=key,
        )
        return

    # DIRECT match
    dish = result.candidates[0]
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=inbound.from_phone,
    )

    draft_order_id = conv.state.get("draft_order_id")
    if draft_order_id:
        order = await session.get(Order, draft_order_id)
    else:
        order = await create_draft_order(
            session, restaurant_id=restaurant_id, customer_id=customer.id,
        )
        conv.state = {**conv.state, "draft_order_id": order.id}

    await add_item(session, order=order, dish=dish, qty=qty)

    confirm_body = (
        f"{qty}x {dish.dish_number}. {dish.name} — AED {dish.price_aed} added.\n"
        f"Reply with more items, or send 'done' to proceed to delivery details."
    )
    key = f"item-added-{conv.id}-{inbound.wa_message_id}"
    await enqueue_message(
        session, restaurant_id=restaurant_id,
        to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
        payload={"body": confirm_body}, idempotency_key=key,
    )
    conv.state = {**conv.state, "dialogue_state": "collecting_items"}


async def _handle_address_capture(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Handle address capture: location pin OR comma-separated text."""
    from app.geo.haversine import distance_km as haversine_distance
    from app.ordering.fees import UndeliverableError, calculate_fee
    from app.ordering.service import get_last_address, get_or_create_customer, upsert_address
    from app.identity.models import Restaurant
    from sqlalchemy import select as sa_select

    restaurant = await session.scalar(
        sa_select(Restaurant).where(Restaurant.id == restaurant_id)
    )
    rest_lat = restaurant.latitude if restaurant else 25.2048
    rest_lon = restaurant.longitude if restaurant else 55.2708

    if inbound.type.value == "location":
        lat = inbound.payload["latitude"]
        lon = inbound.payload["longitude"]
        dist = haversine_distance(rest_lat, rest_lon, lat, lon)
        try:
            fee = calculate_fee(dist)
        except UndeliverableError:
            key = f"undeliverable-{conv.id}-{inbound.wa_message_id}"
            await enqueue_message(
                session, restaurant_id=restaurant_id,
                to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
                payload={"body": "Sorry, your location is outside our delivery area (max 10 km)."},
                idempotency_key=key,
            )
            return

        # Check returning customer for stored address
        customer = await get_or_create_customer(
            session, restaurant_id=restaurant_id, phone=inbound.from_phone,
        )
        last_addr = await get_last_address(session, customer.id)

        conv.state = {
            **conv.state,
            "pin_lat": lat, "pin_lon": lon,
            "distance_km": dist, "delivery_fee": str(fee),
        }

        if last_addr and last_addr.room_apartment and last_addr.building:
            # Offer stored address
            stored_text = f"room/apartment {last_addr.room_apartment} building {last_addr.building}"
            key = f"offer-stored-{conv.id}-{inbound.wa_message_id}"
            await enqueue_message(
                session, restaurant_id=restaurant_id,
                to_phone=inbound.from_phone, msg_type=OutboundMessageType.BUTTONS,
                payload={
                    "body": f"Use your saved address?\n{stored_text}",
                    "buttons": [
                        {"id": f"use_address_{last_addr.id}", "title": "Yes, use this"},
                        {"id": "new_address", "title": "Enter new address"},
                    ],
                },
                idempotency_key=key,
            )
            conv.state = {**conv.state, "offered_address_id": last_addr.id}
        else:
            # Ask for text address
            key = f"ask-text-addr-{conv.id}-{inbound.wa_message_id}"
            await enqueue_message(
                session, restaurant_id=restaurant_id,
                to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
                payload={"body": "Please send your room/apartment and building, separated by a comma.\nExample: 101, Tower A"},
                idempotency_key=key,
            )
            conv.state = {**conv.state, "dialogue_state": "address_text_pending"}
        return

    # Text address: expect "room/apartment, building"
    text = inbound.payload.get("text", "")
    if "," not in text:
        key = f"addr-format-{conv.id}-{inbound.wa_message_id}"
        await enqueue_message(
            session, restaurant_id=restaurant_id,
            to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
            payload={"body": "Please include a comma between room/apartment and building.\nExample: 101, Tower A"},
            idempotency_key=key,
        )
        return

    parts = text.split(",", 1)
    room_apartment = parts[0].strip()
    building = parts[1].strip()
    echo = f"room/apartment number {room_apartment} building {building}"
    conv.state = {
        **conv.state,
        "pending_room": room_apartment,
        "pending_building": building,
        "dialogue_state": "address_confirm_pending",
    }
    key = f"addr-echo-{conv.id}-{inbound.wa_message_id}"
    await enqueue_message(
        session, restaurant_id=restaurant_id,
        to_phone=inbound.from_phone, msg_type=OutboundMessageType.BUTTONS,
        payload={
            "body": f"Confirm address: {echo}",
            "buttons": [
                {"id": "confirm_address", "title": "Confirm"},
                {"id": "change_address", "title": "Change"},
            ],
        },
        idempotency_key=key,
    )


async def _handle_order_confirmation(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Send order summary; on button confirm → set sla_confirmed_at and transition to confirmed."""
    from app.ordering.models import Order, OrderItem
    from app.ordering.service import finalize_confirmation

    order_id = conv.state.get("pending_order_id")
    if not order_id:
        return

    order = await session.get(Order, order_id)
    if not order:
        return

    # Button confirm
    if inbound.type.value == "button_reply":
        btn_id = inbound.payload.get("id", "")
        if btn_id == "confirm_order":
            await finalize_confirmation(session, order=order, actor="customer")
            conv.state = {**conv.state, "dialogue_state": "order_placed"}
            key = f"order-confirmed-{conv.id}-{inbound.wa_message_id}"
            await enqueue_message(
                session, restaurant_id=restaurant_id,
                to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
                payload={"body": (
                    f"Order confirmed! Your ETA is 40 minutes.\n"
                    f"Total: AED {order.total} (COD — cash on delivery).\n"
                    f"Order #{order.order_number}"
                )},
                idempotency_key=key,
            )
            return

    # First visit to confirmation state — render summary
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    item_lines = "\n".join(
        f"  {it.qty}x {it.dish_number}. {it.dish_name} — AED {it.price_aed * it.qty}"
        for it in items
    )

    weather_note = ""
    if order.weather_delay_disclosed:
        weather_note = "\n⚠️ Note: delivery may be delayed due to weather conditions."

    summary = (
        f"Order summary:\n{item_lines}\n\n"
        f"Subtotal: AED {order.subtotal}\n"
        f"Delivery fee: AED {order.delivery_fee_aed}\n"
        f"Total: AED {order.total}\n"
        f"Payment: COD (cash on delivery)\n"
        f"ETA: 40 minutes{weather_note}\n\n"
        f"Confirm your order?"
    )
    key = f"order-summary-{conv.id}-{inbound.wa_message_id}"
    await enqueue_message(
        session, restaurant_id=restaurant_id,
        to_phone=inbound.from_phone, msg_type=OutboundMessageType.BUTTONS,
        payload={
            "body": summary,
            "buttons": [
                {"id": "confirm_order", "title": "Confirm Order"},
                {"id": "cancel_order", "title": "Cancel"},
            ],
        },
        idempotency_key=key,
    )
```

Update `handle_inbound` dispatcher in `engine.py` — add new state branches after `menu_sent`:

```python
    elif state in ("menu_sent", "collecting_items"):
        await _handle_collecting_items(session, conv, inbound, restaurant_id)
    elif state in ("address_capture", "address_text_pending"):
        await _handle_address_capture(session, conv, inbound, restaurant_id)
    elif state in ("order_confirmation", "address_confirm_pending"):
        await _handle_order_confirmation(session, conv, inbound, restaurant_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/conversation/engine.py src/app/ordering/service.py \
        tests/conversation/test_engine_ordering.py
git commit -m "feat: conversation engine ordering states — item collection, address capture, order confirmation"
```

---

### Task 7: Order modification before `ready` + cancellation with resale

**Files:**
- Extend: `src/app/ordering/service.py` (modify_order, cancel_order)
- Extend: `src/app/conversation/engine.py` (modification + cancellation state handlers)
- Create: `tests/ordering/test_modification.py`, `tests/ordering/test_cancellation.py`

- [ ] **Step 1: Write the failing modification tests**

```python
# tests/ordering/test_modification.py
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select

from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.ordering.service import modify_order
from app.ordering.fsm import OrderStatus, IllegalTransitionError
from app.audit.models import AuditLog


async def _seed_confirmed_order(db_session) -> tuple[Order, object]:
    """Seed a confirmed order with one item. Returns (order, dish)."""
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=1,
        dish_number=110, name="Chicken Biryani",
        price_aed=Decimal("22.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.flush()

    customer = Customer(
        restaurant_id=1, phone="+971501230099", name="Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-MOD1", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        sla_confirmed_at=now, sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id, dish_id=dish.id,
        dish_number=110, dish_name="Chicken Biryani",
        price_aed=Decimal("22.00"), qty=1,
    )
    db_session.add(item)
    await db_session.commit()
    return order, dish


async def test_modify_order_recalculates_total(db_session):
    """Adding an item via modify_order recalculates subtotal + total."""
    order, dish = await _seed_confirmed_order(db_session)
    original_deadline = order.sla_deadline

    # Add another item
    await modify_order(
        db_session, order=order,
        new_items=[{"dish": dish, "qty": 2, "notes": None}],
        actor="customer",
    )
    await db_session.commit()
    await db_session.refresh(order)

    assert order.subtotal == Decimal("44.00")
    assert order.total == Decimal("44.00")


async def test_modify_order_restarts_sla_clock(db_session):
    """SLA deadline is reset to now+40 min after modification."""
    order, dish = await _seed_confirmed_order(db_session)
    original_deadline = order.sla_deadline

    await modify_order(
        db_session, order=order,
        new_items=[{"dish": dish, "qty": 1, "notes": None}],
        actor="customer",
    )
    await db_session.commit()
    await db_session.refresh(order)

    assert order.sla_deadline > original_deadline


async def test_modify_order_blocked_at_ready(db_session):
    """Modification at or after ready raises ValueError."""
    order, dish = await _seed_confirmed_order(db_session)
    order.status = OrderStatus.READY
    await db_session.commit()

    with pytest.raises(ValueError, match="modification.*not allowed"):
        await modify_order(
            db_session, order=order,
            new_items=[{"dish": dish, "qty": 1, "notes": None}],
            actor="customer",
        )


async def test_modify_order_produces_audit_log(db_session):
    """Each modification is recorded in audit_log."""
    order, dish = await _seed_confirmed_order(db_session)

    await modify_order(
        db_session, order=order,
        new_items=[{"dish": dish, "qty": 1, "notes": "extra spicy"}],
        actor="customer",
    )
    await db_session.commit()

    logs = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(r.action == "order_modified" for r in logs)
```

- [ ] **Step 2: Write the failing cancellation tests**

```python
# tests/ordering/test_cancellation.py
import hashlib
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select

from app.ordering.models import Customer, Order
from app.ordering.service import cancel_order
from app.ordering.fsm import OrderStatus


async def _seed_order(db_session, status: str) -> Order:
    customer = Customer(
        restaurant_id=1, phone="+971501230098", name="Cancel Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-CAN1", status=status,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def test_cancel_before_preparing_transitions_to_cancelled(db_session):
    order = await _seed_order(db_session, OrderStatus.CONFIRMED)
    await cancel_order(db_session, order=order, actor="customer", reason="Changed mind")
    await db_session.commit()
    await db_session.refresh(order)
    assert order.status == OrderStatus.CANCELLED
    assert order.cancellation_reason == "Changed mind"


async def test_cancel_during_preparing_creates_resale_copy(db_session):
    """Cancellation after cooking started creates an on_resale copy with exclusion hash."""
    order = await _seed_order(db_session, OrderStatus.PREPARING)
    original_id = order.id

    await cancel_order(db_session, order=order, actor="customer", reason="Duplicate order")
    await db_session.commit()

    orders = (await db_session.execute(select(Order))).scalars().all()
    resale_order = next((o for o in orders if o.resale_of_order_id == original_id), None)

    assert resale_order is not None
    assert resale_order.status == OrderStatus.ON_RESALE
    assert resale_order.exclusion_hash is not None
    # Original order transitioned to on_resale via FSM
    await db_session.refresh(order)
    assert order.status == OrderStatus.ON_RESALE


async def test_exclusion_hash_encodes_phone_and_address(db_session):
    """Exclusion hash is SHA-256 of phone + address_id so same customer is blocked from resale."""
    customer = Customer(
        restaurant_id=1, phone="+971501230097", name="Hash Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    from app.ordering.models import CustomerAddress
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="10", building="A", confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-HASH1", status=OrderStatus.PREPARING,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        address_id=addr.id,
    )
    db_session.add(order)
    await db_session.commit()

    await cancel_order(db_session, order=order, actor="customer", reason="Test")
    await db_session.commit()

    resale = (await db_session.execute(
        select(Order).where(Order.resale_of_order_id == order.id)
    )).scalar_one()

    expected_hash = hashlib.sha256(
        f"+971501230097:{addr.id}".encode()
    ).hexdigest()
    assert resale.exclusion_hash == expected_hash
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/ordering/test_modification.py tests/ordering/test_cancellation.py -v`
Expected: FAIL — `ImportError: cannot import name 'modify_order'`

- [ ] **Step 4: Extend `src/app/ordering/service.py`** — append `modify_order` and `cancel_order`:

```python
# append to src/app/ordering/service.py

import hashlib
from copy import deepcopy


_MODIFIABLE_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.PENDING_CONFIRMATION,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
}
# Only before ready
_MODIFIABLE_BEFORE_READY = {OrderStatus.DRAFT, OrderStatus.PENDING_CONFIRMATION, OrderStatus.CONFIRMED}


async def modify_order(
    session: AsyncSession,
    *,
    order: Order,
    new_items: list[dict],  # [{"dish": Dish, "qty": int, "notes": str|None}]
    actor: str,
) -> None:
    """Replace all items on an order, recalculate totals, restart SLA clock.

    Allowed only before status reaches 'ready'. Raises ValueError otherwise.
    Caller must commit.
    """
    from app.ordering.fsm import OrderStatus as _OS
    non_modifiable = {_OS.READY, _OS.ASSIGNED, _OS.PICKED_UP, _OS.ARRIVING,
                      _OS.DELIVERED, _OS.CANCELLED, _OS.UNDELIVERABLE,
                      _OS.ON_RESALE, _OS.RESOLD, _OS.WRITTEN_OFF}
    if order.status in non_modifiable:
        raise ValueError(
            f"Order modification not allowed at status '{order.status}'. "
            f"Modifications are blocked once an order reaches 'ready'."
        )

    before_snapshot = {
        "status": str(order.status),
        "subtotal": str(order.subtotal),
        "total": str(order.total),
        "sla_deadline": order.sla_deadline.isoformat() if order.sla_deadline else None,
    }

    # Delete existing items
    existing_items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    for item in existing_items:
        await session.delete(item)
    await session.flush()

    # Add new items
    subtotal = Decimal("0.00")
    for entry in new_items:
        dish = entry["dish"]
        qty = entry.get("qty", 1)
        notes = entry.get("notes")
        item = OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=dish.dish_number,
            dish_name=dish.name,
            price_aed=dish.price_aed,
            qty=qty,
            notes=notes,
        )
        session.add(item)
        subtotal += dish.price_aed * qty

    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed

    # Restart SLA clock
    now = datetime.now(timezone.utc)
    order.sla_confirmed_at = now
    order.sla_deadline = now + timedelta(minutes=40)
    order.promised_eta = order.sla_deadline

    await session.flush()

    await record_audit(
        session,
        actor=actor,
        restaurant_id=order.restaurant_id,
        entity="order",
        entity_id=str(order.id),
        action="order_modified",
        before=before_snapshot,
        after={
            "subtotal": str(order.subtotal),
            "total": str(order.total),
            "sla_deadline": order.sla_deadline.isoformat(),
        },
    )


async def cancel_order(
    session: AsyncSession,
    *,
    order: Order,
    actor: str,
    reason: str | None = None,
) -> Order | None:
    """Cancel an order. If cooking has started (status=preparing) → create resale copy.

    Returns the resale Order if created, else None.
    Caller must commit.
    """
    from app.ordering.fsm import transition as fsm_transition, OrderStatus as _OS

    order.cancellation_reason = reason
    order.cancelled_at = datetime.now(timezone.utc)

    if order.status == _OS.PREPARING:
        # Post-cooking: transition original to on_resale, create resale copy
        await fsm_transition(session, order, _OS.ON_RESALE, actor=actor,
                             extra_audit={"reason": reason or ""})

        # Build exclusion hash from customer phone + address_id
        customer = await session.get(Customer, order.customer_id)
        phone = customer.phone if customer else ""
        addr_id = str(order.address_id or "")
        exclusion_hash = hashlib.sha256(f"{phone}:{addr_id}".encode()).hexdigest()

        resale = Order(
            restaurant_id=order.restaurant_id,
            customer_id=order.customer_id,
            order_number=f"{order.order_number}-RS",
            status=_OS.ON_RESALE,
            priority=order.priority,
            weather_delay_disclosed=order.weather_delay_disclosed,
            delivery_fee_aed=order.delivery_fee_aed,
            subtotal=order.subtotal,
            total=order.total,
            address_id=order.address_id,
            distance_km=order.distance_km,
            additional_details=order.additional_details,
            resale_of_order_id=order.id,
            exclusion_hash=exclusion_hash,
        )
        session.add(resale)
        await session.flush()
        return resale

    # Pre-cooking: plain cancel
    await fsm_transition(session, order, _OS.CANCELLED, actor=actor,
                         extra_audit={"reason": reason or ""})
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ordering/test_modification.py tests/ordering/test_cancellation.py -v`
Expected: 7 PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/ordering/service.py \
        tests/ordering/test_modification.py tests/ordering/test_cancellation.py
git commit -m "feat: order modification (SLA clock restart, blocked at ready) + cancellation with post-cooking resale"
```

---

### Task 8: "Where is my order?" status reply handler

**Files:**
- Extend: `src/app/conversation/engine.py` (status reply state + trigger from any state)
- Create: `tests/ordering/test_status_reply.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/ordering/test_status_reply.py
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.ordering.models import Customer, Order
from app.ordering.fsm import OrderStatus
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _status_msg(wa_id: str = "wamid.status1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110099",
        type=MessageType.TEXT,
        payload={"text": "where is my order"},
        restaurant_phone="+97141234567",
        timestamp=1717660900,
    )


async def _seed_active_order(db_session, status: str) -> Order:
    customer = Customer(
        restaurant_id=1, phone="+971501110099", name="StatusTest",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-STA1", status=status,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        sla_confirmed_at=now,
        sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def test_status_query_confirmed_order_returns_status_message(db_session):
    """'Where is my order' when order is confirmed returns a status string."""
    await _seed_active_order(db_session, OrderStatus.CONFIRMED)

    from app.menu.models import Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()

    await handle_inbound(db_session, _status_msg(), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert rows
    last = rows[-1].payload["body"].lower()
    assert any(word in last for word in ("confirmed", "preparing", "kitchen", "order", "eta"))


async def test_status_query_preparing_mentions_kitchen(db_session):
    await _seed_active_order(db_session, OrderStatus.PREPARING)

    from app.menu.models import Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()

    await handle_inbound(db_session, _status_msg(wa_id="wamid.status2"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"].lower()
    assert "kitchen" in last or "preparing" in last


async def test_status_query_no_active_order_returns_polite_reply(db_session):
    """No active order → polite 'no recent order' message."""
    from app.menu.models import Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()

    await handle_inbound(db_session, _status_msg(wa_id="wamid.status3"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert rows
    last = rows[-1].payload["body"].lower()
    assert "order" in last
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/ordering/test_status_reply.py -v`
Expected: FAIL — status intent not handled

- [ ] **Step 3: Extend `src/app/conversation/engine.py`** — add status reply function and intent interception

Add after existing state handlers:

```python
async def _handle_status_query(
    session: AsyncSession,
    conv: Conversation,
    inbound: InboundMessage,
    restaurant_id: int,
) -> None:
    """Reply to 'where is my order' with current order status."""
    from app.ordering.models import Customer, Order
    from app.ordering.fsm import OrderStatus

    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == inbound.from_phone,
        )
    )
    if not customer:
        body = "I don't see any recent orders for this number. Send 'hi' to start a new order."
        key = f"status-no-customer-{conv.id}-{inbound.wa_message_id}"
        await enqueue_message(
            session, restaurant_id=restaurant_id,
            to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
            payload={"body": body}, idempotency_key=key,
        )
        return

    # Find the most recent active (non-terminal) order
    terminal = {
        str(OrderStatus.DELIVERED), str(OrderStatus.CANCELLED),
        str(OrderStatus.UNDELIVERABLE), str(OrderStatus.RESOLD),
        str(OrderStatus.WRITTEN_OFF),
    }
    order = await session.scalar(
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.customer_id == customer.id,
            Order.status.notin_(terminal),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )

    if not order:
        body = "You don't have any active orders right now. Send 'hi' to place a new order."
        key = f"status-no-order-{conv.id}-{inbound.wa_message_id}"
        await enqueue_message(
            session, restaurant_id=restaurant_id,
            to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
            payload={"body": body}, idempotency_key=key,
        )
        return

    status_messages = {
        str(OrderStatus.DRAFT): "Your order is being assembled.",
        str(OrderStatus.PENDING_CONFIRMATION): "Your order is waiting for your confirmation.",
        str(OrderStatus.CONFIRMED): f"Your order #{order.order_number} is confirmed and will be ready in about 40 minutes.",
        str(OrderStatus.PREPARING): f"Your order #{order.order_number} is being prepared in the kitchen.",
        str(OrderStatus.READY): f"Your order #{order.order_number} is ready and waiting for the rider.",
        str(OrderStatus.ASSIGNED): f"Your order #{order.order_number} has been assigned to a rider.",
        str(OrderStatus.PICKED_UP): f"Your order #{order.order_number} is on its way!",
        str(OrderStatus.ARRIVING): f"Your order #{order.order_number} is arriving shortly!",
        str(OrderStatus.ON_RESALE): "Your order was cancelled. Please contact the restaurant for more information.",
    }
    body = status_messages.get(str(order.status), f"Order status: {order.status}.")

    if order.sla_deadline:
        from datetime import datetime, timezone
        remaining = int((order.sla_deadline - datetime.now(timezone.utc)).total_seconds() / 60)
        if 0 < remaining <= 40 and order.status in (
            str(OrderStatus.CONFIRMED), str(OrderStatus.PREPARING), str(OrderStatus.READY)
        ):
            body += f" Estimated time remaining: ~{remaining} minutes."

    key = f"status-reply-{conv.id}-{inbound.wa_message_id}"
    await enqueue_message(
        session, restaurant_id=restaurant_id,
        to_phone=inbound.from_phone, msg_type=OutboundMessageType.TEXT,
        payload={"body": body}, idempotency_key=key,
    )
```

In `handle_inbound`, add intent interception at the top of the state dispatch (after manual_takeover check, before state routing) — check for status intent keywords:

```python
    # Intent intercept: status query recognized at any state
    if inbound.type.value == "text":
        from app.llm.factory import get_intent_classifier
        classifier = get_intent_classifier()
        intent = classifier.classify(inbound.payload.get("text", ""))
        if intent == "status":
            await _handle_status_query(session, conv, inbound, restaurant_id)
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ordering/test_status_reply.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/conversation/engine.py tests/ordering/test_status_reply.py
git commit -m "feat: 'where is my order' status reply with ETA countdown from SLA clock"
```

---

### Task 9: `ordering/router.py` + `ordering/schemas.py`

**Files:**
- Create: `src/app/ordering/schemas.py`, `src/app/ordering/router.py`
- Modify: `src/app/main.py` (mount ordering router)

- [ ] **Step 1: Write the failing test** (append to `tests/ordering/test_service.py`)

```python
# append to tests/ordering/test_service.py
async def test_get_order_api_returns_order(client, db_session):
    """GET /api/v1/orders/{id} returns order JSON for the authenticated restaurant."""
    from decimal import Decimal
    from app.ordering.models import Customer, Order
    from app.ordering.fsm import OrderStatus

    customer = Customer(
        restaurant_id=1, phone="+971501220001", name="API Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-API1", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/orders/{order.id}",
        headers={"Authorization": f"Bearer {_get_test_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_number"] == "R1-API1"
    assert data["status"] == "confirmed"
```

Note: `_get_test_token()` should be the same helper used in Phase 0+1 identity tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ordering/test_service.py::test_get_order_api_returns_order -v`
Expected: FAIL — 404 (route not mounted)

- [ ] **Step 3: Write `src/app/ordering/schemas.py`**

```python
# src/app/ordering/schemas.py
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dish_number: int
    dish_name: str
    price_aed: Decimal
    qty: int
    notes: Optional[str]


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    customer_id: int
    order_number: str
    status: str
    priority: str
    subtotal: Decimal
    delivery_fee_aed: Decimal
    total: Decimal
    distance_km: Optional[float]
    weather_delay_disclosed: bool
    sla_confirmed_at: Optional[datetime]
    sla_deadline: Optional[datetime]
    promised_eta: Optional[datetime]
    delivered_at: Optional[datetime]
    late: Optional[bool]
    additional_details: Optional[str]
    address_id: Optional[int]
    cancellation_reason: Optional[str]
    cancelled_at: Optional[datetime]
    resale_of_order_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    phone: str
    name: Optional[str]
    total_orders: int
    total_spend: Decimal
    first_order_at: Optional[datetime]
    last_order_at: Optional[datetime]
```

- [ ] **Step 4: Write `src/app/ordering/router.py`**

```python
# src/app/ordering/router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.ordering.models import Order, OrderItem
from app.ordering.schemas import OrderItemOut, OrderOut

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> Order:
    order = await session.scalar(
        select(Order).where(
            Order.id == order_id,
            Order.restaurant_id == restaurant.id,
        )
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: str | None = None,
    limit: int = 50,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[Order]:
    q = select(Order).where(Order.restaurant_id == restaurant.id)
    if status:
        q = q.where(Order.status == status)
    q = q.order_by(Order.created_at.desc()).limit(limit)
    return list((await session.scalars(q)).all())
```

- [ ] **Step 5: Mount router in `src/app/main.py`** — add:

```python
from app.ordering.router import router as ordering_router
# ...
app.include_router(ordering_router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest tests/ordering/test_service.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/ordering/schemas.py src/app/ordering/router.py src/app/main.py \
        tests/ordering/test_service.py
git commit -m "feat: ordering API router — GET /api/v1/orders/{id} and list with status filter"
```

---

### Task 10: Weather stub port + integration into order confirmation

**Files:**
- Create: `src/app/weather/__init__.py`, `src/app/weather/port.py`, `src/app/weather/fake.py`
- Extend: `src/app/conversation/engine.py` (call weather port in order_confirmation state)
- Create: `tests/ordering/test_weather_stub.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/ordering/test_weather_stub.py
from app.weather.fake import FakeWeatherPort
from app.weather.port import WeatherPort


def test_fake_weather_port_default_no_delay():
    port = FakeWeatherPort(delay_active=False)
    assert port.is_delay_active() is False


def test_fake_weather_port_delay_active():
    port = FakeWeatherPort(delay_active=True)
    assert port.is_delay_active() is True


def test_fake_weather_port_satisfies_protocol():
    port: WeatherPort = FakeWeatherPort()
    assert callable(port.is_delay_active)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/ordering/test_weather_stub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.weather'`

- [ ] **Step 3: Write implementation**

```python
# src/app/weather/__init__.py
```

```python
# src/app/weather/port.py
from typing import Protocol


class WeatherPort(Protocol):
    def is_delay_active(self) -> bool:
        """Return True if current weather conditions may delay delivery."""
        ...
```

```python
# src/app/weather/fake.py
from app.weather.port import WeatherPort


class FakeWeatherPort:
    """Test/dev stub — configurable delay flag."""

    def __init__(self, delay_active: bool = False) -> None:
        self._delay_active = delay_active

    def is_delay_active(self) -> bool:
        return self._delay_active
```

- [ ] **Step 4: Add `get_weather_port()` to `src/app/llm/factory.py`** (or create `src/app/weather/factory.py`):

```python
# src/app/weather/factory.py
from app.weather.fake import FakeWeatherPort


def get_weather_port():
    """FastAPI dependency. Returns FakeWeatherPort for now; real implementation in Phase 4."""
    return FakeWeatherPort(delay_active=False)
```

- [ ] **Step 5: In `_handle_order_confirmation` in `engine.py`**, check weather port before generating summary:

```python
    # Before building summary:
    from app.weather.factory import get_weather_port
    weather = get_weather_port()
    if weather.is_delay_active():
        order.weather_delay_disclosed = True
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ordering/test_weather_stub.py -v`
Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/weather tests/ordering/test_weather_stub.py \
        src/app/conversation/engine.py
git commit -m "feat: weather delay port stub — integrated into order confirmation disclosure"
```

---

### Task 11: Full ordering service tests (create + items + finalize round-trip)

**Files:**
- Extend: `tests/ordering/test_service.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/ordering/test_service.py`)

```python
# append to tests/ordering/test_service.py
async def test_create_draft_order_increments_number(db_session):
    from app.ordering.service import create_draft_order, get_or_create_customer
    customer = await get_or_create_customer(
        db_session, restaurant_id=1, phone="+971500000001",
    )
    await db_session.commit()
    order1 = await create_draft_order(db_session, restaurant_id=1, customer_id=customer.id)
    await db_session.commit()
    order2 = await create_draft_order(db_session, restaurant_id=1, customer_id=customer.id)
    await db_session.commit()
    assert order1.order_number != order2.order_number


async def test_add_item_recalculates_total(db_session):
    from app.menu.models import Dish, Menu
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer

    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=1, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.flush()

    customer = await get_or_create_customer(
        db_session, restaurant_id=1, phone="+971500000002",
    )
    await db_session.flush()
    order = await create_draft_order(db_session, restaurant_id=1, customer_id=customer.id)
    await db_session.flush()

    await add_item(db_session, order=order, dish=dish, qty=2)
    await db_session.commit()

    assert order.subtotal == Decimal("44.00")
    assert order.total == Decimal("44.00")


async def test_finalize_confirmation_sets_sla_fields(db_session):
    from datetime import datetime, timezone
    from app.ordering.service import (
        create_draft_order, finalize_confirmation, get_or_create_customer,
    )
    from app.ordering.fsm import OrderStatus

    customer = await get_or_create_customer(
        db_session, restaurant_id=1, phone="+971500000003",
    )
    await db_session.flush()
    order = await create_draft_order(db_session, restaurant_id=1, customer_id=customer.id)
    await db_session.flush()

    await finalize_confirmation(db_session, order=order, actor="customer")
    await db_session.commit()

    assert order.status == OrderStatus.CONFIRMED
    assert order.sla_confirmed_at is not None
    assert order.sla_deadline is not None
    diff_minutes = (order.sla_deadline - order.sla_confirmed_at).total_seconds() / 60
    assert abs(diff_minutes - 40) < 1  # within 1 min tolerance


async def test_get_or_create_customer_idempotent(db_session):
    from app.ordering.service import get_or_create_customer
    c1 = await get_or_create_customer(
        db_session, restaurant_id=1, phone="+971500000004",
    )
    await db_session.commit()
    c2 = await get_or_create_customer(
        db_session, restaurant_id=1, phone="+971500000004",
    )
    assert c1.id == c2.id
```

- [ ] **Step 2: Run test to verify all pass**

Run: `.venv/bin/pytest tests/ordering/test_service.py -v`
Expected: all PASS (including earlier ones + new 4)

- [ ] **Step 3: Commit**

```bash
git add tests/ordering/test_service.py
git commit -m "test: ordering service round-trip tests — draft, items, finalize, SLA fields"
```

---

### Task 12: MockProvider pipeline integration test (handle_inbound end-to-end)

**Files:**
- Create: `tests/conversation/test_engine_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/conversation/test_engine_pipeline.py
"""
Integration test: inbound text → handle_inbound → outbox enqueued → MockProvider send.
Mirrors the pipeline test pattern from Phase 2.
"""
from decimal import Decimal
from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.outbox.models import OutboxMessage
from app.outbox.service import enqueue_message
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.port import InboundMessage, MessageType, OutboundMessage, OutboundMessageType


async def _seed_menu(db_session):
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=1, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()


async def test_full_greeting_pipeline_via_mock_provider(db_session):
    """Greeting → handle_inbound → outbox row → MockProvider.send delivers it."""
    await _seed_menu(db_session)

    inbound = InboundMessage(
        wa_message_id="wamid.pipeline-1",
        from_phone="+971509000001",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone="+97141234567",
        timestamp=1717660900,
    )

    await handle_inbound(db_session, inbound, restaurant_id=1)
    await db_session.commit()

    # Simulate outbox worker: send all pending rows via MockProvider
    provider = MockProvider()
    rows = (await db_session.execute(
        select(OutboxMessage).where(OutboxMessage.status == "pending")
    )).scalars().all()
    for row in rows:
        payload = dict(row.payload)
        msg_type = OutboundMessageType(payload.pop("type"))
        msg = OutboundMessage(
            to_phone=row.to_phone,
            type=msg_type,
            payload=payload,
            idempotency_key=row.idempotency_key,
        )
        wa_id = await provider.send(msg)
        row.status = "sent"
        row.wa_message_id = wa_id
    await db_session.commit()

    sends = provider.drain_sends()
    assert len(sends) == 1
    assert "110" in sends[0].payload.get("body", "") or "Chicken Biryani" in sends[0].payload.get("body", "")


async def test_item_collection_pipeline_direct_match(db_session):
    """After menu_sent, sending a dish name enqueues a confirmation message."""
    await _seed_menu(db_session)

    # Step 1: greeting
    greet = InboundMessage(
        wa_message_id="wamid.pipe-greet",
        from_phone="+971509000002",
        type=MessageType.TEXT,
        payload={"text": "hello"},
        restaurant_phone="+97141234567",
        timestamp=1717660901,
    )
    await handle_inbound(db_session, greet, restaurant_id=1)
    await db_session.commit()

    # Step 2: order a dish
    order_msg = InboundMessage(
        wa_message_id="wamid.pipe-item1",
        from_phone="+971509000002",
        type=MessageType.TEXT,
        payload={"text": "chicken biryani"},
        restaurant_phone="+97141234567",
        timestamp=1717660902,
    )
    await handle_inbound(db_session, order_msg, restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    # Should have greeting + item confirmation
    assert len(rows) >= 2
    bodies = [r.payload.get("body", "") for r in rows]
    assert any("Chicken Biryani" in b or "110" in b for b in bodies)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_engine_pipeline.py -v`
Expected: FAIL — pipeline not wired yet or test catches a state mismatch

- [ ] **Step 3: Fix any wiring issues** (no new production code expected — tests drive discovery of import/init issues)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/conversation/test_engine_pipeline.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conversation/test_engine_pipeline.py
git commit -m "test: MockProvider pipeline integration tests for greeting and item collection flows"
```

---

### Task 13: Returning customer — stored address offer in address_capture

**Files:**
- Extend: `src/app/conversation/engine.py` (`_handle_address_capture` — button reply for stored address)
- Extend: `tests/conversation/test_engine_ordering.py`

- [ ] **Step 1: Write the failing test** (append to `tests/conversation/test_engine_ordering.py`)

```python
# append to tests/conversation/test_engine_ordering.py
async def test_returning_customer_offered_stored_address(db_session):
    """A customer with a confirmed address is offered it rather than asked for text."""
    await _seed_restaurant_and_menu(db_session)

    from app.ordering.models import Customer, CustomerAddress
    from app.conversation.models import Conversation
    from sqlalchemy import select as sa_select

    # Seed customer with a confirmed address
    customer = Customer(
        restaurant_id=1, phone="+971501110002", name="Returning",
        usual_order_times={}, tags={}, total_orders=1, total_spend=Decimal("22.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    addr = CustomerAddress(
        customer_id=customer.id, latitude=25.21, longitude=55.27,
        room_apartment="5B", building="Marina Tower",
        receiver_name="Returning", confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()

    # Trigger greeting
    greet = InboundMessage(
        wa_message_id="wamid.ret1",
        from_phone="+971501110002",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone="+97141234567",
        timestamp=1717661000,
    )
    await handle_inbound(db_session, greet, restaurant_id=1)
    await db_session.commit()

    # Move to address_capture state
    conv = (await db_session.execute(
        sa_select(Conversation).where(Conversation.phone == "+971501110002")
    )).scalar_one()
    conv.state = {**conv.state, "dialogue_state": "address_capture"}
    await db_session.commit()

    # Send location pin near restaurant
    loc = InboundMessage(
        wa_message_id="wamid.ret2",
        from_phone="+971501110002",
        type=MessageType.LOCATION,
        payload={"latitude": 25.21, "longitude": 55.27},
        restaurant_phone="+97141234567",
        timestamp=1717661001,
    )
    await handle_inbound(db_session, loc, restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload
    # Should offer stored address as a button message
    assert last.get("type") == "buttons" or "5B" in last.get("body", "") or "Marina" in last.get("body", "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_returning_customer_offered_stored_address -v`
Expected: FAIL

- [ ] **Step 3: Verify `_handle_address_capture` in engine.py already handles this path** (from Task 6's code — `get_last_address` branch). If the test still fails, check that `get_last_address` is being called and the button payload type is set correctly.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/conversation/engine.py tests/conversation/test_engine_ordering.py
git commit -m "test: returning customer stored address offer in address_capture state"
```

---

### Task 14: Simulator end-to-end smoke test (order flow via `/simulator/send`)

**Files:**
- Create: `tests/test_simulator_ordering.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulator_ordering.py
"""
End-to-end smoke test: drive a full order conversation via POST /simulator/send
and GET /simulator/messages (Phase 2 simulator endpoints).
"""
from decimal import Decimal
import pytest


async def _seed_full_menu(db_session):
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=1, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=1, dish_number=201,
        name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    await db_session.commit()


async def test_simulator_greeting_returns_menu(client, db_session):
    """POST /simulator/send with 'hi' → bot replies with menu."""
    await _seed_full_menu(db_session)

    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509111001",
            "restaurant_phone": "+97141234567",
            "text": "hi",
        },
    )
    assert resp.status_code == 200

    # Poll messages sent to this phone
    msgs_resp = await client.get(
        "/simulator/messages",
        params={"to_phone": "+971509111001"},
    )
    assert msgs_resp.status_code == 200
    messages = msgs_resp.json()
    bodies = [m.get("payload", {}).get("body", "") for m in messages]
    assert any("Chicken Biryani" in b for b in bodies)


async def test_simulator_order_dish_gets_confirmation(client, db_session):
    """Greeting then dish name → confirmation message contains dish name."""
    await _seed_full_menu(db_session)

    await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509111002",
            "restaurant_phone": "+97141234567",
            "text": "hi",
        },
    )

    resp = await client.post(
        "/simulator/send",
        json={
            "from_phone": "+971509111002",
            "restaurant_phone": "+97141234567",
            "text": "chicken biryani",
        },
    )
    assert resp.status_code == 200

    msgs_resp = await client.get(
        "/simulator/messages",
        params={"to_phone": "+971509111002"},
    )
    messages = msgs_resp.json()
    bodies = [m.get("payload", {}).get("body", "") for m in messages]
    assert any("Chicken Biryani" in b or "110" in b for b in bodies)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_simulator_ordering.py -v`
Expected: FAIL (simulator not wired to new ordering engine states, or restaurant_id resolution not yet stubbed)

- [ ] **Step 3: Fix any wiring issues** — ensure the simulator router resolves `restaurant_id` from `restaurant_phone` by looking up the `restaurants` table (or a default for dev). The simulator was built in Phase 2; this task just drives it further.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_simulator_ordering.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_simulator_ordering.py
git commit -m "test: end-to-end simulator smoke test for ordering flow"
```

---

### Task 15: Full Phase 3 suite run + ruff lint

- [ ] **Step 1: Run the full ordering test suite**

```bash
.venv/bin/pytest tests/ordering/ tests/conversation/ tests/geo/ tests/llm/ \
                 tests/test_simulator_ordering.py -v --tb=short
```

Expected: all PASS. Triage any failures before proceeding.

- [ ] **Step 2: Run ruff lint**

```bash
.venv/bin/ruff check src/app/ordering src/app/geo src/app/weather \
                     src/app/conversation/engine.py src/app/llm/
```

Expected: no errors. Fix any reported issues.

- [ ] **Step 3: Run full suite to confirm no regressions**

```bash
.venv/bin/pytest --tb=short -q
```

Expected: all PASS (no regressions from Phase 0-2 tests).

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -u
git commit -m "chore: ruff lint fixes for Phase 3 ordering module"
```

---

### Task 16: Dish description (via `what is X`) + ambiguous match disambiguation reply

**Files:**
- Extend: `tests/conversation/test_engine_ordering.py`

- [ ] **Step 1: Write the failing tests** (append)

```python
# append to tests/conversation/test_engine_ordering.py
async def test_what_is_query_returns_description_without_price(db_session):
    """'What is chicken biryani' → FakeDescriber reply, no price."""
    await _seed_restaurant_and_menu(db_session)

    from app.conversation.models import Conversation
    from sqlalchemy import select as sa_select

    await handle_inbound(db_session, _msg("hi", "wamid.desc1"), restaurant_id=1)
    await db_session.commit()
    conv = (await db_session.execute(
        sa_select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()
    conv.state = {**conv.state, "dialogue_state": "collecting_items"}
    await db_session.commit()

    await handle_inbound(
        db_session, _msg("what is chicken biryani", "wamid.desc2"), restaurant_id=1
    )
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"]
    assert "22" not in last  # no price
    assert "AED" not in last


async def test_ambiguous_match_sends_disambiguation_question(db_session):
    """Two similar dishes → disambiguation message with both options."""
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=1, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=1, dish_number=111,
        name="Special Chicken Biryani", price_aed=Decimal("28.00"),
        category="Rice", is_available=True, name_normalized="special chicken biryani",
    ))
    await db_session.commit()

    from app.conversation.models import Conversation
    from sqlalchemy import select as sa_select
    from app.ordering.matching import MatchResult, MatchConfidence
    import unittest.mock as mock

    await handle_inbound(db_session, _msg("hi", "wamid.ambig1"), restaurant_id=1)
    await db_session.commit()
    conv = (await db_session.execute(
        sa_select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()
    conv.state = {**conv.state, "dialogue_state": "collecting_items"}
    await db_session.commit()

    # Mock find_dish_matches to return AMBIGUOUS
    ambig_dish_1 = await db_session.scalar(
        sa_select(Dish).where(Dish.dish_number == 110)
    )
    ambig_dish_2 = await db_session.scalar(
        sa_select(Dish).where(Dish.dish_number == 111)
    )
    with mock.patch(
        "app.conversation.engine.find_dish_matches",
        return_value=MatchResult(
            confidence=MatchConfidence.AMBIGUOUS,
            candidates=[ambig_dish_1, ambig_dish_2],
        ),
    ):
        await handle_inbound(
            db_session, _msg("biryani", "wamid.ambig2"), restaurant_id=1
        )
        await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"]
    assert "110" in last or "111" in last  # disambiguation question lists dish numbers
    assert "Do you mean" in last or "mean" in last.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/conversation/test_engine_ordering.py::test_what_is_query_returns_description_without_price tests/conversation/test_engine_ordering.py::test_ambiguous_match_sends_disambiguation_question -v`
Expected: FAIL

- [ ] **Step 3: Fix if needed** — the `_handle_collecting_items` code from Task 6 should already handle both paths. Run to confirm.

- [ ] **Step 4: Run all ordering + conversation tests**

```bash
.venv/bin/pytest tests/ordering/ tests/conversation/ -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conversation/test_engine_ordering.py
git commit -m "test: dish description (no price) + ambiguous match disambiguation question coverage"
```

---

## Phase 3 completion checklist

- [ ] All 16 tasks committed
- [ ] `.venv/bin/pytest --tb=short -q` — full suite green, no regressions
- [ ] `.venv/bin/ruff check src apps tests` — zero errors
- [ ] `docker compose exec db psql -U app -d restaurant -c "\dt"` — confirms `customers`, `customer_addresses`, `orders`, `order_items` tables present
- [ ] Simulator smoke test passes end-to-end (`tests/test_simulator_ordering.py`)
- [ ] `ordering/fsm.py` — every `OrderStatus` value is a key in `TRANSITIONS`
- [ ] No price values in `FakeDescriber` or `ClaudeDescriber` output (safety strip in place)
- [ ] SLA clock restart on modification confirmed by test
- [ ] Resale exclusion hash confirmed by test
- [ ] Weather delay disclosure confirmed by test

---

## Open architecture notes for Phase 4 (Logistics)

- `CustomerAddress.latitude/longitude` are plain floats here; Phase 4 will add a PostGIS `geography(Point)` column for spatial queries (rider proximity, geofence checks).
- `WeatherPort.is_delay_active()` returns a stub `False`; Phase 4 wires the real weather API.
- `Order.distance_km` is populated from `haversine_distance(restaurant, pin)` in the address_capture handler; Phase 4 upgrades to Google Maps Routes API with traffic when available, falling back to haversine.
- The dispatch engine (Phase 4) will call `transition(order, ASSIGNED, actor="dispatch")` — all FSM paths to `ASSIGNED` are already wired.
- `rider_id` field on orders is intentionally absent from Phase 3 models — added by the dispatch/batch migration in Phase 4.
- SLA monitor (Phase 4) reads `Order.sla_deadline` and `weather_delay_disclosed` to decide coupon issuance — both fields are set correctly here.

