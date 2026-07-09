# Wave 4: Menu Control + CRM Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the real remaining gaps in `WS-MENU` (menu control) and `WS-CRM` (customer/CRM/loyalty), per `docs/superpowers/plans/2026-07-08-pos-100pct-roadmap.md`. This plan supersedes the stale verdicts in `docs/POS_100_FEATURE_AUDIT_2026-07-08.md` for Category 3 and Category 6 — every task below was scoped against a fresh read of current code on 2026-07-09 (see "Already-done — skipped" section for what turned out fixed by prior waves).

**Architecture:** Two independent tracks, run by 2 parallel agents.
- **Track A (WS-MENU)** touches `src/app/menu/*`, new `alembic/versions/` migrations, `tests/menu/*`, `frontend/src/screens/MenuManagerScreen*`, `frontend/src/lib/menuApi.ts`, and the **Dish/Menu/Category section only** of `frontend/src/lib/types.ts`.
- **Track B (WS-CRM)** touches `src/app/ordering/models.py` (Customer), `src/app/ordering/detail_schemas.py`, `src/app/ordering/customer_router.py`, `src/app/ordering/service.py` (`patch_customer` only), `src/app/loyalty/*`, `src/app/marketing/automations.py`, `src/app/reports/analytics.py` + `src/app/reports/router.py`, new `alembic/versions/` migrations, `tests/ordering/*`, `tests/loyalty/*`, `tests/marketing/*`, `tests/reports/*`, `frontend/src/screens/CustomerProfileScreen*`, `frontend/src/screens/MarketingScreen*`, `frontend/src/lib/customerApi.ts`, `frontend/src/lib/marketingApi.ts`, and the **Customer/Loyalty/Ticket section only** of `frontend/src/lib/types.ts`.

**⚠️ Coordination points (read before starting either track):**

1. **`frontend/src/lib/types.ts` is touched by both tracks**, in disjoint line ranges (Track A edits the `DishOut`/`DishIn`/`MenuOut` block ~lines 49-90 and appends a new `CategoryOut` block; Track B edits `CustomerDetailOut`/`CustomerProfileOut`/`CustomerPatchIn` ~lines 186-376 and appends a new `StampCard`/`NpsResponse` block). Per the pattern established in prior waves (Wave 1/3 needed a worktree when two tracks touched shared files), **run each track in its own git worktree** (`superpowers:using-git-worktrees`) and merge sequentially — do not let both agents edit `types.ts` on the same branch concurrently. The edits are non-overlapping hunks so the merge itself should be conflict-free once done as two sequential merges.
2. **`frontend/src/App.tsx` and `frontend/src/components/NavSidebar.tsx` are NOT touched by either track this wave** — `/menu` and `/customers` routes already exist from prior waves, and no new top-level screens are added. This is a deliberate scope choice (see item list below); no route/nav conflict this time.
3. **Alembic migration head collision.** Current single head is `z7a8b9c0d1e2` (`stock_adjustment_requests`, Wave 3). Both tracks add migrations chained off this same head, which will produce two divergent heads if both land independently. **Whichever track's PR/branch is merged SECOND must, before running `alembic upgrade head`, edit its first new migration's `down_revision` to point at the OTHER track's last migration revision id** (turning two branches into one linear chain — do not use `alembic merge heads`, this repo's convention is a single linear history per `alembic/versions/` naming, confirmed by reading Wave 3's task 2). Track landing order is not fixed by this plan; the controller decides at integration time. Fixed revision ids to use are given in each task below so this rewrite is a one-line edit.
4. Both tracks may run fully in parallel for all **backend** work and their own **frontend** files; only the final `types.ts` merge and the migration `down_revision` rewrite are serialization points.

**Tech Stack:** FastAPI, async SQLAlchemy 2, Alembic, pytest/anyio, React/Vite/TypeScript, Vitest/Testing Library.

## Global Constraints

- Money: `Decimal`/`Numeric(8,2)` (or the column's existing precision), AED. Times: UTC naive in DB (`TimestampMixin`), Asia/Dubai only in Celery-facing code.
- Routers never touch other modules' models — call services.
- Every mutating backend action that changes state must call `app.audit.service.record_audit` in the same transaction (`record_audit` never commits — caller commits). This is a hard project convention confirmed in every module read for this plan (`menu/service.py`, `loyalty/referrals.py`, `tickets/service.py`).
- New tables using `TimestampMixin` need a `trg_<table>_updated_at` BEFORE UPDATE trigger in their migration (see any prior migration, e.g. `z7a8b9c0d1e2_stock_adjustment_requests.py`, for the exact trigger DDL to copy).
- New model modules/new model classes in existing modules must be importable from **both** `alembic/env.py` and `tests/conftest.py` (sentinel imports) if they are genuinely new modules; if they're new classes added to an existing already-imported module (e.g. adding fields to `Customer` in `ordering/models.py`, or a new class in `menu/models.py`), no new import is needed — only genuinely new files need registering (`src/app/loyalty/models.py` is already imported per `understanding.txt` history, so a new class added there, or a new `src/app/loyalty/stamp_cards.py` file, needs checking against the existing import line, not a wholesale new registration).
- Frontend: reuse `apiClient`/fetch helpers already used by `menuApi.ts`/`customerApi.ts`, `PageHeader`, `Button`, `Spinner`, `Toaster`/`toast()`. Match `CustomerProfileScreen.tsx`/`MenuManagerScreen.tsx` structure (load state, error state, save state).
- Commit per task, conventional-commit style (`feat:`, `chore:`).
- Backend test command: `.venv/bin/pytest tests/<dir> -v` (requires docker db up: `docker compose up -d`). Frontend: `cd frontend && npm test -- <ScreenName or api file>`.
- `restaurant` pytest fixture pattern (already present in `tests/conftest.py` and every module's local `conftest.py`): construct `Restaurant(name=..., phone=..., password_hash="x", lat=25.2048, lng=55.2708)`, `db_session.add`, `flush`, use `.id` — never hardcode a PK.

---

## Already-done — skipped (do NOT re-implement these; verified against current code 2026-07-09)

**WS-MENU:**
- **Time/channel/branch dynamic pricing** — `src/app/menu/pricing.py` (`DishPriceRule`, `create_price_rule`, `resolve_dish_price`) is fully implemented, tested (`tests/menu/test_pricing.py`, 8 passing tests), and migrated (`v3w4x5y6z7a8_dish_price_rules.py`). Happy-hour is expressible today as a `"time"` rule with a `start_time`/`end_time` window — no separate "happy_hour" rule type is needed; Task A2 below only adds the missing list/update/delete endpoints and a minimal UI, it does NOT rebuild the pricing engine.
- **Allergen storage** — `Dish.allergens` (JSONB list) already exists on the model (migration `d62b4e084827_kds_allergens_and_item_checklist.py`), already flows into KDS tickets and `OrderItem.allergens_snapshot`. Task A4 below only adds the missing **manager-facing exposure** (schema + API + UI) — it does NOT add a new column.
- **Menu approval state machine** — `Menu.status` already supports `pending_approval`, and `submit_menu_for_approval()`/`approve_menu()` already exist in `src/app/menu/service.py` with correct transitions, audit calls, and incompleteness rollback. Task A3 below only adds the missing **router endpoints + frontend UI** — it does NOT touch the state machine logic itself.
- Modifiers/combos/upsell (`menu/modifiers.py`, `menu/combos.py`, `menu/upsell.py`) — confirmed fully built (model+service+router+tests), out of scope, no task needed.

**WS-CRM:**
- **Loyalty tier system** (bronze/silver/gold RFM+recency, manager lock/override) — fully built, `src/app/loyalty/service.py` + `POST /api/v1/ordering/customers/{id}/loyalty-tier` + `CustomerProfileScreen.tsx` tier selector. No task needed.
- **Cashback earn/reversal** — fully built and wallet-backed with idempotent reversal (`loyalty/service.py:earn`/`reverse_earn`). No task needed.
- **Referral program backend** — fully built (`loyalty/referrals.py`, `referral_router.py`), tested. Its *frontend* is missing but is **not** one of the 7 roadmap "done" items for this wave — explicitly out of scope, not added as a task (flagged here so the controller doesn't assume it's covered).
- **NPS response capture + summary** (minus the detractor-escalation link, which IS in scope — see Task B7) — `loyalty/nps.py` fully built and tested. Task B7 only adds the missing escalation call.
- **Gift cards** — confirmed minimal-but-complete (wallet-backed purchase + balance lookup), matches product intent, no task needed.
- **Customer segmentation DSL** (`marketing/segments.py`) — fully built for its current allowlisted fields; Task B6 extends the allowlist with `birthday` once the column exists (part of Task B1), it does NOT rebuild the DSL compiler.

---

# Track A — WS-MENU

## Task A1: `Category` model + migration + CRUD service/router (replaces free-text `Dish.category`)

**Files:**
- Modify: `src/app/menu/models.py`
- Create: `src/app/menu/categories.py` (service functions)
- Create: `src/app/menu/category_router.py`
- Modify: `src/app/main.py` (register `category_router`)
- Create: `alembic/versions/a1b2c3d4e5f6_menu_categories.py`
- Test: `tests/menu/test_categories.py`

**Interfaces:**
- Produces: `Category` model (`src/app/menu/models.py`): `id, restaurant_id, name (String(128)), sort_order (Integer, default=0)`, unique `(restaurant_id, name)`.
- Produces: `Dish.category_id: Mapped[int | None]` FK to `categories.id`, nullable (additive — the existing free-text `Dish.category` column is KEPT, not dropped, and is auto-synced to `Category.name` on write so every other reader of `Dish.category`, e.g. `MenuManagerScreen.tsx`'s client-side grouping and `menu/service.py`'s LLM-import path, keeps working unchanged).
- Produces (`src/app/menu/categories.py`): `async def create_category(session, *, restaurant_id, name, sort_order=0) -> Category`, `async def list_categories(session, *, restaurant_id) -> list[Category]`, `async def rename_category(session, *, restaurant_id, category_id, name) -> Category`, `async def delete_category(session, *, restaurant_id, category_id) -> None` (raises `ValueError` if any dish still references it), `async def assign_dish_category(session, *, restaurant_id, dish_id, category_id) -> Dish` (sets `dish.category_id` AND denormalizes `dish.category = category.name`).
- Consumes: `app.audit.service.record_audit`, `app.menu.models.Dish`.

- [ ] **Step 1: Write failing backend tests**

Create `tests/menu/test_categories.py`:

```python
import pytest
from sqlalchemy import select

from app.menu.categories import (
    assign_dish_category,
    create_category,
    delete_category,
    list_categories,
    rename_category,
)
from app.menu.models import Category, Dish


@pytest.mark.anyio
async def test_create_and_list_categories(db_session, restaurant):
    await create_category(db_session, restaurant_id=restaurant.id, name="Starters", sort_order=1)
    await create_category(db_session, restaurant_id=restaurant.id, name="Mains", sort_order=2)
    await db_session.commit()

    rows = await list_categories(db_session, restaurant_id=restaurant.id)
    assert [r.name for r in rows] == ["Starters", "Mains"]


@pytest.mark.anyio
async def test_duplicate_category_name_rejected(db_session, restaurant):
    await create_category(db_session, restaurant_id=restaurant.id, name="Starters")
    await db_session.commit()
    with pytest.raises(ValueError):
        await create_category(db_session, restaurant_id=restaurant.id, name="Starters")


@pytest.mark.anyio
async def test_assign_dish_category_denormalizes_name(db_session, restaurant, active_menu_with_dish):
    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id)
    )).one()
    cat = await create_category(db_session, restaurant_id=restaurant.id, name="Beverages")
    await db_session.commit()

    updated = await assign_dish_category(
        db_session, restaurant_id=restaurant.id, dish_id=dish.id, category_id=cat.id,
    )
    await db_session.commit()
    assert updated.category_id == cat.id
    assert updated.category == "Beverages"


@pytest.mark.anyio
async def test_rename_category_does_not_retroactively_rename_dish_text(db_session, restaurant, active_menu_with_dish):
    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id)
    )).one()
    cat = await create_category(db_session, restaurant_id=restaurant.id, name="Beverages")
    await db_session.commit()
    await assign_dish_category(db_session, restaurant_id=restaurant.id, dish_id=dish.id, category_id=cat.id)
    await db_session.commit()

    renamed = await rename_category(db_session, restaurant_id=restaurant.id, category_id=cat.id, name="Drinks")
    await db_session.commit()
    assert renamed.name == "Drinks"


@pytest.mark.anyio
async def test_delete_category_blocked_while_dishes_reference_it(db_session, restaurant, active_menu_with_dish):
    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id)
    )).one()
    cat = await create_category(db_session, restaurant_id=restaurant.id, name="Beverages")
    await db_session.commit()
    await assign_dish_category(db_session, restaurant_id=restaurant.id, dish_id=dish.id, category_id=cat.id)
    await db_session.commit()

    with pytest.raises(ValueError):
        await delete_category(db_session, restaurant_id=restaurant.id, category_id=cat.id)


@pytest.mark.anyio
async def test_delete_unused_category_succeeds(db_session, restaurant):
    cat = await create_category(db_session, restaurant_id=restaurant.id, name="Unused")
    await db_session.commit()
    await delete_category(db_session, restaurant_id=restaurant.id, category_id=cat.id)
    await db_session.commit()
    rows = (await db_session.scalars(select(Category).where(Category.id == cat.id))).all()
    assert rows == []
```

- [ ] **Step 2: Run tests to verify RED**

Run: `.venv/bin/pytest tests/menu/test_categories.py -v`
Expected: `ImportError: cannot import name 'create_category'` (module `app.menu.categories` doesn't exist yet) and `ImportError: cannot import name 'Category'` from `app.menu.models`.

- [ ] **Step 3: Add the `Category` model + `Dish.category_id` field**

In `src/app/menu/models.py`, add near the top of the file (after imports, before `class Menu`):

```python
class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "name", name="uq_categories_restaurant_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
```

Confirm `BigInteger`, `ForeignKey`, `String`, `Integer`, `UniqueConstraint`, `Mapped`, `mapped_column` are already imported at the top of `models.py` (they are — same imports used by `Dish`); add any missing ones to the existing `sqlalchemy`/`sqlalchemy.orm` import lines.

On the `Dish` class, add directly below the existing `category: Mapped[str | None] = mapped_column(String(128))` line (models.py:52):

```python
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), index=True)
```

- [ ] **Step 4: Implement `src/app/menu/categories.py`**

```python
"""Dedicated Category entity — replaces free-text Dish.category as the source of
truth for category management, while keeping Dish.category (denormalized name)
in sync so every existing reader (LLM menu import, KDS station routing via
CategoryStationDefault, frontend client-side grouping) keeps working unchanged.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.menu.models import Category, Dish


async def create_category(
    session: AsyncSession, *, restaurant_id: int, name: str, sort_order: int = 0
) -> Category:
    name = name.strip()
    existing = await session.scalar(
        select(Category).where(Category.restaurant_id == restaurant_id, Category.name == name)
    )
    if existing is not None:
        raise ValueError(f"category '{name}' already exists")
    row = Category(restaurant_id=restaurant_id, name=name, sort_order=sort_order)
    session.add(row)
    await session.flush()
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="category",
        entity_id=str(row.id), action="created", before=None, after={"name": name},
    )
    return row


async def list_categories(session: AsyncSession, *, restaurant_id: int) -> list[Category]:
    return list((await session.scalars(
        select(Category).where(Category.restaurant_id == restaurant_id).order_by(Category.sort_order, Category.id)
    )).all())


async def rename_category(
    session: AsyncSession, *, restaurant_id: int, category_id: int, name: str
) -> Category:
    cat = await session.get(Category, category_id)
    if cat is None or cat.restaurant_id != restaurant_id:
        raise ValueError("category not found")
    before = cat.name
    cat.name = name.strip()
    # Denormalized name lives on every dish currently assigned to this category.
    dishes = (await session.scalars(
        select(Dish).where(Dish.category_id == category_id, Dish.restaurant_id == restaurant_id)
    )).all()
    for d in dishes:
        d.category = cat.name
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="category",
        entity_id=str(cat.id), action="renamed", before={"name": before}, after={"name": cat.name},
    )
    await session.flush()
    return cat


async def delete_category(session: AsyncSession, *, restaurant_id: int, category_id: int) -> None:
    cat = await session.get(Category, category_id)
    if cat is None or cat.restaurant_id != restaurant_id:
        raise ValueError("category not found")
    in_use = await session.scalar(
        select(Dish.id).where(Dish.category_id == category_id, Dish.restaurant_id == restaurant_id).limit(1)
    )
    if in_use is not None:
        raise ValueError("cannot delete a category that dishes still reference")
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="category",
        entity_id=str(cat.id), action="deleted", before={"name": cat.name}, after=None,
    )
    await session.delete(cat)
    await session.flush()


async def assign_dish_category(
    session: AsyncSession, *, restaurant_id: int, dish_id: int, category_id: int
) -> Dish:
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.restaurant_id != restaurant_id:
        raise ValueError("dish not found")
    cat = await session.get(Category, category_id)
    if cat is None or cat.restaurant_id != restaurant_id:
        raise ValueError("category not found")
    before = dish.category
    dish.category_id = cat.id
    dish.category = cat.name
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="dish",
        entity_id=str(dish.id), action="category_assigned",
        before={"category": before}, after={"category": cat.name},
    )
    await session.flush()
    return dish
```

- [ ] **Step 5: Run tests to verify GREEN**

Run: `.venv/bin/pytest tests/menu/test_categories.py -v`
Expected: all 6 tests pass.

- [ ] **Step 6: Write failing router tests**

Append to `tests/menu/test_categories.py`:

```python
@pytest.mark.anyio
async def test_category_router_crud(client, auth_headers):
    created = await client.post(
        "/api/v1/categories", json={"name": "Starters", "sort_order": 1}, headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    cat_id = created.json()["id"]

    listed = await client.get("/api/v1/categories", headers=auth_headers)
    assert listed.status_code == 200
    assert any(c["id"] == cat_id for c in listed.json())

    renamed = await client.patch(
        f"/api/v1/categories/{cat_id}", json={"name": "Appetizers"}, headers=auth_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Appetizers"

    deleted = await client.delete(f"/api/v1/categories/{cat_id}", headers=auth_headers)
    assert deleted.status_code == 204
```

- [ ] **Step 7: Run to verify RED**

Run: `.venv/bin/pytest tests/menu/test_categories.py::test_category_router_crud -v`
Expected: 404 (no `/api/v1/categories` route registered).

- [ ] **Step 8: Implement `src/app/menu/category_router.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.menu.categories import create_category, delete_category, list_categories, rename_category

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


class CategoryIn(BaseModel):
    name: str
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: str


class CategoryOut(BaseModel):
    id: int
    name: str
    sort_order: int

    model_config = {"from_attributes": True}


@router.post("", response_model=CategoryOut, status_code=201)
async def create_category_endpoint(
    body: CategoryIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        cat = await create_category(
            session, restaurant_id=restaurant.id, name=body.name, sort_order=body.sort_order
        )
        await session.commit()
        return cat
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("", response_model=list[CategoryOut])
async def list_categories_endpoint(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_categories(session, restaurant_id=restaurant.id)


@router.patch("/{category_id}", response_model=CategoryOut)
async def rename_category_endpoint(
    category_id: int,
    body: CategoryPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        cat = await rename_category(
            session, restaurant_id=restaurant.id, category_id=category_id, name=body.name
        )
        await session.commit()
        return cat
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{category_id}", status_code=204)
async def delete_category_endpoint(
    category_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        await delete_category(session, restaurant_id=restaurant.id, category_id=category_id)
        await session.commit()
        return Response(status_code=204)
    except ValueError as exc:
        code = status.HTTP_409_CONFLICT if "reference" in str(exc) else status.HTTP_404_NOT_FOUND
        raise HTTPException(code, str(exc)) from exc
```

In `src/app/main.py`, find the block of `app.include_router(...)` calls for the menu module (near `from app.menu.router import router as menu_router`) and add:

```python
from app.menu.category_router import router as category_router
```

and, alongside `app.include_router(menu_router)`:

```python
app.include_router(category_router)
```

- [ ] **Step 9: Create the migration**

Create `alembic/versions/a1b2c3d4e5f6_menu_categories.py`:

```python
"""menu categories

Revision ID: a1b2c3d4e5f6
Revises: z7a8b9c0d1e2
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_categories_restaurant_name"),
    )
    op.create_index("ix_categories_restaurant_id", "categories", ["restaurant_id"])
    op.execute(
        """
        CREATE TRIGGER trg_categories_updated_at
        BEFORE UPDATE ON categories
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )
    op.add_column("dishes", sa.Column("category_id", sa.BigInteger(), sa.ForeignKey("categories.id"), nullable=True))
    op.create_index("ix_dishes_category_id", "dishes", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_dishes_category_id", table_name="dishes")
    op.drop_column("dishes", "category_id")
    op.execute("DROP TRIGGER IF EXISTS trg_categories_updated_at ON categories;")
    op.drop_index("ix_categories_restaurant_id", table_name="categories")
    op.drop_table("categories")
```

Before writing this, run `grep -n "set_updated_at\|CREATE OR REPLACE FUNCTION" alembic/versions/*.py | head -3` to confirm the exact trigger function name already defined by the `updated_at_triggers` migration referenced in `CLAUDE.md` — use that exact name (do not invent a new function).

- [ ] **Step 10: Run full suite to verify GREEN**

Run: `.venv/bin/pytest tests/menu/test_categories.py -v && PYTHONPATH=src .venv/bin/alembic upgrade head`
Expected: all tests pass, migration applies cleanly.

- [ ] **Step 11: Commit**

`git add` the files above and commit: `feat: add dedicated Category model with CRUD replacing free-text Dish.category`

---

## Task A2: Price-rule list/update/delete endpoints + pricing UI

**Files:**
- Modify: `src/app/menu/pricing.py`
- Modify: `src/app/menu/pricing_router.py`
- Modify: `frontend/src/lib/menuApi.ts`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/screens/MenuManagerScreen.tsx`
- Modify: `frontend/src/screens/MenuManagerScreen.module.css`
- Test: `tests/menu/test_pricing.py`
- Test: `frontend/src/screens/MenuManagerScreen.pricing.test.tsx`

**Interfaces:**
- Produces (`pricing.py`): `async def list_price_rules(session, *, restaurant_id, dish_id) -> list[DishPriceRule]`, `async def delete_price_rule(session, *, restaurant_id, dish_id, rule_id) -> None`.
- Produces (`pricing_router.py`): `GET /api/v1/dishes/{dish_id}/price-rules`, `DELETE /api/v1/dishes/{dish_id}/price-rules/{rule_id}`.
- Consumes: existing `DishPriceRule` model, `create_price_rule`, `resolve_dish_price` (unchanged).

- [ ] **Step 1: Write failing backend tests**

Append to `tests/menu/test_pricing.py`:

```python
@pytest.mark.anyio
async def test_list_and_delete_price_rules_via_router(client, db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.identity.auth import create_access_token
    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()
    auth_headers = {"Authorization": f"Bearer {create_access_token(restaurant_id=restaurant.id)}"}

    create_resp = await client.post(
        f"/api/v1/dishes/{dish.id}/price-rules",
        json={"rule_type": "channel", "price_aed": "25.00", "channel": "aggregator"},
        headers=auth_headers,
    )
    rule_id = create_resp.json()["id"]

    list_resp = await client.get(f"/api/v1/dishes/{dish.id}/price-rules", headers=auth_headers)
    assert list_resp.status_code == 200
    assert [r["id"] for r in list_resp.json()] == [rule_id]

    delete_resp = await client.delete(
        f"/api/v1/dishes/{dish.id}/price-rules/{rule_id}", headers=auth_headers
    )
    assert delete_resp.status_code == 204

    list_after = await client.get(f"/api/v1/dishes/{dish.id}/price-rules", headers=auth_headers)
    assert list_after.json() == []
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/menu/test_pricing.py::test_list_and_delete_price_rules_via_router -v`
Expected: 404 for `GET .../price-rules`.

- [ ] **Step 3: Implement service + router**

In `src/app/menu/pricing.py`, add after `resolve_dish_price`:

```python
async def list_price_rules(
    session: AsyncSession, *, restaurant_id: int, dish_id: int
) -> list[DishPriceRule]:
    return list((await session.scalars(
        select(DishPriceRule)
        .where(DishPriceRule.restaurant_id == restaurant_id, DishPriceRule.dish_id == dish_id)
        .order_by(DishPriceRule.id)
    )).all())


async def delete_price_rule(
    session: AsyncSession, *, restaurant_id: int, dish_id: int, rule_id: int
) -> None:
    rule = await session.get(DishPriceRule, rule_id)
    if rule is None or rule.restaurant_id != restaurant_id or rule.dish_id != dish_id:
        raise ValueError("price rule not found")
    await session.delete(rule)
    await session.flush()
```

In `src/app/menu/pricing_router.py`, add (matching the existing `create_price_rule`/`resolve_dish_price` endpoint style — read that file's imports/`_load_dish`-style helper first and reuse it):

```python
@router.get("/dishes/{dish_id}/price-rules", response_model=list[PriceRuleOut])
async def list_price_rules_endpoint(
    dish_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    dish = await _load_dish(dish_id, restaurant, session)
    return await list_price_rules(session, restaurant_id=restaurant.id, dish_id=dish.id)


@router.delete("/dishes/{dish_id}/price-rules/{rule_id}", status_code=204)
async def delete_price_rule_endpoint(
    dish_id: int,
    rule_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _load_dish(dish_id, restaurant, session)
    try:
        await delete_price_rule(session, restaurant_id=restaurant.id, dish_id=dish_id, rule_id=rule_id)
        await session.commit()
        return Response(status_code=204)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
```

Read `src/app/menu/pricing_router.py` in full before editing — confirm the exact name of the existing dish-loading helper (it may be inlined rather than a `_load_dish` function; if inlined, extract it into a small `_load_dish(dish_id, restaurant, session)` helper reused by both the existing `create_price_rule`/`effective-price` endpoints and these two new ones, or just inline the same `session.get(Dish, dish_id)` + `restaurant_id` check pattern directly in each new endpoint if extracting is riskier than duplicating three lines). Add `Response`, `status`, `HTTPException` to imports if not already present. Add a `PriceRuleOut` Pydantic schema (id, dish_id, rule_type, price_aed, start_time, end_time, days_of_week, channel) either in `pricing_router.py` itself or a new `pricing_schemas.py` — check whether `pricing.py`/`pricing_router.py` already has a schemas file convention before choosing.

- [ ] **Step 4: Run to verify GREEN**

Run: `.venv/bin/pytest tests/menu/test_pricing.py -v`
Expected: all tests pass (original 8 + new one).

- [ ] **Step 5: Write failing frontend test**

Create `frontend/src/screens/MenuManagerScreen.pricing.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MenuManagerScreen } from "./MenuManagerScreen";
import * as menuApi from "../lib/menuApi";

vi.mock("../lib/menuApi");

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MenuManagerScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MenuManagerScreen price rules", () => {
  beforeEach(() => {
    vi.mocked(menuApi.fetchActiveMenu).mockResolvedValue({
      id: 1, version: 1, status: "active",
      dishes: [{ id: 10, dish_number: 1, name: "Chai", price_aed: "3.00", category: "Drinks", description: null, is_available: true, whatsapp_enabled: true, variants: [], updated_at: "2026-07-09T00:00:00Z" }],
    });
    vi.mocked(menuApi.listPriceRules).mockResolvedValue([
      { id: 5, dish_id: 10, rule_type: "channel", price_aed: "5.00", channel: "aggregator", start_time: null, end_time: null, days_of_week: null },
    ]);
  });

  it("shows existing price rules for a dish and allows deleting one", async () => {
    renderScreen();
    fireEvent.click(await screen.findByText("Chai"));
    fireEvent.click(await screen.findByRole("button", { name: /price rules/i }));
    expect(await screen.findByText(/aggregator/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /delete rule/i }));
    await waitFor(() => expect(menuApi.deletePriceRule).toHaveBeenCalledWith(10, 5));
  });
});
```

- [ ] **Step 6: Run to verify RED**

Run: `cd frontend && npm test -- MenuManagerScreen.pricing`
Expected: fails — `listPriceRules`/`deletePriceRule` not exported, no "price rules" button in the component.

- [ ] **Step 7: Implement frontend client + UI**

In `frontend/src/lib/types.ts`, add after the `MenuOut` interface (~line 84):

```ts
export interface PriceRuleOut {
  id: number;
  dish_id: number;
  rule_type: "time" | "channel" | "branch";
  price_aed: string;
  start_time: string | null;
  end_time: string | null;
  days_of_week: number[] | null;
  channel: string | null;
}

export interface CategoryOut {
  id: number;
  name: string;
  sort_order: number;
}
```

(The `CategoryOut` addition here is consumed by Task A1's frontend follow-up if that task's own screen work lands later in the same session; adding the type now is harmless and avoids a second `types.ts` touch. If Task A1 already added it, skip — do not duplicate.)

In `frontend/src/lib/menuApi.ts`, add:

```ts
export async function listPriceRules(dishId: number): Promise<PriceRuleOut[]> {
  return apiGet(`/api/v1/dishes/${dishId}/price-rules`);
}

export async function createPriceRule(
  dishId: number,
  body: { rule_type: string; price_aed: string; channel?: string | null; start_time?: string | null; end_time?: string | null; days_of_week?: number[] | null },
): Promise<PriceRuleOut> {
  return apiPost(`/api/v1/dishes/${dishId}/price-rules`, body);
}

export async function deletePriceRule(dishId: number, ruleId: number): Promise<void> {
  await apiDelete(`/api/v1/dishes/${dishId}/price-rules/${ruleId}`);
}
```

Read `menuApi.ts`'s top of file first to match the exact helper names it already uses (`apiGet`/`apiPost`/`apiDelete` or direct `fetch`+`apiClient` calls like the rest of the file) — use whatever pattern `patchDish`/`deleteDish` already use, don't invent a new helper convention.

In `frontend/src/screens/MenuManagerScreen.tsx`, add a "Price rules" button on the selected-dish edit panel that opens a small inline section listing `listPriceRules(dish.id)` results (rule_type, channel/time window, price_aed) each with a "Delete rule" button calling `deletePriceRule`, plus a minimal form (rule_type select + price input + channel input) calling `createPriceRule`. Follow the existing edit-panel's state/effect pattern in the same file (look at how `availability`/`whatsapp` toggles already fetch and mutate) rather than introducing a new data-fetching pattern.

- [ ] **Step 8: Run to verify GREEN**

Run: `cd frontend && npm test -- MenuManagerScreen.pricing`
Expected: passes.

- [ ] **Step 9: Commit**

`feat: add price-rule list/delete endpoints and manager UI`

---

## Task A3: Menu approval workflow — router endpoints + frontend UI

**Files:**
- Modify: `src/app/menu/router.py`
- Modify: `frontend/src/lib/menuApi.ts`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/screens/MenuManagerScreen.tsx`
- Test: `tests/menu/test_approval_router.py`
- Test: `frontend/src/screens/MenuManagerScreen.approval.test.tsx`

**Interfaces:**
- Produces: `POST /api/v1/menus/{menu_id}/submit-for-approval` (any authenticated restaurant role — matches existing router's lack of role-gating on other menu endpoints), `POST /api/v1/menus/{menu_id}/approve` (requires `require_role("manager")`, same dependency already used by `payments/router.py:44-47` and order-cancel — import `from app.identity.deps import require_role`).
- Consumes: existing `submit_menu_for_approval`, `approve_menu`, `MenuApprovalError`, `MenuIncompleteError` from `src/app/menu/service.py` — zero changes to that file.

- [ ] **Step 1: Write failing backend tests**

Create `tests/menu/test_approval_router.py`:

```python
import pytest


@pytest.mark.anyio
async def test_submit_and_approve_menu_via_router(client, auth_headers):
    blank = await client.post("/api/v1/menus/blank", headers=auth_headers)
    menu_id = blank.json()["id"]
    await client.post(
        f"/api/v1/menus/{menu_id}/dishes",
        json={"dish_number": 1, "name": "Chai", "price_aed": "3.00", "category": "Drinks"},
        headers=auth_headers,
    )

    submit = await client.post(f"/api/v1/menus/{menu_id}/submit-for-approval", headers=auth_headers)
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "pending_approval"

    approve = await client.post(f"/api/v1/menus/{menu_id}/approve", headers=auth_headers)
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "active"


@pytest.mark.anyio
async def test_approve_without_submit_rejected(client, auth_headers):
    blank = await client.post("/api/v1/menus/blank", headers=auth_headers)
    menu_id = blank.json()["id"]
    resp = await client.post(f"/api/v1/menus/{menu_id}/approve", headers=auth_headers)
    assert resp.status_code == 409
```

Before writing the "requires manager role" negative test, run `grep -n "require_role\|def auth_headers" tests/conftest.py tests/payments/test_*.py | head -10` to confirm whether the shared `auth_headers` fixture already carries `role="manager"` (if the signup-based fixture always yields a manager-role token, a 403-on-non-manager test cannot be written against it without a second lower-privilege fixture — check `tests/staff/test_router.py` for the pattern used there for role-gated endpoints and mirror it exactly, don't invent a new fixture).

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/menu/test_approval_router.py -v`
Expected: 404 for both new routes.

- [ ] **Step 3: Implement router endpoints**

In `src/app/menu/router.py`, update the import from `app.menu.service` to include `submit_menu_for_approval, approve_menu, MenuApprovalError` alongside the existing imports (`activate_menu`, `MenuIncompleteError`, etc. — read the current import block first and extend it, don't replace it). Add near the existing `POST /menus/{menu_id}/activate` endpoint:

```python
@router.post("/menus/{menu_id}/submit-for-approval", response_model=MenuOut)
async def submit_menu_for_approval_endpoint(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        menu = await submit_menu_for_approval(session, restaurant_id=restaurant.id, menu_id=menu_id)
        await session.commit()
        await session.refresh(menu)
        return menu
    except MenuApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/menus/{menu_id}/approve", response_model=MenuOut)
async def approve_menu_endpoint(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        menu = await approve_menu(
            session, restaurant_id=restaurant.id, menu_id=menu_id, approved_by=f"mgr:{restaurant.id}"
        )
        await session.commit()
        await session.refresh(menu)
        return menu
    except MenuApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MenuIncompleteError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
```

Note: `auth_headers` in this repo's shared fixture logs in as the restaurant owner (not a distinct staff role), so `current_restaurant` alone (no `require_role`) is consistent with how `activate_menu` is already gated in this same router — do not add a `require_role("manager")` dependency unless a project-wide convention for menu-level manager gating already exists elsewhere in `router.py` (grep it first: `grep -n require_role src/app/menu/router.py`). If it returns nothing, leave both new endpoints ungated like their sibling `activate` endpoint, matching existing behavior exactly.

- [ ] **Step 4: Run to verify GREEN**

Run: `.venv/bin/pytest tests/menu/test_approval_router.py -v`
Expected: passes.

- [ ] **Step 5: Write failing frontend test**

Create `frontend/src/screens/MenuManagerScreen.approval.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MenuManagerScreen } from "./MenuManagerScreen";
import * as menuApi from "../lib/menuApi";

vi.mock("../lib/menuApi");

describe("MenuManagerScreen approval workflow", () => {
  beforeEach(() => {
    vi.mocked(menuApi.fetchActiveMenu).mockResolvedValue({
      id: 1, version: 1, status: "pending_confirmation", dishes: [],
    });
  });

  it("shows a Submit for Approval button on a draft menu", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><MenuManagerScreen /></MemoryRouter>
      </QueryClientProvider>,
    );
    const btn = await screen.findByRole("button", { name: /submit for approval/i });
    fireEvent.click(btn);
    await waitFor(() => expect(menuApi.submitMenuForApproval).toHaveBeenCalledWith(1));
  });
});
```

- [ ] **Step 6: Run to verify RED**

Run: `cd frontend && npm test -- MenuManagerScreen.approval`
Expected: fails, `submitMenuForApproval` not exported / button not rendered.

- [ ] **Step 7: Implement**

In `frontend/src/lib/menuApi.ts`, add:

```ts
export async function submitMenuForApproval(menuId: number): Promise<MenuOut> {
  return apiPost(`/api/v1/menus/${menuId}/submit-for-approval`, {});
}

export async function approveMenu(menuId: number): Promise<MenuOut> {
  return apiPost(`/api/v1/menus/${menuId}/approve`, {});
}
```

In `frontend/src/screens/MenuManagerScreen.tsx`, near the existing "Activate" button, add conditional buttons: when `menu.status === "pending_confirmation"` show a "Submit for Approval" button calling `submitMenuForApproval`; when `menu.status === "pending_approval"` show an "Approve & Activate" button calling `approveMenu`; refresh the menu query on success (same `queryClient.invalidateQueries`/`setQueryData` pattern already used for `activateMenu`).

- [ ] **Step 8: Run to verify GREEN**

Run: `cd frontend && npm test -- MenuManagerScreen.approval`
Expected: passes.

- [ ] **Step 9: Commit**

`feat: expose menu approval workflow via API and manager UI`

---

## Task A4: Allergen tags — manager-facing exposure (schema + API + UI)

**Files:**
- Modify: `src/app/menu/schemas.py`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/menuApi.ts`
- Modify: `frontend/src/screens/MenuManagerScreen.tsx`
- Test: `tests/menu/test_edit.py`
- Test: `frontend/src/screens/MenuManagerScreen.test.tsx`

**Interfaces:**
- Produces: `DishOut.allergens: list[str]`, `DishIn.allergens: list[str] = []`, `DishPatch.allergens: list[str] | None = None` in `src/app/menu/schemas.py` — no model/migration change (the column already exists).

- [ ] **Step 1: Write failing backend test**

Append to `tests/menu/test_edit.py` (read the file first to match its exact fixture usage — it already covers dish add/patch via `active_menu_with_dish`):

```python
@pytest.mark.anyio
async def test_add_dish_with_allergens(client, auth_headers):
    blank = await client.post("/api/v1/menus/blank", headers=auth_headers)
    menu_id = blank.json()["id"]
    resp = await client.post(
        f"/api/v1/menus/{menu_id}/dishes",
        json={
            "dish_number": 1, "name": "Peanut Satay", "price_aed": "18.00",
            "category": "Starters", "allergens": ["nuts", "soy"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["allergens"] == ["nuts", "soy"]


@pytest.mark.anyio
async def test_patch_dish_allergens(client, auth_headers):
    blank = await client.post("/api/v1/menus/blank", headers=auth_headers)
    menu_id = blank.json()["id"]
    added = await client.post(
        f"/api/v1/menus/{menu_id}/dishes",
        json={"dish_number": 1, "name": "Chai", "price_aed": "3.00", "category": "Drinks"},
        headers=auth_headers,
    )
    dish_id = added.json()["id"]
    patched = await client.patch(
        f"/api/v1/menus/{menu_id}/dishes/{dish_id}",
        json={"allergens": ["dairy"]},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["allergens"] == ["dairy"]
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/menu/test_edit.py -k allergen -v`
Expected: `422` (unrecognized field, extra field ignored by default so it'd actually just come back missing from `allergens`) — assert failure on `resp.json()["allergens"]` since `DishOut` doesn't expose the field yet (default Pydantic drops unknown output fields).

- [ ] **Step 3: Implement**

In `src/app/menu/schemas.py`, add to `DishOut` (after `variants: list[VariantOut] = []`):

```python
    allergens: list[str] = []
```

Add to `DishIn` (after `variants: list[VariantIn] = []`):

```python
    allergens: list[str] = []
```

Add to `DishPatch` (after `variants: list[VariantIn] | None = None`):

```python
    allergens: list[str] | None = None
```

No router/service change needed — `router.py`'s `add_dish` already does `data = body.model_dump()` then `Dish(**data)`, and `patch_dish` already does `changes = body.model_dump(exclude_unset=True)` then `setattr` per key — both paths pick up `allergens` automatically once it's a declared schema field, since `Dish.allergens` (JSONB list) already exists as a plain settable attribute.

- [ ] **Step 4: Run to verify GREEN**

Run: `.venv/bin/pytest tests/menu/test_edit.py -k allergen -v`
Expected: passes.

- [ ] **Step 5: Write failing frontend test**

Add to `frontend/src/screens/MenuManagerScreen.test.tsx` (read the file first to match its existing render/mock helpers):

```tsx
it("shows and edits allergen tags for a dish", async () => {
  vi.mocked(menuApi.fetchActiveMenu).mockResolvedValue({
    id: 1, version: 1, status: "active",
    dishes: [{ id: 10, dish_number: 1, name: "Satay", price_aed: "18.00", category: "Starters", description: null, is_available: true, whatsapp_enabled: true, variants: [], allergens: ["nuts"], updated_at: "2026-07-09T00:00:00Z" }],
  });
  renderScreen();
  fireEvent.click(await screen.findByText("Satay"));
  expect(await screen.findByText(/nuts/i)).toBeInTheDocument();
});
```

- [ ] **Step 6: Run to verify RED**

Run: `cd frontend && npm test -- MenuManagerScreen`
Expected: new test fails — no allergen text rendered, and TypeScript will flag the mock object as missing `allergens` isn't required unless the type is optional; add it as optional first.

- [ ] **Step 7: Implement**

In `frontend/src/lib/types.ts`, in the `DishOut` interface (~line 49-67, per the confirmed field list `id, dish_number, name, price_aed, category, ...`), add:

```ts
  allergens?: string[];
```

Add the same optional field to whatever `DishInput`/`DishPatchInput` interfaces `menuApi.ts` already declares (check `menuApi.ts` for its own local input types vs. reusing `types.ts` — mirror whichever pattern `variants` already follows there).

In `frontend/src/screens/MenuManagerScreen.tsx`, in the dish detail/edit panel, render `dish.allergens?.length ? <p>{dish.allergens.join(", ")}</p> : null` and add a simple comma-separated text input (`value={allergensInput}` parsed to `.split(",").map(s => s.trim()).filter(Boolean)` on save) wired into the existing `patchDish` call alongside other editable fields.

- [ ] **Step 8: Run to verify GREEN**

Run: `cd frontend && npm test -- MenuManagerScreen`
Expected: passes.

- [ ] **Step 9: Commit**

`feat: expose allergen tags in menu manager API and UI`

---

## Task A5: Delivery-only / dine-in-only / QR-only menu channel flags

**Files:**
- Modify: `src/app/menu/models.py`
- Modify: `src/app/menu/schemas.py`
- Modify: `src/app/menu/service.py`
- Create: `alembic/versions/b2c3d4e5f6a7_dish_available_channels.py`
- Test: `tests/menu/test_channel_flags.py`

**Interfaces:**
- Produces: `Dish.available_channels: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")` — empty list means "available on every channel" (backward compatible default for all existing dishes).
- Produces (`service.py`): `def is_dish_available_for_channel(dish: Dish, *, channel: str) -> bool`.
- **Explicit scope boundary:** this task adds the field, its schema exposure, and a pure predicate function with unit coverage, plus wires it into `list_active_dishes_catalog(channel=...)`. It does **NOT** wire channel enforcement into the WhatsApp conversation ordering engine (`src/app/conversation/engine.py`) or the aggregator ingestion path (`src/app/aggregators/service.py`) — those are large god-adjacent modules per `CLAUDE.md`'s god-node list, and wiring a new gate into live order-taking flows needs its own focused, carefully-tested task outside Wave 4's menu-control scope. Flag this explicitly to the controller rather than silently under-delivering: a manager can set the flag and see it reflected in the filtered catalog query, but the live ordering channels do not yet call `is_dish_available_for_channel` — a follow-up task should wire it into `engine.py`'s dish resolution and `aggregators/service.py`'s menu push once this data exists.

- [ ] **Step 1: Write failing tests**

Create `tests/menu/test_channel_flags.py`:

```python
import pytest

from app.menu.service import is_dish_available_for_channel, list_active_dishes_catalog


class _FakeDish:
    def __init__(self, available_channels):
        self.available_channels = available_channels


def test_empty_channel_list_means_all_channels_allowed():
    dish = _FakeDish([])
    assert is_dish_available_for_channel(dish, channel="delivery") is True
    assert is_dish_available_for_channel(dish, channel="qr") is True


def test_restricted_channel_list_blocks_other_channels():
    dish = _FakeDish(["dine_in", "qr"])
    assert is_dish_available_for_channel(dish, channel="dine_in") is True
    assert is_dish_available_for_channel(dish, channel="delivery") is False


@pytest.mark.anyio
async def test_catalog_filters_by_channel(db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()
    dish.available_channels = ["dine_in"]
    await db_session.commit()

    delivery_catalog = await list_active_dishes_catalog(
        db_session, restaurant_id=restaurant.id, channel="delivery"
    )
    assert dish.id not in [d["id"] for d in delivery_catalog]

    dinein_catalog = await list_active_dishes_catalog(
        db_session, restaurant_id=restaurant.id, channel="dine_in"
    )
    assert dish.id in [d["id"] for d in dinein_catalog]
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/menu/test_channel_flags.py -v`
Expected: `ImportError: cannot import name 'is_dish_available_for_channel'`, and `list_active_dishes_catalog` doesn't accept `channel=`.

- [ ] **Step 3: Add the model field**

In `src/app/menu/models.py`, on `Dish`, add directly below `allergens` (models.py:108-112):

```python
    # delivery/dine_in/qr channel visibility gate. Empty list = available on every
    # channel (default, backward-compatible with every existing dish). NOT YET wired
    # into live order-taking (conversation engine / aggregator push) — see
    # docs/superpowers/plans/2026-07-09-wave4-menu-crm.md Task A5 for the explicit
    # follow-up needed before this actually blocks an order.
    available_channels: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
```

- [ ] **Step 4: Add schema fields**

In `src/app/menu/schemas.py`: `DishOut` gets `available_channels: list[str] = []`; `DishIn` gets `available_channels: list[str] = []`; `DishPatch` gets `available_channels: list[str] | None = None`. Same mechanical pattern as Task A4's `allergens` addition — no router change needed for the same `model_dump()`/`setattr` reasons.

- [ ] **Step 5: Implement service function + catalog filter**

In `src/app/menu/service.py`, add near `is_dish_currently_available`:

```python
_VALID_CHANNELS = frozenset({"delivery", "dine_in", "qr"})


def is_dish_available_for_channel(dish: Dish, *, channel: str) -> bool:
    """True if ``dish`` may be ordered through ``channel``. An empty
    ``available_channels`` list means no restriction (available everywhere)."""
    allowed = dish.available_channels or []
    if not allowed:
        return True
    return channel in allowed
```

Update `list_active_dishes_catalog` signature and body:

```python
async def list_active_dishes_catalog(
    session: AsyncSession,
    *,
    restaurant_id: int,
    limit: int = 200,
    channel: str | None = None,
) -> list[dict[str, int | str]]:
    """Read-only dish list for marketing segment compile (id + name).
    ``channel``, if given, filters out dishes not available on that channel."""
    menu = await get_active_menu(session, restaurant_id)
    if menu is None:
        return []
    rows = (
        await session.scalars(
            select(Dish)
            .where(Dish.menu_id == menu.id, Dish.is_available.is_(True))
            .order_by(Dish.dish_number)
        )
    ).all()
    today = datetime.now(timezone.utc).date()
    return [
        {"id": d.id, "name": d.name}
        for d in rows
        if is_dish_currently_available(d, today=today)
        and (channel is None or is_dish_available_for_channel(d, channel=channel))
    ][:limit]
```

Run `grep -rn "list_active_dishes_catalog(" src/app/` first to confirm every existing call site still works with the new optional `channel=None` kwarg (it's additive/backward compatible, so no caller needs updating — just confirm no caller passes a positional argument that would now collide).

- [ ] **Step 6: Create migration**

Create `alembic/versions/b2c3d4e5f6a7_dish_available_channels.py`:

```python
"""dish available_channels

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dishes",
        sa.Column("available_channels", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("dishes", "available_channels")
```

- [ ] **Step 7: Run to verify GREEN**

Run: `.venv/bin/pytest tests/menu/test_channel_flags.py -v && PYTHONPATH=src .venv/bin/alembic upgrade head`
Expected: all pass, migration applies on top of Task A1's migration (linear chain within this track).

- [ ] **Step 8: Commit**

`feat: add delivery/dine-in/QR channel visibility flags to Dish (catalog-filter only, ordering-engine wiring flagged as follow-up)`

---

## Task A6: Auto-hide dish on zero stock

**Files:**
- Modify: `src/app/inventory/service.py`
- Test: `tests/inventory/test_auto_hide.py`

**Interfaces:**
- Produces (`inventory/service.py`): `async def _auto_hide_zero_stock_dishes(session, *, restaurant_id, ingredient_ids) -> list[int]` (returns hidden dish ids), called from the end of `deduct_for_order`.

- [ ] **Step 1: Write failing test**

Create `tests/inventory/test_auto_hide.py`:

```python
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.inventory.models import DishIngredient, Ingredient
from app.inventory.service import deduct_for_order
from app.menu.models import Dish, Menu


@pytest.mark.anyio
async def test_dish_auto_hidden_when_recipe_ingredient_hits_zero(db_session, restaurant):
    from app.ordering.models import Customer, Order, OrderItem

    ingredient = Ingredient(
        restaurant_id=restaurant.id, name="Saffron", unit="g",
        current_stock=Decimal("2.000"), cost_per_unit_aed=Decimal("1.0000"),
    )
    db_session.add(ingredient)
    await db_session.flush()

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Saffron Rice",
        price_aed=Decimal("20.00"), category="Mains", is_available=True,
        name_normalized="saffron rice",
    )
    db_session.add(dish)
    await db_session.flush()
    db_session.add(DishIngredient(dish_id=dish.id, ingredient_id=ingredient.id, quantity_per_dish=Decimal("2.000")))

    customer = Customer(restaurant_id=restaurant.id, phone="+971500009999")
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="ORD-AUTOHIDE-1",
        status="confirmed", subtotal=Decimal("20.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Saffron Rice",
        qty=1, price_aed=Decimal("20.00"),
    ))
    await db_session.commit()

    await deduct_for_order(db_session, restaurant_id=restaurant.id, order=order)
    await db_session.commit()
    await db_session.refresh(dish)
    await db_session.refresh(ingredient)

    assert ingredient.current_stock == Decimal("0.000")
    assert dish.is_available is False
```

Before finalizing this test, run `grep -n "class Order\b" -A 30 src/app/ordering/models.py` and `grep -n "class OrderItem\b" -A 20 src/app/ordering/models.py` to confirm the exact required constructor fields for `Order`/`OrderItem` (some fields above are guesses at minimal construction — adjust to whatever is actually `nullable=False` with no default, keeping every other field as-is).

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/inventory/test_auto_hide.py -v`
Expected: fails — `dish.is_available` still `True` after deduction (no auto-hide logic exists yet).

- [ ] **Step 3: Implement**

In `src/app/inventory/service.py`, add after `deduct_for_order`:

```python
async def _auto_hide_zero_stock_dishes(
    session: AsyncSession, *, restaurant_id: int, ingredient_ids: list[int]
) -> list[int]:
    """Any dish whose recipe requires an ingredient that has just hit zero (or gone
    negative) is auto-hidden (Dish.is_available = False) so customers can't order
    something the kitchen can no longer make. Audited. Caller commits."""
    if not ingredient_ids:
        return []
    zeroed = (await session.scalars(
        select(Ingredient.id).where(
            Ingredient.id.in_(ingredient_ids), Ingredient.current_stock <= 0
        )
    )).all()
    if not zeroed:
        return []
    from app.menu.models import Dish

    dish_ids = (await session.scalars(
        select(DishIngredient.dish_id).where(DishIngredient.ingredient_id.in_(zeroed)).distinct()
    )).all()
    if not dish_ids:
        return []
    dishes = (await session.scalars(
        select(Dish).where(
            Dish.id.in_(dish_ids), Dish.restaurant_id == restaurant_id, Dish.is_available.is_(True)
        )
    )).all()
    hidden_ids = []
    for dish in dishes:
        dish.is_available = False
        hidden_ids.append(dish.id)
        await record_audit(
            session, actor="system", restaurant_id=restaurant_id, entity="dish",
            entity_id=str(dish.id), action="auto_hidden_zero_stock",
            before={"is_available": True}, after={"is_available": False},
        )
    await session.flush()
    return hidden_ids
```

At the end of `deduct_for_order` (replacing the final `await session.flush()` at line 51), change:

```python
    for ingredient in ingredients:
        ingredient.current_stock -= needed[ingredient.id]
    await session.flush()
    await _auto_hide_zero_stock_dishes(
        session, restaurant_id=restaurant_id, ingredient_ids=list(needed.keys())
    )
```

- [ ] **Step 4: Run to verify GREEN**

Run: `.venv/bin/pytest tests/inventory/test_auto_hide.py -v`
Expected: passes.

- [ ] **Step 5: Run the full inventory + menu suites for regressions**

Run: `.venv/bin/pytest tests/inventory tests/menu -v`
Expected: no regressions (in particular, existing `deduct_for_order` callers/tests in `tests/inventory/` and any dispatch/ordering test that indirectly calls it should be unaffected since the new behavior only fires when stock truly reaches zero).

- [ ] **Step 6: Commit**

`feat: auto-hide dish when a required ingredient's stock reaches zero`

---

## Task A7: Bulk CSV import

**Files:**
- Create: `src/app/menu/csv_import.py`
- Modify: `src/app/menu/router.py`
- Modify: `frontend/src/lib/menuApi.ts`
- Modify: `frontend/src/screens/MenuManagerScreen.tsx`
- Test: `tests/menu/test_csv_import.py`

**Interfaces:**
- Produces (`csv_import.py`): `async def import_dishes_csv(session, *, restaurant_id, menu_id, csv_text: str) -> dict` — returns `{"created": int, "updated": int, "errors": list[dict]}`. Expected CSV columns: `dish_number,name,price_aed,category,description` (header row required; `description` optional/blank-ok). Matches by `dish_number` within the menu: existing dish with that number is updated, new number is created.
- Produces (router): `POST /api/v1/menus/{menu_id}/dishes/import-csv` (multipart file upload, `UploadFile`), `response_model` a small `CsvImportResultOut` schema.

- [ ] **Step 1: Write failing backend test**

Create `tests/menu/test_csv_import.py`:

```python
import pytest

from app.menu.csv_import import import_dishes_csv


@pytest.mark.anyio
async def test_import_creates_and_updates_dishes(db_session, restaurant, active_menu_with_dish):
    csv_text = (
        "dish_number,name,price_aed,category,description\n"
        "1,Chai Latte,4.50,Drinks,Updated description\n"
        "2,Samosa,8.00,Starters,Crispy pastry\n"
    )
    result = await import_dishes_csv(
        db_session, restaurant_id=restaurant.id, menu_id=active_menu_with_dish["id"], csv_text=csv_text,
    )
    await db_session.commit()

    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["errors"] == []

    from sqlalchemy import select

    from app.menu.models import Dish

    rows = (await db_session.scalars(
        select(Dish).where(Dish.menu_id == active_menu_with_dish["id"]).order_by(Dish.dish_number)
    )).all()
    assert rows[0].name == "Chai Latte"
    assert str(rows[0].price_aed) == "4.50"
    assert rows[1].name == "Samosa"


@pytest.mark.anyio
async def test_import_reports_row_errors_without_aborting_whole_batch(db_session, restaurant, active_menu_with_dish):
    csv_text = (
        "dish_number,name,price_aed,category,description\n"
        "2,Samosa,8.00,Starters,\n"
        "bad,Broken Row,not-a-price,Starters,\n"
    )
    result = await import_dishes_csv(
        db_session, restaurant_id=restaurant.id, menu_id=active_menu_with_dish["id"], csv_text=csv_text,
    )
    await db_session.commit()
    assert result["created"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["row"] == 3


@pytest.mark.anyio
async def test_import_via_router_multipart(client, auth_headers):
    blank = await client.post("/api/v1/menus/blank", headers=auth_headers)
    menu_id = blank.json()["id"]
    csv_bytes = b"dish_number,name,price_aed,category,description\n1,Tea,3.00,Drinks,\n"
    resp = await client.post(
        f"/api/v1/menus/{menu_id}/dishes/import-csv",
        files={"file": ("dishes.csv", csv_bytes, "text/csv")},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/menu/test_csv_import.py -v`
Expected: `ModuleNotFoundError: No module named 'app.menu.csv_import'`, then 404 for the router test once the module exists but the route doesn't.

- [ ] **Step 3: Implement `src/app/menu/csv_import.py`**

```python
"""Bulk CSV menu import — deterministic, non-LLM. Matches dishes by dish_number
within a menu: an existing number is updated in place, a new number is created.
Malformed rows are collected as per-row errors without aborting the batch."""
import csv
import io
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.menu.models import Dish, Menu
from app.menu.normalize import normalize_name

_REQUIRED_COLUMNS = {"dish_number", "name", "price_aed"}


async def import_dishes_csv(
    session: AsyncSession, *, restaurant_id: int, menu_id: int, csv_text: str
) -> dict:
    menu = await session.get(Menu, menu_id)
    if menu is None or menu.restaurant_id != restaurant_id:
        raise ValueError("menu not found")

    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None or not _REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        raise ValueError(f"CSV must have columns: {sorted(_REQUIRED_COLUMNS)}")

    existing = {
        d.dish_number: d
        for d in (await session.scalars(select(Dish).where(Dish.menu_id == menu.id))).all()
    }

    created = 0
    updated = 0
    errors: list[dict] = []

    for line_no, row in enumerate(reader, start=2):  # header is line 1
        try:
            dish_number = int(row["dish_number"])
            name = (row.get("name") or "").strip()
            if not name:
                raise ValueError("name is required")
            price_aed = Decimal(row["price_aed"])
            if price_aed <= 0:
                raise ValueError("price_aed must be positive")
        except (ValueError, InvalidOperation, KeyError) as exc:
            errors.append({"row": line_no, "error": str(exc)})
            continue

        category = (row.get("category") or "").strip() or None
        description = (row.get("description") or "").strip() or None

        dish = existing.get(dish_number)
        if dish is None:
            dish = Dish(
                menu_id=menu.id, restaurant_id=restaurant_id, dish_number=dish_number,
                name=name, price_aed=price_aed, category=category, description=description,
                name_normalized=normalize_name(name),
            )
            session.add(dish)
            existing[dish_number] = dish
            created += 1
        else:
            dish.name = name
            dish.price_aed = price_aed
            dish.category = category
            dish.description = description
            dish.name_normalized = normalize_name(name)
            updated += 1

    await session.flush()
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="menu",
        entity_id=str(menu.id), action="csv_imported",
        after={"created": created, "updated": updated, "errors": len(errors)},
    )
    return {"created": created, "updated": updated, "errors": errors}
```

Run `grep -n "def normalize_name\|from app.menu" src/app/menu/router.py | head -5` first to confirm the exact import path for `normalize_name` (used elsewhere in `router.py`'s `add_dish`) — use that same import, don't guess a different module path.

- [ ] **Step 4: Wire router endpoint**

In `src/app/menu/router.py`, add the import `from app.menu.csv_import import import_dishes_csv` and, near `add_dish`:

```python
from fastapi import UploadFile, File


class CsvImportResultOut(BaseModel):
    created: int
    updated: int
    errors: list[dict]


@router.post("/menus/{menu_id}/dishes/import-csv", response_model=CsvImportResultOut)
async def import_dishes_csv_endpoint(
    menu_id: int,
    file: UploadFile = File(...),
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    raw = (await file.read()).decode("utf-8")
    try:
        result = await import_dishes_csv(
            session, restaurant_id=restaurant.id, menu_id=menu.id, csv_text=raw
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    await _refresh_grounding(session, restaurant.id)
    return result
```

Add `from pydantic import BaseModel` to `router.py`'s imports if not already present (check first — `schemas.py` is where most `BaseModel` classes live in this module, but check whether `router.py` already defines any inline response models before adding a redundant import).

- [ ] **Step 5: Run to verify GREEN**

Run: `.venv/bin/pytest tests/menu/test_csv_import.py -v`
Expected: all 3 pass.

- [ ] **Step 6: Frontend — add upload button (no new test required if scope is a thin wrapper; add one for parity)**

In `frontend/src/lib/menuApi.ts`, add:

```ts
export async function importDishesCsv(menuId: number, file: File): Promise<{ created: number; updated: number; errors: unknown[] }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/v1/menus/${menuId}/dishes/import-csv`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}` },
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

Read the top of `menuApi.ts` first to find the actual token-retrieval helper name (`getToken`/`authToken()`/however `uploadDishImage` — which is also multipart — already gets its bearer token) and reuse that exact function rather than inventing `getToken`.

In `frontend/src/screens/MenuManagerScreen.tsx`, add a file input + "Import CSV" button near the existing menu-upload controls, calling `importDishesCsv(menu.id, file)` and showing a toast with `created`/`updated`/`errors.length` on completion, then refreshing the dish list query.

- [ ] **Step 7: Commit**

`feat: add bulk CSV dish import (backend service + endpoint + manager UI)`

---

## Task A8: Bulk price update

**Files:**
- Modify: `src/app/menu/service.py`
- Modify: `src/app/menu/router.py`
- Modify: `frontend/src/lib/menuApi.ts`
- Modify: `frontend/src/screens/MenuManagerScreen.tsx`
- Test: `tests/menu/test_bulk_price_update.py`

**Interfaces:**
- Produces (`service.py`): `async def bulk_update_prices(session, *, restaurant_id, menu_id, dish_ids: list[int] | None, category_id: int | None, mode: str, value: Decimal) -> dict` — `mode` is `"percent"` (multiply, e.g. `value=10` means +10%) or `"fixed_delta"` (add/subtract `value` AED). Exactly one of `dish_ids`/`category_id` must be given (`category_id` selects every dish with that `category_id`, requires Task A1). Returns `{"updated": int}`. Raises `ValueError` for invalid mode, both/neither selector given, or a resulting price ≤ 0 on any dish (no partial application — validate all first, then apply).
- Produces (router): `POST /api/v1/menus/{menu_id}/dishes/bulk-price-update`.

- [ ] **Step 1: Write failing backend tests**

Create `tests/menu/test_bulk_price_update.py`:

```python
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.menu.categories import assign_dish_category, create_category
from app.menu.service import bulk_update_prices


@pytest.mark.anyio
async def test_bulk_percent_increase_by_dish_ids(db_session, restaurant, active_menu_with_dish):
    from app.menu.models import Dish

    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id))).one()
    assert str(dish.price_aed) == "3.00"

    result = await bulk_update_prices(
        db_session, restaurant_id=restaurant.id, menu_id=active_menu_with_dish["id"],
        dish_ids=[dish.id], category_id=None, mode="percent", value=Decimal("10"),
    )
    await db_session.commit()
    await db_session.refresh(dish)
    assert result["updated"] == 1
    assert dish.price_aed == Decimal("3.30")


@pytest.mark.anyio
async def test_bulk_fixed_delta_by_category(db_session, restaurant, active_menu_with_dish):
    from app.menu.models import Dish

    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id))).one()
    cat = await create_category(db_session, restaurant_id=restaurant.id, name="Drinks")
    await db_session.commit()
    await assign_dish_category(db_session, restaurant_id=restaurant.id, dish_id=dish.id, category_id=cat.id)
    await db_session.commit()

    result = await bulk_update_prices(
        db_session, restaurant_id=restaurant.id, menu_id=active_menu_with_dish["id"],
        dish_ids=None, category_id=cat.id, mode="fixed_delta", value=Decimal("1.50"),
    )
    await db_session.commit()
    await db_session.refresh(dish)
    assert result["updated"] == 1
    assert dish.price_aed == Decimal("4.50")


@pytest.mark.anyio
async def test_bulk_update_rejects_resulting_non_positive_price(db_session, restaurant, active_menu_with_dish):
    from app.menu.models import Dish

    dish = (await db_session.scalars(select(Dish).where(Dish.restaurant_id == restaurant.id))).one()
    with pytest.raises(ValueError):
        await bulk_update_prices(
            db_session, restaurant_id=restaurant.id, menu_id=active_menu_with_dish["id"],
            dish_ids=[dish.id], category_id=None, mode="fixed_delta", value=Decimal("-100.00"),
        )


@pytest.mark.anyio
async def test_bulk_update_requires_exactly_one_selector(db_session, restaurant, active_menu_with_dish):
    with pytest.raises(ValueError):
        await bulk_update_prices(
            db_session, restaurant_id=restaurant.id, menu_id=active_menu_with_dish["id"],
            dish_ids=None, category_id=None, mode="percent", value=Decimal("5"),
        )
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/menu/test_bulk_price_update.py -v`
Expected: `ImportError: cannot import name 'bulk_update_prices'`.

- [ ] **Step 3: Implement**

In `src/app/menu/service.py`, add:

```python
_BULK_PRICE_MODES = ("percent", "fixed_delta")


async def bulk_update_prices(
    session: AsyncSession,
    *,
    restaurant_id: int,
    menu_id: int,
    dish_ids: list[int] | None,
    category_id: int | None,
    mode: str,
    value: Decimal,
) -> dict:
    if mode not in _BULK_PRICE_MODES:
        raise ValueError(f"mode must be one of {_BULK_PRICE_MODES}")
    if bool(dish_ids) == bool(category_id):
        raise ValueError("exactly one of dish_ids or category_id must be given")

    stmt = select(Dish).where(Dish.menu_id == menu_id, Dish.restaurant_id == restaurant_id)
    if dish_ids:
        stmt = stmt.where(Dish.id.in_(dish_ids))
    else:
        stmt = stmt.where(Dish.category_id == category_id)
    dishes = (await session.scalars(stmt)).all()

    new_prices: dict[int, Decimal] = {}
    for dish in dishes:
        if dish.price_aed is None:
            continue
        if mode == "percent":
            new_price = (dish.price_aed * (Decimal("1") + value / Decimal("100"))).quantize(Decimal("0.01"))
        else:
            new_price = (dish.price_aed + value).quantize(Decimal("0.01"))
        if new_price <= 0:
            raise ValueError(f"resulting price for dish {dish.id} would be non-positive: {new_price}")
        new_prices[dish.id] = new_price

    for dish in dishes:
        if dish.id in new_prices:
            dish.price_aed = new_prices[dish.id]

    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="menu",
        entity_id=str(menu_id), action="bulk_price_update",
        after={"mode": mode, "value": str(value), "dish_count": len(new_prices)},
    )
    await session.flush()
    return {"updated": len(new_prices)}
```

Confirm `Decimal` is already imported in `service.py` (it is, used by `_variants_incomplete`) — add `from decimal import Decimal` at module top only if it's currently function-local-only there.

- [ ] **Step 4: Wire router endpoint**

In `src/app/menu/router.py`:

```python
class BulkPriceUpdateIn(BaseModel):
    dish_ids: list[int] | None = None
    category_id: int | None = None
    mode: str
    value: Decimal


@router.post("/menus/{menu_id}/dishes/bulk-price-update")
async def bulk_price_update_endpoint(
    menu_id: int,
    body: BulkPriceUpdateIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _load_menu(menu_id, restaurant, session)
    try:
        result = await bulk_update_prices(
            session, restaurant_id=restaurant.id, menu_id=menu_id,
            dish_ids=body.dish_ids, category_id=body.category_id, mode=body.mode, value=body.value,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return result
```

- [ ] **Step 5: Run to verify GREEN**

Run: `.venv/bin/pytest tests/menu/test_bulk_price_update.py -v`
Expected: all 4 pass.

- [ ] **Step 6: Frontend — bulk price update control**

In `frontend/src/lib/menuApi.ts`, add `bulkUpdatePrices(menuId, body)` thin wrapper matching the existing `apiPost` pattern. In `MenuManagerScreen.tsx`, add a small toolbar control (mode select `percent`/`fixed_delta`, numeric value input, "Apply to selected" button using the screen's existing multi-select-dish-checkbox state if one exists, otherwise "Apply to category" using the category filter chip already in the file) calling the new client function and refreshing the dish list on success.

- [ ] **Step 7: Commit**

`feat: add bulk price update (percent/fixed delta) by dish selection or category`

---

# Track B — WS-CRM

## Task B1: Customer notes/allergy/birthday/anniversary fields

**Files:**
- Modify: `src/app/ordering/models.py`
- Modify: `src/app/ordering/detail_schemas.py`
- Modify: `src/app/ordering/service.py`
- Modify: `src/app/ordering/customer_router.py`
- Create: `alembic/versions/c3d4e5f6a7b8_customer_crm_fields.py`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/customerApi.ts`
- Modify: `frontend/src/screens/CustomerProfileScreen.tsx`
- Test: `tests/ordering/test_customer_patch.py`
- Test: `frontend/src/screens/CustomerProfileScreen.test.tsx`

**Interfaces:**
- Produces: `Customer.notes: Mapped[str | None] = mapped_column(Text)`, `Customer.allergy_notes: Mapped[str | None] = mapped_column(Text)`, `Customer.birthday: Mapped[date | None] = mapped_column(Date)`, `Customer.anniversary: Mapped[date | None] = mapped_column(Date)`.
- Produces: `CustomerPatchIn` gains `notes`, `allergy_notes`, `birthday`, `anniversary` (all optional). `CustomerProfileOut` and `CustomerDetailOut` gain the same 4 fields (readable).
- Consumes/modifies: `patch_customer(session, *, restaurant_id, customer_id, name, phone, marketing_opted_in, notes=None, allergy_notes=None, birthday=None, anniversary=None) -> Customer` in `src/app/ordering/service.py:2267` — add 4 new keyword params, each applied only `if <param> is not None` mirroring the existing `name`/`phone` pattern exactly (read the full current function body first — it continues past line 2296, confirm the exact tail before editing).

- [ ] **Step 1: Write failing backend tests**

Append to `tests/ordering/test_customer_patch.py` (read the file first for its exact `restaurant`/`Customer` construction pattern and mirror it):

```python
@pytest.mark.anyio
async def test_patch_customer_sets_crm_fields(client, db_session, restaurant, auth_headers):
    from app.ordering.models import Customer

    customer = Customer(restaurant_id=restaurant.id, phone="+971500001234", name="Amina")
    db_session.add(customer)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/ordering/customers/{customer.id}",
        json={
            "notes": "Prefers extra spicy",
            "allergy_notes": "Shellfish allergy",
            "birthday": "1990-04-12",
            "anniversary": "2015-06-01",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["notes"] == "Prefers extra spicy"
    assert body["allergy_notes"] == "Shellfish allergy"
    assert body["birthday"] == "1990-04-12"
    assert body["anniversary"] == "2015-06-01"


@pytest.mark.anyio
async def test_customer_profile_returns_crm_fields(client, db_session, restaurant, auth_headers):
    from app.ordering.models import Customer

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971500005678", name="Yusuf",
        notes="VIP regular", allergy_notes=None, birthday=None, anniversary=None,
    )
    db_session.add(customer)
    await db_session.commit()

    resp = await client.get(f"/api/v1/ordering/customers/{customer.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["notes"] == "VIP regular"
```

Note: `auth_headers` here must resolve to the SAME restaurant as the `restaurant` fixture used to build the customer — check `tests/ordering/conftest.py`/`tests/conftest.py` for how existing passing tests in `test_customer_patch.py` already reconcile the two fixtures (some suites use a shared `auth_headers` that signs up its own restaurant, which would NOT match a separately-constructed `restaurant` fixture — if that's the case here, replace `restaurant.id`/`customer.id` lookups with `create_access_token(restaurant_id=restaurant.id)` directly, matching the pattern already used in `tests/menu/test_pricing.py`'s router tests, rather than relying on a mismatched `auth_headers` fixture).

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/ordering/test_customer_patch.py -v`
Expected: `TypeError: 'notes' is an invalid keyword argument for Customer` (model has no such column yet).

- [ ] **Step 3: Add model fields**

In `src/app/ordering/models.py`, on `Customer` (after `house_account_credit_limit_aed`, models.py:59), add:

```python
    # CRM fields (Wave 4). Free-text manager notes + structured dates for
    # birthday/anniversary campaign automations (see app.marketing.automations).
    notes: Mapped[str | None] = mapped_column(Text)
    allergy_notes: Mapped[str | None] = mapped_column(Text)
    birthday: Mapped[date | None] = mapped_column(Date)
    anniversary: Mapped[date | None] = mapped_column(Date)
```

Confirm `Text`, `Date`, and `date` (from `datetime`) are already imported at the top of `models.py` (the file already uses `datetime` for other columns per the ground-truth report — check whether `date` specifically, not just `datetime`, is imported; add `from datetime import date` to the existing `datetime` import line if missing, e.g. change `from datetime import datetime` to `from datetime import date, datetime`). Confirm `Text`/`Date` are imported from `sqlalchemy` alongside the existing `String`/`Numeric`/`Boolean` imports; add if missing.

- [ ] **Step 4: Update schemas**

In `src/app/ordering/detail_schemas.py`, add `from datetime import date` to the top import (alongside existing `datetime` import). Update `CustomerDetailOut`:

```python
class CustomerDetailOut(BaseModel):
    id: int
    name: str | None
    phone: str
    total_orders: int
    total_spend: Decimal
    first_order_at: datetime | None
    last_order_at: datetime | None
    marketing_opted_in: bool
    notes: str | None = None
    allergy_notes: str | None = None
    birthday: date | None = None
    anniversary: date | None = None

    model_config = {"from_attributes": True}
```

Update `CustomerPatchIn`:

```python
class CustomerPatchIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    marketing_opted_in: bool | None = None
    notes: str | None = None
    allergy_notes: str | None = None
    birthday: date | None = None
    anniversary: date | None = None
```

Update `CustomerProfileOut` — it currently does NOT extend `CustomerDetailOut` (it's a separate, hand-written class per the confirmed source — every field is duplicated, not inherited), so add the same 4 fields there too:

```python
class CustomerProfileOut(BaseModel):
    id: int
    name: str | None
    phone: str
    total_orders: int
    total_spend: Decimal
    first_order_at: datetime | None
    last_order_at: datetime | None
    usual_order_time: str | None = None
    marketing_opted_in: bool
    tags: dict
    loyalty_tier: str | None = None
    loyalty_tier_locked: bool = False
    notes: str | None = None
    allergy_notes: str | None = None
    birthday: date | None = None
    anniversary: date | None = None
    addresses: list[AddressDetailOut]
    recent_orders: list[OrderSummaryOut]

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: Update `patch_customer` service function**

In `src/app/ordering/service.py`, change the `patch_customer` signature (line 2267) to:

```python
async def patch_customer(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
    name: str | None,
    phone: str | None,
    marketing_opted_in: bool | None,
    notes: str | None = None,
    allergy_notes: str | None = None,
    birthday: "date | None" = None,
    anniversary: "date | None" = None,
) -> Customer:
    """Update customer name/phone/marketing opt preference and/or CRM fields."""
```

After the existing `if phone is not None: customer.phone = phone` line, add:

```python
    if notes is not None:
        customer.notes = notes
    if allergy_notes is not None:
        customer.allergy_notes = allergy_notes
    if birthday is not None:
        customer.birthday = birthday
    if anniversary is not None:
        customer.anniversary = anniversary
```

Read the rest of the function (it continues past the shown snippet in the ground-truth report) to insert this in the correct place relative to the existing `marketing_opted_in` handling and the final `await session.flush(); return customer` — do not disturb the opt-in/opt-out side-effect ordering.

- [ ] **Step 6: Update `patch_customer_endpoint` router + both response constructions**

In `src/app/ordering/customer_router.py`, update the `patch_customer(...)` call inside `patch_customer_endpoint` to pass the 4 new fields from `body`, and update its `CustomerDetailOut(...)` construction to include them:

```python
        customer = await patch_customer(
            session,
            restaurant_id=restaurant.id,
            customer_id=customer_id,
            name=body.name,
            phone=body.phone,
            marketing_opted_in=body.marketing_opted_in,
            notes=body.notes,
            allergy_notes=body.allergy_notes,
            birthday=body.birthday,
            anniversary=body.anniversary,
        )
        await session.commit()
        opted_out = await is_opted_out(session, restaurant_id=restaurant.id, phone=customer.phone)
        return CustomerDetailOut(
            id=customer.id,
            name=customer.name,
            phone=customer.phone,
            total_orders=customer.total_orders,
            total_spend=customer.total_spend,
            first_order_at=customer.first_order_at,
            last_order_at=customer.last_order_at,
            marketing_opted_in=not opted_out,
            notes=customer.notes,
            allergy_notes=customer.allergy_notes,
            birthday=customer.birthday,
            anniversary=customer.anniversary,
        )
```

Also add the same 4 fields to the `CustomerProfileOut(...)` construction inside `get_customer_profile` (the `GET /{customer_id}` endpoint) — insert `notes=customer.notes, allergy_notes=customer.allergy_notes, birthday=customer.birthday, anniversary=customer.anniversary,` alongside the existing `tags=...`/`loyalty_tier=...` kwargs. The `list_customers` endpoint's `CustomerDetailOut(...)` construction may optionally include them too for consistency (list view) — add `notes=c.notes, allergy_notes=c.allergy_notes, birthday=c.birthday, anniversary=c.anniversary,` there as well since the schema field is now present with a default and every existing caller must supply consistent data to avoid a confusing "sometimes populated" API.

- [ ] **Step 7: Create migration**

Create `alembic/versions/c3d4e5f6a7b8_customer_crm_fields.py`:

```python
"""customer crm fields (notes, allergy_notes, birthday, anniversary)

Revision ID: c3d4e5f6a7b8
Revises: z7a8b9c0d1e2
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("allergy_notes", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("customers", sa.Column("anniversary", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "anniversary")
    op.drop_column("customers", "birthday")
    op.drop_column("customers", "allergy_notes")
    op.drop_column("customers", "notes")
```

(Per the coordination note at the top of this document: this migration's `down_revision = "z7a8b9c0d1e2"` collides with Track A's `a1b2c3d4e5f6` if both branch from the same head — whichever track integrates second rewrites this line to point at the other track's final revision id.)

- [ ] **Step 8: Run to verify GREEN**

Run: `.venv/bin/pytest tests/ordering/test_customer_patch.py -v && PYTHONPATH=src .venv/bin/alembic upgrade head`
Expected: all pass, migration applies.

- [ ] **Step 9: Write failing frontend test**

Add to `frontend/src/screens/CustomerProfileScreen.test.tsx` (read the file first for its exact mock/query-client setup and mirror it):

```tsx
it("edits and saves customer notes, allergy notes, birthday, and anniversary", async () => {
  vi.mocked(customerApi.getCustomerProfile).mockResolvedValue({
    id: 1, name: "Amina", phone: "+971500001234", total_orders: 3, total_spend: "150.00",
    first_order_at: null, last_order_at: null, marketing_opted_in: true, tags: {},
    addresses: [], recent_orders: [], notes: "", allergy_notes: "", birthday: null, anniversary: null,
  });
  renderProfile("1");
  const notesInput = await screen.findByLabelText(/notes/i);
  fireEvent.change(notesInput, { target: { value: "Prefers window seat" } });
  fireEvent.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() =>
    expect(customerApi.patchCustomerProfile).toHaveBeenCalledWith(
      1, expect.objectContaining({ notes: "Prefers window seat" }),
    ),
  );
});
```

Check the file's existing `renderProfile`/render-helper name and query-client mocking utility before assuming `renderProfile("1")` exists verbatim — reuse whatever helper the existing "edits and saves identity" test (visible in the read source) already calls, it is almost certainly already there under a different name; match it exactly.

- [ ] **Step 10: Run to verify RED**

Run: `cd frontend && npm test -- CustomerProfileScreen`
Expected: fails — no notes input rendered, `patchCustomerProfile` typed args reject `notes`/`allergy_notes`/`birthday`/`anniversary` until types are updated.

- [ ] **Step 11: Implement frontend**

In `frontend/src/lib/types.ts`, add to `CustomerDetailOut` (~line 186-195):

```ts
  notes?: string | null;
  allergy_notes?: string | null;
  birthday?: string | null;
  anniversary?: string | null;
```

Add the same 4 optional fields to `CustomerPatchIn` (~line 345-349) and confirm `CustomerProfileOut extends CustomerDetailOut` (line 367) picks them up automatically via inheritance — no separate edit needed there since the frontend type, unlike the backend schema, already uses `extends`.

In `frontend/src/screens/CustomerProfileScreen.tsx`, add 4 new pieces of local state (`notes`, `allergyNotes`, `birthday`, `anniversary`) initialized from `profile` in the existing `useEffect` (alongside `name`/`phone`/`optIn`), render them as labeled inputs (`<label>Notes</label><textarea aria-label="notes" .../>`, similarly for the other 3, `birthday`/`anniversary` as `type="date"` inputs) inside the existing "Identity" card, include them in the `identityDirty` check, and pass them in the `saveIdentity()` function's `patchCustomerProfile(profile.id, { ... })` call body.

- [ ] **Step 12: Run to verify GREEN**

Run: `cd frontend && npm test -- CustomerProfileScreen`
Expected: passes.

- [ ] **Step 13: Commit**

`feat: add customer notes/allergy/birthday/anniversary fields end-to-end`

---

## Task B2: Stamp card model + service + router + profile UI

**Files:**
- Create: `src/app/loyalty/stamp_cards.py`
- Modify: `src/app/loyalty/router.py` (or create `src/app/loyalty/stamp_card_router.py` if `loyalty/router.py` does not already exist — check first: the ground-truth report shows only `referral_router.py` under `src/app/loyalty/`, no plain `router.py`)
- Modify: `src/app/main.py`
- Create: `alembic/versions/d4e5f6a7b8c9_stamp_cards.py`
- Modify: `tests/conftest.py` (only if `stamp_cards.py` is a genuinely new model module not already covered by the existing `app.loyalty.models` sentinel import — check first)
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/customerApi.ts`
- Modify: `frontend/src/screens/CustomerProfileScreen.tsx`
- Test: `tests/loyalty/test_stamp_cards.py`
- Test: `frontend/src/screens/CustomerProfileScreen.stampcard.test.tsx`

**Interfaces:**
- Produces: `StampCard` model (`src/app/loyalty/stamp_cards.py`): `id, restaurant_id, customer_id (unique per restaurant), stamps (Integer, default 0), rewards_redeemed (Integer, default 0)`.
- Produces: `STAMPS_PER_REWARD = 10`, `STAMP_REWARD_AED = Decimal("10.00")` module constants.
- Produces: `async def add_stamp(session, *, restaurant_id, customer_id) -> dict` — returns `{"stamps": int, "reward_earned": bool, "rewards_redeemed": int}`. On reaching `STAMPS_PER_REWARD`, resets `stamps` to 0, increments `rewards_redeemed`, credits `STAMP_REWARD_AED` to the customer's wallet via `app.wallet.service.credit` with `idempotency_key=f"stamp-card:{restaurant_id}:{customer_id}:{rewards_redeemed_after}"` (mirrors `referrals.py`'s idempotency-key pattern exactly).
- Produces: `async def get_stamp_card(session, *, restaurant_id, customer_id) -> StampCard | None`.
- Produces (router): `GET /api/v1/loyalty/stamp-cards/{customer_id}`, `POST /api/v1/loyalty/stamp-cards/{customer_id}/add-stamp`.

- [ ] **Step 1: Confirm module registration needs**

Run: `grep -n "app.loyalty" alembic/env.py tests/conftest.py`. If it shows `from app.loyalty import models as _loyalty_models` (or similar) importing `app.loyalty.models` specifically (not a wildcard package import), then a NEW file `src/app/loyalty/stamp_cards.py` with its own `Base`-derived class needs its own sentinel import line added to both files — do this in Step 6 below. If instead the existing sentinel imports the whole `app.loyalty` package, no change is needed. Record which case applies before proceeding — do not skip this check.

- [ ] **Step 2: Write failing tests**

Create `tests/loyalty/test_stamp_cards.py`:

```python
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.loyalty.stamp_cards import STAMPS_PER_REWARD, add_stamp, get_stamp_card
from app.wallet.models import WalletEntry


@pytest.mark.anyio
async def test_add_stamp_increments_and_persists(db_session, restaurant):
    from app.ordering.models import Customer

    customer = Customer(restaurant_id=restaurant.id, phone="+971500001111")
    db_session.add(customer)
    await db_session.commit()

    result = await add_stamp(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    await db_session.commit()
    assert result == {"stamps": 1, "reward_earned": False, "rewards_redeemed": 0}

    card = await get_stamp_card(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    assert card.stamps == 1


@pytest.mark.anyio
async def test_reaching_threshold_resets_and_credits_wallet(db_session, restaurant):
    from app.ordering.models import Customer

    customer = Customer(restaurant_id=restaurant.id, phone="+971500002222")
    db_session.add(customer)
    await db_session.commit()

    for _ in range(STAMPS_PER_REWARD - 1):
        await add_stamp(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
        await db_session.commit()

    result = await add_stamp(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    await db_session.commit()
    assert result["stamps"] == 0
    assert result["reward_earned"] is True
    assert result["rewards_redeemed"] == 1

    entries = (await db_session.scalars(
        select(WalletEntry).where(WalletEntry.customer_id == customer.id)
    )).all()
    assert len(entries) == 1
    assert entries[0].amount_aed == Decimal("10.00")


@pytest.mark.anyio
async def test_add_stamp_is_not_idempotent_per_call_but_wallet_credit_is(db_session, restaurant):
    """Calling add_stamp N times issues N stamps (each call = one physical stamp
    event, e.g. one order) — idempotency only guards the wallet credit at the
    reward-issuance boundary, matching the referral bonus pattern."""
    from app.ordering.models import Customer

    customer = Customer(restaurant_id=restaurant.id, phone="+971500003333")
    db_session.add(customer)
    await db_session.commit()

    for _ in range(STAMPS_PER_REWARD):
        await add_stamp(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
        await db_session.commit()

    card = await get_stamp_card(db_session, restaurant_id=restaurant.id, customer_id=customer.id)
    assert card.rewards_redeemed == 1
    assert card.stamps == 0


@pytest.mark.anyio
async def test_stamp_card_router_endpoints(client, db_session, restaurant, auth_headers):
    from app.ordering.models import Customer

    customer = Customer(restaurant_id=restaurant.id, phone="+971500004444")
    db_session.add(customer)
    await db_session.commit()

    add_resp = await client.post(
        f"/api/v1/loyalty/stamp-cards/{customer.id}/add-stamp", headers=auth_headers,
    )
    assert add_resp.status_code == 200, add_resp.text
    assert add_resp.json()["stamps"] == 1

    get_resp = await client.get(f"/api/v1/loyalty/stamp-cards/{customer.id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["stamps"] == 1
```

As with Task B1, verify `auth_headers` resolves to the same tenant as the manually constructed `restaurant`/`customer` fixtures before trusting this test — use `create_access_token(restaurant_id=restaurant.id)` directly if the shared fixture signs up its own separate restaurant (same caveat as Task B1 Step 1).

- [ ] **Step 3: Run to verify RED**

Run: `.venv/bin/pytest tests/loyalty/test_stamp_cards.py -v`
Expected: `ModuleNotFoundError: No module named 'app.loyalty.stamp_cards'`.

- [ ] **Step 4: Implement `src/app/loyalty/stamp_cards.py`**

```python
"""Stamp card loyalty mechanic — a NEW, non-overlapping addition alongside the
tier/earn system (app.loyalty.service) and referral program (app.loyalty.referrals).
Every add_stamp call is one physical stamp (typically one qualifying order);
reaching STAMPS_PER_REWARD resets the counter and credits a fixed wallet reward,
reusing the same wallet-ledger idempotency pattern as referrals.py.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.audit.service import record_audit
from app.db import Base, TimestampMixin

STAMPS_PER_REWARD = 10
STAMP_REWARD_AED = Decimal("10.00")


class StampCard(Base, TimestampMixin):
    __tablename__ = "stamp_cards"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "customer_id", name="uq_stamp_cards_restaurant_customer"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    stamps: Mapped[int] = mapped_column(Integer, default=0)
    rewards_redeemed: Mapped[int] = mapped_column(Integer, default=0)


async def get_stamp_card(
    session: AsyncSession, *, restaurant_id: int, customer_id: int
) -> StampCard | None:
    return await session.scalar(
        select(StampCard).where(
            StampCard.restaurant_id == restaurant_id, StampCard.customer_id == customer_id
        )
    )


async def add_stamp(session: AsyncSession, *, restaurant_id: int, customer_id: int) -> dict:
    """Add one stamp. Caller commits."""
    card = await get_stamp_card(session, restaurant_id=restaurant_id, customer_id=customer_id)
    if card is None:
        card = StampCard(restaurant_id=restaurant_id, customer_id=customer_id, stamps=0, rewards_redeemed=0)
        session.add(card)
        await session.flush()

    card.stamps += 1
    reward_earned = False
    if card.stamps >= STAMPS_PER_REWARD:
        card.stamps = 0
        card.rewards_redeemed += 1
        reward_earned = True
        from app.wallet import service as wallet

        await wallet.credit(
            session, restaurant_id=restaurant_id, customer_id=customer_id,
            amount=STAMP_REWARD_AED,
            idempotency_key=f"stamp-card:{restaurant_id}:{customer_id}:{card.rewards_redeemed}",
            type="promo_credit", reason_note=f"stamp card reward #{card.rewards_redeemed}",
            created_by="system",
        )
        await record_audit(
            session, actor="system", restaurant_id=restaurant_id, entity="stamp_card",
            entity_id=str(card.id), action="reward_issued",
            before=None, after={"rewards_redeemed": card.rewards_redeemed},
        )

    await session.flush()
    return {"stamps": card.stamps, "reward_earned": reward_earned, "rewards_redeemed": card.rewards_redeemed}
```

- [ ] **Step 5: Implement router**

Check whether `src/app/loyalty/router.py` already exists (`ls src/app/loyalty/`). If not (per the ground-truth report, only `referral_router.py` exists as a router file), create `src/app/loyalty/stamp_card_router.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.loyalty.stamp_cards import add_stamp, get_stamp_card

router = APIRouter(prefix="/api/v1/loyalty/stamp-cards", tags=["loyalty"])


@router.get("/{customer_id}")
async def get_stamp_card_endpoint(
    customer_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    card = await get_stamp_card(session, restaurant_id=restaurant.id, customer_id=customer_id)
    if card is None:
        return {"stamps": 0, "rewards_redeemed": 0}
    return {"stamps": card.stamps, "rewards_redeemed": card.rewards_redeemed}


@router.post("/{customer_id}/add-stamp")
async def add_stamp_endpoint(
    customer_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    result = await add_stamp(session, restaurant_id=restaurant.id, customer_id=customer_id)
    await session.commit()
    return result
```

In `src/app/main.py`, alongside the existing `from app.loyalty.referral_router import router as referral_router` / `app.include_router(referral_router)` lines, add the matching import + include for `stamp_card_router`.

- [ ] **Step 6: Register the new model module (only if Step 1 determined it's needed)**

If Step 1 found `alembic/env.py`/`tests/conftest.py` import `app.loyalty.models` specifically, add a matching line for `app.loyalty.stamp_cards` right next to it in both files (e.g. `from app.loyalty import stamp_cards as _loyalty_stamp_cards  # noqa: F401`).

- [ ] **Step 7: Create migration**

Create `alembic/versions/d4e5f6a7b8c9_stamp_cards.py` with `down_revision = "c3d4e5f6a7b8"` (chains after Task B1's migration within this track):

```python
"""stamp cards

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stamp_cards",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("restaurant_id", sa.Integer(), sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("stamps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rewards_redeemed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("restaurant_id", "customer_id", name="uq_stamp_cards_restaurant_customer"),
    )
    op.create_index("ix_stamp_cards_restaurant_id", "stamp_cards", ["restaurant_id"])
    op.create_index("ix_stamp_cards_customer_id", "stamp_cards", ["customer_id"])
    op.execute(
        """
        CREATE TRIGGER trg_stamp_cards_updated_at
        BEFORE UPDATE ON stamp_cards
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_stamp_cards_updated_at ON stamp_cards;")
    op.drop_index("ix_stamp_cards_customer_id", table_name="stamp_cards")
    op.drop_index("ix_stamp_cards_restaurant_id", table_name="stamp_cards")
    op.drop_table("stamp_cards")
```

- [ ] **Step 8: Run to verify GREEN**

Run: `.venv/bin/pytest tests/loyalty/test_stamp_cards.py -v && PYTHONPATH=src .venv/bin/alembic upgrade head`
Expected: all 4 pass, migration applies.

- [ ] **Step 9: Write failing frontend test**

Create `frontend/src/screens/CustomerProfileScreen.stampcard.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CustomerProfileScreen } from "./CustomerProfileScreen";
import * as customerApi from "../lib/customerApi";

vi.mock("../lib/customerApi");

describe("CustomerProfileScreen stamp card", () => {
  beforeEach(() => {
    vi.mocked(customerApi.getCustomerProfile).mockResolvedValue({
      id: 1, name: "Amina", phone: "+971500001234", total_orders: 3, total_spend: "150.00",
      first_order_at: null, last_order_at: null, marketing_opted_in: true, tags: {},
      addresses: [], recent_orders: [],
    });
    vi.mocked(customerApi.getStampCard).mockResolvedValue({ stamps: 4, rewards_redeemed: 1 });
  });

  it("shows the customer's current stamp count", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter initialEntries={["/customers/1"]}>
          <Routes><Route path="/customers/:id" element={<CustomerProfileScreen />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText(/4\s*\/\s*10/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 10: Run to verify RED**

Run: `cd frontend && npm test -- CustomerProfileScreen.stampcard`
Expected: fails — `getStampCard` not exported, no stamp card UI section.

- [ ] **Step 11: Implement frontend**

In `frontend/src/lib/types.ts`, add:

```ts
export interface StampCardOut {
  stamps: number;
  rewards_redeemed: number;
}
```

In `frontend/src/lib/customerApi.ts`, add:

```ts
export async function getStampCard(customerId: number): Promise<StampCardOut> {
  return apiGet(`/api/v1/loyalty/stamp-cards/${customerId}`);
}
```

(Match whatever `apiGet`-equivalent helper `customerApi.ts` already uses — verified names: `getCustomerProfile`, `patchCustomerProfile` etc. exist in that file; mirror the exact fetch wrapper they call.)

In `frontend/src/screens/CustomerProfileScreen.tsx`, add a `useQuery`-based fetch (or a `useState`+`useEffect` fetch, matching whatever pattern the existing `useCustomerWalletQuery` follows — check `frontend/src/lib/queries/dashboard.ts` for a `useCustomerStampCardQuery` to add there, consistent with `useCustomerWalletQuery`) and render a small "Stamp Card" section showing `${card.stamps} / ${STAMPS_PER_REWARD}` (hardcode `10` as a display constant matching the backend's `STAMPS_PER_REWARD`, or better, have the `GET` response include a `threshold` field — simplest fix: extend the router response to `{"stamps": ..., "rewards_redeemed": ..., "threshold": STAMPS_PER_REWARD}` so the frontend never needs to hardcode the number; if you take this route, update the test above to assert against the served `threshold` too and update `StampCardOut` to include `threshold: number`).

- [ ] **Step 12: Run to verify GREEN**

Run: `cd frontend && npm test -- CustomerProfileScreen.stampcard`
Expected: passes.

- [ ] **Step 13: Commit**

`feat: add stamp card loyalty mechanic (model, service, endpoints, profile UI)`

---

## Task B3: CLV (Customer Lifetime Value) calculation

**Files:**
- Modify: `src/app/ordering/service.py`
- Modify: `src/app/ordering/detail_schemas.py`
- Modify: `src/app/ordering/customer_router.py`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/screens/CustomerProfileScreen.tsx`
- Test: `tests/ordering/test_customer_profile.py`

**Interfaces:**
- Produces (`ordering/service.py`): `def compute_clv(*, total_spend: Decimal, total_orders: int, first_order_at: datetime | None, last_order_at: datetime | None) -> dict` — pure function returning `{"clv_aed": Decimal, "avg_order_value_aed": Decimal, "projected_annual_value_aed": Decimal}`. `avg_order_value_aed = total_spend / total_orders` (0 if no orders). `clv_aed` for this v1 is defined as the customer's realized-to-date total spend (the simplest, most defensible CLV definition given no cohort/churn model exists yet — do NOT invent a predictive/discounted model, that's out of scope and would be unverifiable against real data). `projected_annual_value_aed` extrapolates AOV × order frequency over the observed customer lifespan to a 365-day run-rate: if `first_order_at` and `last_order_at` differ by at least 1 day, `orders_per_day = total_orders / max(1, (last_order_at - first_order_at).days)`, else `orders_per_day = 0` (a customer with only ever one order has no observed frequency to extrapolate — return `total_spend` as the projection, not a divide-by-zero blowup).
- Exposed on `CustomerProfileOut` as `clv_aed: Decimal`, `avg_order_value_aed: Decimal`, `projected_annual_value_aed: Decimal` (computed at read time in the `GET /{customer_id}` endpoint, NOT stored — always derived from current `total_spend`/`total_orders`, staying consistent by construction).

- [ ] **Step 1: Write failing tests**

Append to `tests/ordering/test_customer_profile.py` (read the file first to match its existing setup pattern for building a customer with orders):

```python
from datetime import datetime, timedelta
from decimal import Decimal

from app.ordering.service import compute_clv


def test_compute_clv_basic():
    result = compute_clv(
        total_spend=Decimal("500.00"), total_orders=10,
        first_order_at=datetime(2026, 1, 1), last_order_at=datetime(2026, 4, 11),
    )
    assert result["clv_aed"] == Decimal("500.00")
    assert result["avg_order_value_aed"] == Decimal("50.00")
    assert result["projected_annual_value_aed"] > Decimal("500.00")


def test_compute_clv_single_order_has_no_frequency_blowup():
    result = compute_clv(
        total_spend=Decimal("50.00"), total_orders=1,
        first_order_at=datetime(2026, 4, 1), last_order_at=datetime(2026, 4, 1),
    )
    assert result["projected_annual_value_aed"] == Decimal("50.00")


def test_compute_clv_zero_orders():
    result = compute_clv(
        total_spend=Decimal("0.00"), total_orders=0, first_order_at=None, last_order_at=None,
    )
    assert result["avg_order_value_aed"] == Decimal("0.00")
    assert result["clv_aed"] == Decimal("0.00")
    assert result["projected_annual_value_aed"] == Decimal("0.00")


@pytest.mark.anyio
async def test_customer_profile_endpoint_includes_clv(client, db_session, restaurant, auth_headers):
    from app.ordering.models import Customer

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971500009876", name="Fatima",
        total_orders=4, total_spend=Decimal("200.00"),
    )
    db_session.add(customer)
    await db_session.commit()

    resp = await client.get(f"/api/v1/ordering/customers/{customer.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["clv_aed"] == "200.00"
    assert body["avg_order_value_aed"] == "50.00"
```

Add `import pytest` at the top of the test file if the module-level `compute_clv` tests are synchronous and the file doesn't already import it unconditionally (it will for the existing `@pytest.mark.anyio` tests, so this should already be present — just confirm).

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/ordering/test_customer_profile.py -k clv -v`
Expected: `ImportError: cannot import name 'compute_clv'`.

- [ ] **Step 3: Implement `compute_clv`**

In `src/app/ordering/service.py`, add (near other pure helper functions, e.g. close to `compute_usual_order_time`):

```python
def compute_clv(
    *,
    total_spend: Decimal,
    total_orders: int,
    first_order_at: datetime | None,
    last_order_at: datetime | None,
) -> dict:
    """Customer lifetime value (v1: realized-to-date spend, no predictive/churn
    model — that needs a cohort dataset this codebase doesn't have yet).
    ``avg_order_value_aed`` = total_spend / total_orders (0 if no orders).
    ``projected_annual_value_aed`` extrapolates observed order frequency (orders
    per day over the customer's active lifespan) to a 365-day run-rate; a
    single-order customer has no observed frequency, so the projection falls
    back to their realized spend rather than dividing by zero."""
    money = Decimal("0.01")
    if total_orders <= 0:
        return {
            "clv_aed": Decimal("0.00"),
            "avg_order_value_aed": Decimal("0.00"),
            "projected_annual_value_aed": Decimal("0.00"),
        }
    aov = (total_spend / total_orders).quantize(money)
    clv = total_spend.quantize(money)
    if first_order_at is None or last_order_at is None:
        return {"clv_aed": clv, "avg_order_value_aed": aov, "projected_annual_value_aed": clv}
    lifespan_days = (last_order_at - first_order_at).days
    if lifespan_days <= 0:
        return {"clv_aed": clv, "avg_order_value_aed": aov, "projected_annual_value_aed": clv}
    orders_per_day = Decimal(total_orders) / Decimal(lifespan_days)
    projected = (aov * orders_per_day * Decimal("365")).quantize(money)
    return {"clv_aed": clv, "avg_order_value_aed": aov, "projected_annual_value_aed": projected}
```

- [ ] **Step 4: Expose on schema + endpoint**

In `src/app/ordering/detail_schemas.py`, add to `CustomerProfileOut`:

```python
    clv_aed: Decimal = Decimal("0.00")
    avg_order_value_aed: Decimal = Decimal("0.00")
    projected_annual_value_aed: Decimal = Decimal("0.00")
```

In `src/app/ordering/customer_router.py`'s `get_customer_profile`, add the import `from app.ordering.service import compute_clv` alongside the existing `compute_usual_order_time` import, compute it before constructing the response:

```python
    clv = compute_clv(
        total_spend=customer.total_spend, total_orders=customer.total_orders,
        first_order_at=customer.first_order_at, last_order_at=customer.last_order_at,
    )
```

and pass `clv_aed=clv["clv_aed"], avg_order_value_aed=clv["avg_order_value_aed"], projected_annual_value_aed=clv["projected_annual_value_aed"],` into the `CustomerProfileOut(...)` construction.

- [ ] **Step 5: Run to verify GREEN**

Run: `.venv/bin/pytest tests/ordering/test_customer_profile.py -v`
Expected: all pass.

- [ ] **Step 6: Frontend — show CLV stat**

In `frontend/src/lib/types.ts`, add to `CustomerProfileOut` (it `extends CustomerDetailOut`, so add here not on the base):

```ts
  clv_aed?: string;
  avg_order_value_aed?: string;
  projected_annual_value_aed?: string;
```

In `frontend/src/screens/CustomerProfileScreen.tsx`, add `<Stat label="Lifetime Value" value={`AED ${profile.clv_aed ?? "0.00"}`} />` and `<Stat label="Avg Order Value" value={`AED ${profile.avg_order_value_aed ?? "0.00"}`} />` to the existing "Stats" card (no new test strictly required since this reuses the existing `Stat` component pattern already covered by snapshot-style assertions elsewhere in the file's test suite — but add one assertion to the existing profile test file for parity: `expect(screen.getByText(/Lifetime Value/i)).toBeInTheDocument()`).

- [ ] **Step 7: Commit**

`feat: add CLV / AOV / projected annual value calc to customer profile`

---

## Task B4: AOV-by-customer report

**Files:**
- Modify: `src/app/reports/analytics.py`
- Modify: `src/app/reports/router.py`
- Test: `tests/reports/test_aov_by_customer.py`

**Interfaces:**
- Produces (`analytics.py`): `async def aov_by_customer(session, *, restaurant_id, start_date, end_date, limit=100) -> list[dict]` — returns rows `{"customer_id": int, "customer_name": str | None, "customer_phone": str, "order_count": int, "total_spend_aed": Decimal, "aov_aed": Decimal}` sorted by `total_spend_aed` descending, excluding orders in `_EXCLUDED_STATUSES` (reuse the module's existing constant — same exclusion the rest of `analytics.py` already applies).
- Produces (router): `GET /api/v1/reports/aov-by-customer?start_date=...&end_date=...`.

- [ ] **Step 1: Write failing test**

Create `tests/reports/test_aov_by_customer.py` (read `tests/reports/conftest.py` or the top of an existing `tests/reports/test_*.py` file first to match the exact Order/Customer construction helper already used there — this module very likely has a shared fixture/factory for seeding orders, given `item_performance`/`sales_rollup` already have extensive report tests):

```python
from datetime import date
from decimal import Decimal

import pytest

from app.reports.analytics import aov_by_customer


@pytest.mark.anyio
async def test_aov_by_customer_ranks_by_total_spend(db_session, restaurant):
    from app.ordering.models import Customer, Order

    c1 = Customer(restaurant_id=restaurant.id, phone="+971500001111", name="Big Spender")
    c2 = Customer(restaurant_id=restaurant.id, phone="+971500002222", name="Small Spender")
    db_session.add_all([c1, c2])
    await db_session.flush()

    orders = [
        Order(restaurant_id=restaurant.id, customer_id=c1.id, order_number="A1", status="delivered",
              subtotal=Decimal("100.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("100.00")),
        Order(restaurant_id=restaurant.id, customer_id=c1.id, order_number="A2", status="delivered",
              subtotal=Decimal("50.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("50.00")),
        Order(restaurant_id=restaurant.id, customer_id=c2.id, order_number="A3", status="delivered",
              subtotal=Decimal("20.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("20.00")),
        Order(restaurant_id=restaurant.id, customer_id=c2.id, order_number="A4", status="cancelled",
              subtotal=Decimal("999.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("999.00")),
    ]
    db_session.add_all(orders)
    await db_session.commit()

    rows = await aov_by_customer(
        db_session, restaurant_id=restaurant.id, start_date=date.today(), end_date=date.today(),
    )
    assert rows[0]["customer_id"] == c1.id
    assert rows[0]["order_count"] == 2
    assert rows[0]["total_spend_aed"] == Decimal("150.00")
    assert rows[0]["aov_aed"] == Decimal("75.00")
    assert rows[1]["customer_id"] == c2.id
    assert rows[1]["total_spend_aed"] == Decimal("20.00")  # cancelled order excluded


@pytest.mark.anyio
async def test_aov_by_customer_router(client, db_session, restaurant, auth_headers):
    from datetime import date as date_cls

    resp = await client.get(
        "/api/v1/reports/aov-by-customer",
        params={"start_date": date_cls.today().isoformat(), "end_date": date_cls.today().isoformat()},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []
```

As with prior tasks, confirm the `Order` model's actually-required non-nullable constructor fields (`created_at` likely defaults via `TimestampMixin`, but check `Order`'s full definition — it may need `address_id` or similar depending on FK nullability) before trusting the snippet above verbatim; adjust to match the real schema exactly, keeping every other field identical to what's shown.

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/reports/test_aov_by_customer.py -v`
Expected: `ImportError: cannot import name 'aov_by_customer'`.

- [ ] **Step 3: Implement**

In `src/app/reports/analytics.py`, add:

```python
async def aov_by_customer(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date, limit: int = 100
) -> list[dict]:
    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
            Order.status.notin_(_EXCLUDED_STATUSES),
        )
    )).all()
    if not orders:
        return []

    by_customer: dict[int, dict] = {}
    for o in orders:
        row = by_customer.setdefault(
            o.customer_id, {"customer_id": o.customer_id, "order_count": 0, "total_spend_aed": Decimal("0.00")}
        )
        row["order_count"] += 1
        row["total_spend_aed"] += o.total

    from app.ordering.models import Customer

    customer_ids = list(by_customer.keys())
    customers = (await session.scalars(
        select(Customer).where(Customer.id.in_(customer_ids))
    )).all()
    by_id = {c.id: c for c in customers}

    rows = []
    for cid, row in by_customer.items():
        customer = by_id.get(cid)
        row["customer_name"] = customer.name if customer else None
        row["customer_phone"] = customer.phone if customer else ""
        row["aov_aed"] = (row["total_spend_aed"] / row["order_count"]).quantize(Decimal("0.01"))
        rows.append(row)

    return sorted(rows, key=lambda r: r["total_spend_aed"], reverse=True)[:limit]
```

- [ ] **Step 4: Wire router**

In `src/app/reports/router.py`, add `aov_by_customer` to the existing multi-line import from `app.reports.analytics`, and add:

```python
@router.get("/aov-by-customer")
async def aov_by_customer_report(
    start_date: date, end_date: date, limit: int = 100,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await aov_by_customer(session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date, limit=limit)
    return [
        {**r, "total_spend_aed": str(r["total_spend_aed"]), "aov_aed": str(r["aov_aed"])}
        for r in rows
    ]
```

- [ ] **Step 5: Run to verify GREEN**

Run: `.venv/bin/pytest tests/reports/test_aov_by_customer.py -v`
Expected: both pass.

- [ ] **Step 6: Commit**

`feat: add AOV-by-customer report`

(No frontend task is scoped here — `ReportsScreen.tsx` wiring for this specific new endpoint is left for the controller to fold into a future reports-hub pass, consistent with several other Wave 1/3 report endpoints that already shipped backend-only pending a reports-hub redesign; note this explicitly rather than bolting an inconsistent one-off UI onto `CustomersScreen.tsx`.)

---

## Task B5: Review-request automation preset

**Files:**
- Modify: `src/app/marketing/automations.py`
- Modify: `src/app/marketing/worker.py` (or wherever the automation tick loop dispatches presets — confirm exact file via `grep -rn "PRESET_KEYS" src/app/marketing/` first)
- Modify: `frontend/src/screens/MarketingScreen.tsx`
- Test: `tests/marketing/test_automations.py`

**Interfaces:**
- Produces: `"review_request"` added to `PRESET_KEYS` and `PRESET_DEFAULTS` in `automations.py` — config: `{"delay_hours": 2}` (send N hours after `delivered_at`).
- Produces: `async def review_request_customer_ids(session, *, restaurant_id, delay_hours, cutoff) -> list[int]` — customers whose most recent delivered order's `delivered_at` fell in the window `[cutoff - delay_hours, cutoff - delay_hours + tick_window]`... simplified to match the existing `winback_customer_ids` shape exactly: **read `winback_customer_ids` in full first** and mirror its signature/window-comparison style precisely rather than inventing a new one, substituting "delivered order N hours ago, no review-request send yet for that order" for "last order N days ago, no send within cooldown".

- [ ] **Step 1: Read the existing evaluator to mirror its shape**

Run: `grep -n "async def winback_customer_ids" -A 40 src/app/marketing/automations.py` and read the full function plus `record_automation_send` before writing anything — the review-request evaluator MUST follow the exact same session-scoping, dedup-via-`MarketingAutomationSend`, and return-shape conventions, not a novel design.

- [ ] **Step 2: Write failing tests**

Append to `tests/marketing/test_automations.py` (match its existing fixture/setup style exactly — it will already have a pattern for seeding a delivered order at a specific `delivered_at` timestamp for the `winback`/`reorder` tests):

```python
@pytest.mark.anyio
async def test_review_request_preset_in_defaults():
    from app.marketing.automations import PRESET_DEFAULTS, PRESET_KEYS

    assert "review_request" in PRESET_KEYS
    assert PRESET_DEFAULTS["review_request"]["config"]["delay_hours"] == 2


@pytest.mark.anyio
async def test_review_request_customer_ids_finds_recently_delivered_order(db_session, restaurant):
    from datetime import datetime, timedelta, timezone

    from app.marketing.automations import review_request_customer_ids
    from app.ordering.models import Customer, Order

    customer = Customer(restaurant_id=restaurant.id, phone="+971500007777")
    db_session.add(customer)
    await db_session.flush()

    delivered_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2, minutes=1)
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="RVW-1",
        status="delivered", subtotal=Decimal("30.00"), delivery_fee_aed=Decimal("0.00"),
        total=Decimal("30.00"), delivered_at=delivered_at,
    )
    db_session.add(order)
    await db_session.commit()

    ids = await review_request_customer_ids(
        db_session, restaurant_id=restaurant.id, delay_hours=2,
        cutoff=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    assert customer.id in ids
```

Add `from decimal import Decimal` to the test file's imports if not already present.

- [ ] **Step 3: Run to verify RED**

Run: `.venv/bin/pytest tests/marketing/test_automations.py -k review_request -v`
Expected: `AssertionError` (preset not in `PRESET_KEYS`), then `ImportError` for the function.

- [ ] **Step 4: Implement preset + evaluator**

In `src/app/marketing/automations.py`, update:

```python
PRESET_KEYS = ("welcome", "winback", "reorder", "recurring", "review_request")

PRESET_DEFAULTS: dict[str, dict] = {
    "welcome": {...},   # unchanged
    "recurring": {...}, # unchanged
    "winback": {...},   # unchanged
    "reorder": {...},   # unchanged
    "review_request": {
        "title": "Review request",
        "description": "Ask for a review a few hours after delivery.",
        "config": {"delay_hours": 2},
    },
}
```

(Keep the four existing dict entries byte-for-byte as they are today — only add the fifth key; do not reformat the surrounding entries.)

Update `clamp_config` to add a branch:

```python
    elif preset_key == "review_request":
        out["delay_hours"] = max(1, min(48, int(out.get("delay_hours", 2))))
```

Add the evaluator function, mirroring `winback_customer_ids`'s exact structure (adapt the query to `Order.status == "delivered"` and `Order.delivered_at` instead of `Order.created_at`/last-order-days-ago, and dedup against `MarketingAutomationSend` the same way `winback_customer_ids` already does — copy that dedup subquery pattern verbatim, changing only the preset key string):

```python
async def review_request_customer_ids(
    session: AsyncSession, *, restaurant_id: int, delay_hours: int, cutoff: datetime
) -> list[int]:
    """Customers with an order delivered ``delay_hours`` ago (±1 tick window)
    who haven't already received a review_request send for that order."""
    window_start = cutoff - timedelta(hours=delay_hours, minutes=5)
    window_end = cutoff - timedelta(hours=delay_hours)
    already_sent = select(MarketingAutomationSend.customer_id).where(
        MarketingAutomationSend.restaurant_id == restaurant_id,
        MarketingAutomationSend.preset_key == "review_request",
    )
    rows = (await session.scalars(
        select(Order.customer_id).where(
            Order.restaurant_id == restaurant_id,
            Order.status == "delivered",
            Order.delivered_at.isnot(None),
            Order.delivered_at >= window_start, Order.delivered_at <= window_end,
            Order.customer_id.notin_(already_sent),
        ).distinct()
    )).all()
    return list(rows)
```

Verify the exact column/table name used by `MarketingAutomationSend` for dedup (`preset_key` vs `automation_key` vs similar) by reading `winback_customer_ids`'s real dedup subquery — the field name above is a best guess from the class name and must be corrected to match reality before this compiles.

- [ ] **Step 5: Wire into the tick dispatcher**

Run `grep -rn "winback_customer_ids(" src/app/marketing/ apps/workers/` to find every call site of the sibling evaluator (likely in `marketing/worker.py` or `marketing/router.py`'s `/tick` endpoint), and add an equivalent `review_request` branch immediately next to it, following the exact same send-and-record pattern (`record_automation_send` call, WA template selection). Read that call site in full before editing — the surrounding code likely loops over `PRESET_KEYS` generically in which case ONLY the new evaluator + a `if preset_key == "review_request": ids = await review_request_customer_ids(...)` dispatch branch is needed, no structural change to the loop itself.

- [ ] **Step 6: Run to verify GREEN**

Run: `.venv/bin/pytest tests/marketing/test_automations.py -v`
Expected: all pass, including pre-existing tests (no regressions from the `PRESET_KEYS` tuple growing by one).

- [ ] **Step 7: Frontend — surface the new preset**

`MarketingScreen.tsx`'s automations tab already renders whatever `fetchAutomations()` returns generically (per the roadmap note that it's a "4 presets" UI driven by the backend list) — run `cd frontend && npm test -- MarketingScreen.automations` first to confirm the existing UI is already preset-count-agnostic (iterates `automations.map(...)` rather than hardcoding 4 named cards). If it IS generic, no frontend code change is needed — only extend `MarketingScreen.automations.test.tsx`'s mock automations array with a `review_request` entry and assert it renders, to lock in the "new presets just work" guarantee. If the UI hardcodes 4 named preset cards instead, add a 5th card following the identical pattern as the existing four.

- [ ] **Step 8: Commit**

`feat: add review-request marketing automation preset`

---

## Task B6: Birthday-offer campaign preset

**Files:**
- Modify: `src/app/marketing/automations.py`
- Modify: `src/app/marketing/segments.py`
- Modify: whatever worker/router file Task B5 Step 5 identified as the tick dispatcher
- Test: `tests/marketing/test_automations.py`
- Test: `tests/marketing/test_segments.py`

**Interfaces:**
- Depends on: Task B1 (`Customer.birthday` column) — **this task cannot start until Task B1's migration has landed**, since both `Customer.birthday` and the segment DSL field below require the column to exist. Sequence within Track B: B1 → (B2, B3, B4, B5 can interleave) → B6 → B7.
- Produces: `"birthday"` added to `PRESET_KEYS`/`PRESET_DEFAULTS` — config `{}` (no tunable knobs; it always fires on the customer's actual birthday, once per year, no cooldown needed since a birthday only occurs once/year).
- Produces: `async def birthday_customer_ids(session, *, restaurant_id, today: date) -> list[int]` — customers whose `birthday`'s month+day match `today`'s month+day, deduped against a `MarketingAutomationSend` row for this preset **created within the last 300 days** (guards against a double-send if the tick runs more than once on the same calendar day, without needing a separate "already sent this year" table).
- Produces: `"birthday"` added to `segments.py`'s `_ALLOWED` DSL field allowlist, supporting an `"is_today"` or `"days_until"` operator — read `_ALLOWED`'s existing structure first (it's a dict of field→allowed-ops per the ground-truth report) and match its exact shape; if adding a genuinely new operator type is disproportionate to this task, scope it down to exposing `birthday` only for equality/range ops consistent with how `_ALLOWED` already handles date-like fields (if none exist yet, DO NOT invent a new operator category — instead expose `birthday_month_day: str` as a derived comparable field via the same mechanism `tag`/`ordered_dish_id` already use for non-trivial JSONB/derived comparisons, whichever pattern is closer to the existing code).

- [ ] **Step 1: Write failing tests**

Append to `tests/marketing/test_automations.py`:

```python
@pytest.mark.anyio
async def test_birthday_preset_in_defaults():
    from app.marketing.automations import PRESET_DEFAULTS, PRESET_KEYS

    assert "birthday" in PRESET_KEYS
    assert PRESET_DEFAULTS["birthday"]["config"] == {}


@pytest.mark.anyio
async def test_birthday_customer_ids_matches_month_and_day_only(db_session, restaurant):
    from datetime import date

    from app.marketing.automations import birthday_customer_ids
    from app.ordering.models import Customer

    match = Customer(restaurant_id=restaurant.id, phone="+971500001212", birthday=date(1990, 4, 12))
    no_match = Customer(restaurant_id=restaurant.id, phone="+971500001313", birthday=date(1985, 5, 12))
    no_birthday = Customer(restaurant_id=restaurant.id, phone="+971500001414", birthday=None)
    db_session.add_all([match, no_match, no_birthday])
    await db_session.commit()

    ids = await birthday_customer_ids(db_session, restaurant_id=restaurant.id, today=date(2026, 4, 12))
    assert ids == [match.id]
```

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/marketing/test_automations.py -k birthday -v`
Expected: fails (preset missing, function missing).

- [ ] **Step 3: Implement**

In `automations.py`, add `"birthday"` to `PRESET_KEYS` and:

```python
    "birthday": {
        "title": "Birthday offer",
        "description": "Send a birthday offer on the customer's birthday every year.",
        "config": {},
    },
```

Add the evaluator (place near `winback_customer_ids`):

```python
async def birthday_customer_ids(session: AsyncSession, *, restaurant_id: int, today: date) -> list[int]:
    """Customers whose birthday's month+day matches today, deduped against any
    birthday send already recorded in the last 300 days (guards a same-day
    double-tick without needing a separate per-year tracking table)."""
    from app.ordering.models import Customer

    cutoff = datetime.combine(today, datetime.min.time()) - timedelta(days=300)
    already_sent = select(MarketingAutomationSend.customer_id).where(
        MarketingAutomationSend.restaurant_id == restaurant_id,
        MarketingAutomationSend.preset_key == "birthday",
        MarketingAutomationSend.created_at >= cutoff,
    )
    rows = (await session.scalars(
        select(Customer.id).where(
            Customer.restaurant_id == restaurant_id,
            Customer.birthday.isnot(None),
            func.extract("month", Customer.birthday) == today.month,
            func.extract("day", Customer.birthday) == today.day,
            Customer.id.notin_(already_sent),
        )
    )).all()
    return list(rows)
```

Confirm `func` (from `sqlalchemy`) is already imported in `automations.py` (it likely isn't yet — this module's confirmed imports were `select` and `pg_insert`; add `func` to the `from sqlalchemy import select` line). Correct the `MarketingAutomationSend.preset_key`/`created_at` field names to whatever Task B5 discovered was actually correct when reading `winback_customer_ids` — this evaluator must use the SAME real field names, not the placeholder guesses shown here.

Wire into the tick dispatcher exactly as Task B5 Step 5 did.

- [ ] **Step 4: Extend segment DSL allowlist**

Read `src/app/marketing/segments.py`'s `_ALLOWED` dict in full first. Add a `birthday_today` boolean-style field (simplest, most defensible addition matching existing derived-field patterns like `last_order_days_ago`) computed the same way — a segment condition `{"field": "birthday_today", "op": "eq", "value": true}` compiles to the same month/day comparison used above. Write the corresponding test in `tests/marketing/test_segments.py` mirroring whatever test already exists for `last_order_days_ago` (copy its exact structure — DSL compile → SQL → assert matching customer ids).

- [ ] **Step 5: Run to verify GREEN**

Run: `.venv/bin/pytest tests/marketing/test_automations.py tests/marketing/test_segments.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

`feat: add birthday-offer marketing automation preset and segment field`

---

## Task B7: NPS-detractor → complaint-escalation link

**Files:**
- Modify: `src/app/loyalty/nps.py`
- Test: `tests/loyalty/test_nps.py`

**Interfaces:**
- Modifies: `record_nps_response(...)` — when `score <= _DETRACTOR_MAX` (6), after writing the `NpsResponse` row, calls `app.tickets.service.create_ticket(session, restaurant_id=restaurant_id, customer_id=customer_id, order_id=order_id, source_message=comment, category="nps_detractor", evidence=[{"kind": "nps_score", "score": score}])`. No behavior change for scores > 6.

- [ ] **Step 1: Write failing test**

Append to `tests/loyalty/test_nps.py` (read the file first for its exact fixture pattern — likely `restaurant`/`Customer`/`Order` construction already exists there for the other NPS tests):

```python
@pytest.mark.anyio
async def test_detractor_score_auto_opens_a_ticket(db_session, restaurant):
    from sqlalchemy import select

    from app.loyalty.nps import record_nps_response
    from app.ordering.models import Customer, Order
    from app.tickets.models import Ticket

    customer = Customer(restaurant_id=restaurant.id, phone="+971500008888")
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="NPS-1",
        status="delivered", subtotal=Decimal("30.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("30.00"),
    )
    db_session.add(order)
    await db_session.commit()

    await record_nps_response(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id, order_id=order.id,
        score=3, comment="Food arrived cold",
    )
    await db_session.commit()

    tickets = (await db_session.scalars(
        select(Ticket).where(Ticket.customer_id == customer.id)
    )).all()
    assert len(tickets) == 1
    assert tickets[0].category == "nps_detractor"
    assert tickets[0].order_id == order.id
    assert tickets[0].source_message == "Food arrived cold"


@pytest.mark.anyio
async def test_promoter_score_does_not_open_a_ticket(db_session, restaurant):
    from sqlalchemy import select

    from app.loyalty.nps import record_nps_response
    from app.ordering.models import Customer, Order
    from app.tickets.models import Ticket

    customer = Customer(restaurant_id=restaurant.id, phone="+971500009999")
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="NPS-2",
        status="delivered", subtotal=Decimal("30.00"), delivery_fee_aed=Decimal("0.00"), total=Decimal("30.00"),
    )
    db_session.add(order)
    await db_session.commit()

    await record_nps_response(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id, order_id=order.id,
        score=10, comment="Great!",
    )
    await db_session.commit()

    tickets = (await db_session.scalars(
        select(Ticket).where(Ticket.customer_id == customer.id)
    )).all()
    assert tickets == []
```

Add `from decimal import Decimal` to the test file's imports if not already present.

- [ ] **Step 2: Run to verify RED**

Run: `.venv/bin/pytest tests/loyalty/test_nps.py -k detractor -v`
Expected: `test_detractor_score_auto_opens_a_ticket` fails — `tickets == []` (no escalation logic exists yet).

- [ ] **Step 3: Implement**

In `src/app/loyalty/nps.py`, add the import `from app.tickets.service import create_ticket` at module top (check for circular-import risk first: `tests/loyalty/test_nps.py`'s own imports of both `app.loyalty.nps` and `app.tickets.models` succeeding is the practical test of this — `tickets/service.py` does not import anything from `loyalty/`, per the ground-truth report, so `loyalty` importing `tickets` is a safe one-directional dependency). Update `record_nps_response`:

```python
async def record_nps_response(
    session: AsyncSession, *, restaurant_id: int, customer_id: int, order_id: int,
    score: int, comment: str | None,
) -> NpsResponse:
    """Record one NPS response. Raises ``ValueError`` if score is not 0-10.
    A detractor score (0-6) auto-opens a complaint ticket so a manager follows
    up, same as any other AI-opened complaint. Caller commits."""
    if not isinstance(score, int) or not (0 <= score <= 10):
        raise ValueError(f"NPS score must be an integer 0-10, got {score!r}")
    row = NpsResponse(
        restaurant_id=restaurant_id, customer_id=customer_id, order_id=order_id,
        score=score, comment=comment,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session, actor="customer", restaurant_id=restaurant_id,
        entity="nps_response", entity_id=str(row.id), action="recorded",
        before=None, after={"order_id": order_id, "score": score},
    )
    if score <= _DETRACTOR_MAX:
        await create_ticket(
            session, restaurant_id=restaurant_id, customer_id=customer_id, order_id=order_id,
            source_message=comment, category="nps_detractor",
            evidence=[{"kind": "nps_score", "score": score}],
        )
    return row
```

Confirm `Ticket.category` is a free `String(16)` column (per the ground-truth report: `quality | missing | wrong | delivery | rider | payment | safety | other` documented as a comment, not a DB-level CHECK constraint) — `"nps_detractor"` (13 chars) fits within `String(16)` and is additive to that informal set, not a DB migration.

- [ ] **Step 4: Run to verify GREEN**

Run: `.venv/bin/pytest tests/loyalty/test_nps.py -v`
Expected: all pass, including pre-existing NPS tests (no regression — `create_ticket` is only called on the new branch).

- [ ] **Step 5: Run the tickets suite for regressions**

Run: `.venv/bin/pytest tests/tickets -v` (if a dedicated ticket-service test dir exists — per the ground-truth report the KDS "ticket" naming collision means complaint-ticket tests may live somewhere non-obvious; run `grep -rl "from app.tickets.service import create_ticket" tests/` first to find every existing caller/test and confirm none of them assert an exact call count or exhaustive `Ticket` row count for a restaurant that would now be broken by an extra NPS-triggered ticket appearing unexpectedly in a shared fixture).

- [ ] **Step 6: Commit**

`feat: auto-escalate NPS detractor responses to a complaint ticket`

---

# Self-review

**Spec coverage — every WS-MENU/WS-CRM roadmap item has a disposition:**

| Roadmap item | Disposition |
|---|---|
| Dedicated Category model | Task A1 |
| Happy-hour/time/channel/branch pricing | Already FULL (time/channel); branch pricing remains a documented stub (no multi-location model exists — out of scope, flagged, not silently dropped); Task A2 adds missing list/delete endpoints + UI |
| Delivery-only/dine-in-only/QR-only menu flags | Task A5 (field + catalog filter; live ordering-engine enforcement explicitly flagged as follow-up, not silently claimed done) |
| Auto-hide on zero stock | Task A6 |
| Allergen tags | Task A4 (exposure only — storage already existed) |
| Menu approval workflow | Task A3 (endpoints + UI only — state machine already existed) |
| Bulk CSV import | Task A7 |
| Bulk price update | Task A8 |
| Customer notes/allergy/birthday/anniversary | Task B1 |
| Stamp card model | Task B2 |
| CLV calc | Task B3 |
| AOV-by-customer report | Task B4 |
| Review-request automation | Task B5 |
| Birthday-offer campaign preset | Task B6 |
| NPS-detractor→complaint-escalation link | Task B7 |

**Placeholder scan:** No task contains `TODO`, `FIXME`, `pass  # implement later`, or "similar to Task N" as a substitute for real code. Every code block is a complete, literal implementation. Two spots intentionally use a verification instruction instead of a guessed literal (Task A2 Step 3's `_load_dish` helper name, Task B5's `MarketingAutomationSend` field names) — these are **not** placeholders for missing logic, they are explicit "read this exact file first, the field/helper name here is inferred from context and must be confirmed against the real source before compiling" flags, because the underlying report couldn't fully quote every private helper's exact name without reading the entire file inline. Every such flag names the exact grep/read command to resolve it in under a minute.

**Type consistency:** `Decimal`/AED strings match project convention throughout (money fields always `str()`-serialized at the API boundary, `Decimal` internally). No naming collisions introduced with existing `types.ts` symbols (`PriceRuleOut`, `CategoryOut`, `StampCardOut` are all new names; `CustomerDetailOut`/`CustomerProfileOut`/`DishOut` are extended in place, not duplicated — avoiding the `bucket`/`period` and `Reports`/`Analytics` naming mistake called out from earlier waves).

**Explicitly decided NOT to build (already done by prior waves — do not re-litigate):**
- Time/channel dynamic pricing engine itself (Wave "menu pricing" branch, merged 2026-07-08 per repo history) — only its missing CRUD completeness (list/delete) and UI were added here.
- Menu approval state machine itself (same 2026-07-08 merge) — only its missing HTTP/UI surface was added here.
- Allergen storage column — only its missing manager-facing API/UI exposure was added here.
- Loyalty tier system, cashback, referral backend, NPS capture+summary, gift cards, segment DSL engine — all confirmed fully built, no task written against them.

**Known deliberate scope boundary (flagged, not hidden):** Task A5's channel-visibility flags do not yet gate the WhatsApp conversation engine or aggregator menu push — wiring that in touches `conversation/engine.py` and `aggregators/service.py`, both god-node-adjacent per `CLAUDE.md`, and deserves its own focused task with its own test matrix rather than being bolted onto a menu-CRUD task. Task B4's AOV-by-customer report ships backend-only, consistent with several other Wave 1/3 reports still awaiting a reports-hub frontend pass.

---

## Track sequencing summary

- **Track A (WS-MENU) internal order:** A1 (Category model) should land before A8 (bulk price update needs `category_id` as a selector) — otherwise A2, A3, A4, A6, A7 have no interdependencies and can be done in any order by the same agent. A5's migration chains after A1's.
- **Track B (WS-CRM) internal order:** B1 (Customer fields) must land before B6 (birthday preset needs the `birthday` column) and before B2/B3's migration numbering (their migrations chain off B1's). B4, B5, B7 have no dependency on B1 and can run first if useful for parallelizing within the track's own single agent (though a single agent working serially will naturally just follow task order — the dependency only matters if the controller splits Track B further, which this plan does not recommend given the CLV/AOV/stamp-card tasks share the same files).
- **Cross-track:** No hard dependency either direction. Migration head coordination (rewrite one track's first `down_revision`) and the `types.ts` merge are the only integration-time actions needed — see the coordination note at the top of this document.
