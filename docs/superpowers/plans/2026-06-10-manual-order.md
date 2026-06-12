# Manual Order Creation (Dashboard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow restaurant managers to place delivery orders on behalf of walk-in or phone customers directly from the dashboard, bypassing the WhatsApp bot.

**Architecture:** Two new backend endpoints (`GET /api/v1/orders/manual/customer-lookup`, `POST /api/v1/orders/manual`) plus one new menu endpoint (`GET /api/v1/menus/active`). A new `create_manual_order` service function reuses existing `get_or_create_customer`, `upsert_address`, `add_item`, `finalize_confirmation`. A new `NewOrderScreen` React component provides a single-page form. The created order enters the same FSM as bot-placed orders and sends a WhatsApp confirmation via the existing outbox system.

**Tech Stack:** FastAPI, async SQLAlchemy 2, Pydantic v2, React 18 + TypeScript, Vitest, existing OutboxMessage/enqueue_message.

---

## File Map

**Create:**
- `tests/ordering/test_manual_order.py` — backend tests (service + API)
- `frontend/src/lib/manualOrderApi.ts` — `lookupCustomer` + `createManualOrder`
- `frontend/src/screens/NewOrderScreen.tsx` — single-page order form
- `frontend/src/screens/NewOrderScreen.module.css` — styles
- `frontend/src/screens/NewOrderScreen.test.tsx` — vitest tests

**Modify:**
- `src/app/ordering/schemas.py` — add `ManualOrderItemIn`, `ManualOrderAddressIn`, `AddressOut`, `ManualOrderIn`, `CustomerLookupOut`
- `src/app/ordering/service.py` — add `create_manual_order`
- `src/app/ordering/router.py` — add two manual order endpoints (before existing `/{order_id}` routes)
- `src/app/menu/router.py` — add `GET /menus/active`
- `frontend/src/lib/menuApi.ts` — add `fetchActiveMenu`
- `frontend/src/components/NavSidebar.tsx` — add "New Order" nav item
- `frontend/src/App.tsx` — add `/new-order` route

---

### Task 1: Backend Schemas

**Files:**
- Modify: `src/app/ordering/schemas.py`

- [ ] **Step 1: Add new Pydantic schemas**

Open `src/app/ordering/schemas.py`. Add at the bottom, after existing classes:

```python
from pydantic import Field


class ManualOrderItemIn(BaseModel):
    dish_id: int
    qty: int = Field(ge=1, le=50)
    notes: str | None = None


class ManualOrderAddressIn(BaseModel):
    apt_room: str = Field(min_length=1)
    building: str = Field(min_length=1)
    receiver_name: str = Field(min_length=1)
    notes: str | None = None


class AddressOut(BaseModel):
    apt_room: str
    building: str
    receiver_name: str
    notes: str | None


class ManualOrderIn(BaseModel):
    customer_phone: str = Field(min_length=7)
    customer_name: str | None = None
    items: list[ManualOrderItemIn] = Field(min_length=1)
    address: ManualOrderAddressIn
    delivery_fee_aed: Decimal = Decimal("0.00")


class CustomerLookupOut(BaseModel):
    name: str | None
    last_address: AddressOut | None
```

Note: `Decimal` is already imported at the top of `schemas.py`. `Field` needs to be added to the Pydantic import line: change `from pydantic import BaseModel, ConfigDict` to `from pydantic import BaseModel, ConfigDict, Field`.

- [ ] **Step 2: Verify imports compile**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/python -c "from app.ordering.schemas import ManualOrderIn, CustomerLookupOut, AddressOut; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/app/ordering/schemas.py
git commit -m "feat: add manual order Pydantic schemas"
```

---

### Task 2: Backend Service Tests (Failing)

**Files:**
- Create: `tests/ordering/test_manual_order.py`

These tests use the `db_session` and `restaurant` fixtures from `tests/ordering/conftest.py`. They will FAIL until Task 3 implements the service.

- [ ] **Step 1: Create the test file**

```python
# tests/ordering/test_manual_order.py
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.menu.models import Dish, Menu
from app.ordering.models import Order, OrderItem, Customer, CustomerAddress
from app.outbox.models import OutboxMessage


async def _seed_menu(db_session, restaurant_id: int) -> Menu:
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=101, name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=201, name="Mutton Karahi", price_aed=Decimal("35.00"),
        category="Curries", is_available=True, name_normalized="mutton karahi",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=301, name="Unavailable Dish", price_aed=Decimal("10.00"),
        category="Other", is_available=False, name_normalized="unavailable dish",
    ))
    await db_session.commit()
    return menu


async def _get_dish_id(db_session, menu_id: int, name: str) -> int:
    dish = await db_session.scalar(
        select(Dish).where(Dish.menu_id == menu_id, Dish.name == name)
    )
    return dish.id


async def test_create_manual_order_new_customer(db_session, restaurant):
    """New phone → customer created, order confirmed, items correct, SLA set."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")
    karahi_id = await _get_dish_id(db_session, menu.id, "Mutton Karahi")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990001",
        customer_name="Ahmed Al Rashid",
        items=[
            {"dish_id": biryani_id, "qty": 2, "notes": None},
            {"dish_id": karahi_id, "qty": 1, "notes": "extra spicy"},
        ],
        apt_room="Apt 404",
        building="Marina Tower",
        receiver_name="Ahmed Al Rashid",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
    )
    await db_session.commit()

    assert order.status == "confirmed"
    assert order.sla_confirmed_at is not None
    assert order.sla_deadline is not None

    items = (
        await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    assert len(items) == 2
    names = {i.dish_name for i in items}
    assert names == {"Chicken Biryani", "Mutton Karahi"}

    total_items = sum(i.qty for i in items)
    biryani = next(i for i in items if i.dish_name == "Chicken Biryani")
    assert biryani.qty == 2

    assert order.subtotal == Decimal("79.00")   # 22*2 + 35*1
    assert order.total == Decimal("79.00")

    customer = await db_session.scalar(
        select(Customer).where(Customer.phone == "+971509990001")
    )
    assert customer is not None
    assert customer.name == "Ahmed Al Rashid"


async def test_create_manual_order_existing_customer(db_session, restaurant):
    """Known phone → reuses customer row; new address stored."""
    from app.ordering.service import create_manual_order, get_or_create_customer

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    # Pre-create customer
    existing = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971509990002"
    )
    existing.name = "Sara"
    await db_session.commit()

    await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990002",
        customer_name="Sara Updated",   # should NOT overwrite existing name
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="Unit 5",
        building="Gold Tower",
        receiver_name="Sara",
        address_notes=None,
        delivery_fee_aed=Decimal("5.00"),
    )
    await db_session.commit()

    customers = (
        await db_session.scalars(
            select(Customer).where(
                Customer.restaurant_id == restaurant.id,
                Customer.phone == "+971509990002",
            )
        )
    ).all()
    assert len(customers) == 1  # no duplicate
    assert customers[0].name == "Sara"  # original name preserved

    address = await db_session.scalar(
        select(CustomerAddress).where(CustomerAddress.customer_id == customers[0].id)
    )
    assert address is not None
    assert address.building == "Gold Tower"


async def test_create_manual_order_delivery_fee_included_in_total(db_session, restaurant):
    """delivery_fee_aed is added to subtotal in order total."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990003",
        customer_name=None,
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="12A",
        building="Al Noor",
        receiver_name="Guest",
        address_notes=None,
        delivery_fee_aed=Decimal("10.00"),
    )
    await db_session.commit()

    assert order.delivery_fee_aed == Decimal("10.00")
    assert order.subtotal == Decimal("22.00")
    assert order.total == Decimal("32.00")


async def test_create_manual_order_no_active_menu_raises(db_session, restaurant):
    """ValueError raised when no active menu exists."""
    from app.ordering.service import create_manual_order

    with pytest.raises(ValueError, match="No active menu"):
        await create_manual_order(
            db_session,
            restaurant_id=restaurant.id,
            customer_phone="+971509990004",
            customer_name=None,
            items=[{"dish_id": 999, "qty": 1, "notes": None}],
            apt_room="1A",
            building="Tower",
            receiver_name="Guest",
            address_notes=None,
            delivery_fee_aed=Decimal("0.00"),
        )


async def test_create_manual_order_unavailable_dish_raises(db_session, restaurant):
    """ValueError raised when dish is unavailable."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    unavail_id = await _get_dish_id(db_session, menu.id, "Unavailable Dish")

    with pytest.raises(ValueError, match=str(unavail_id)):
        await create_manual_order(
            db_session,
            restaurant_id=restaurant.id,
            customer_phone="+971509990005",
            customer_name=None,
            items=[{"dish_id": unavail_id, "qty": 1, "notes": None}],
            apt_room="1A",
            building="Tower",
            receiver_name="Guest",
            address_notes=None,
            delivery_fee_aed=Decimal("0.00"),
        )


async def test_outbox_message_enqueued_after_manual_order(db_session, restaurant):
    """WhatsApp confirmation OutboxMessage created with correct phone."""
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant.id,
        customer_phone="+971509990006",
        customer_name=None,
        items=[{"dish_id": biryani_id, "qty": 1, "notes": None}],
        apt_room="1A",
        building="Tower",
        receiver_name="Guest",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
    )
    await db_session.commit()

    outbox = (
        await db_session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.restaurant_id == restaurant.id,
                OutboxMessage.to_phone == "+971509990006",
            )
        )
    ).all()
    assert len(outbox) == 1
    assert order.order_number in outbox[0].payload["body"]
```

- [ ] **Step 2: Run tests — verify they all FAIL**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/pytest tests/ordering/test_manual_order.py -v 2>&1 | tail -20
```

Expected: all 6 tests fail with `ImportError` or `cannot import name 'create_manual_order'`.

---

### Task 3: Implement `create_manual_order` Service

**Files:**
- Modify: `src/app/ordering/service.py`

- [ ] **Step 1: Add `create_manual_order` function**

Open `src/app/ordering/service.py`. Add the following function at the end of the file (after `advance_kitchen_status`):

```python
async def create_manual_order(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_phone: str,
    customer_name: str | None,
    items: list[dict],
    apt_room: str,
    building: str,
    receiver_name: str,
    address_notes: str | None,
    delivery_fee_aed: Decimal,
) -> "Order":
    """Create a confirmed delivery order on behalf of a walk-in/phone customer.

    Bypasses the WhatsApp conversation flow. Sends a WhatsApp confirmation
    via the outbox system. Caller must commit after this returns.
    """
    from app.menu.models import Dish, Menu
    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    # 1. Verify active menu exists
    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if not menu:
        raise ValueError("No active menu for this restaurant")

    # 2. Validate all dishes upfront
    validated: list[tuple["Dish", int, str | None]] = []
    for item in items:
        dish = await session.scalar(
            select(Dish).where(
                Dish.id == item["dish_id"],
                Dish.restaurant_id == restaurant_id,
                Dish.is_available.is_(True),
            )
        )
        if not dish:
            raise ValueError(f"Dish {item['dish_id']} not found or unavailable")
        validated.append((dish, item["qty"], item.get("notes")))

    # 3. Get or create customer; only set name if customer is new
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=customer_phone
    )
    if customer_name and customer.name is None:
        customer.name = customer_name
        await session.flush()

    # 4. Store delivery address
    address = await upsert_address(
        session,
        customer_id=customer.id,
        latitude=None,
        longitude=None,
        room_apartment=apt_room,
        building=building,
        receiver_name=receiver_name,
        additional_details=address_notes,
        confirmed=True,
    )

    # 5. Create draft order and wire address + delivery fee
    order = await create_draft_order(
        session, restaurant_id=restaurant_id, customer_id=customer.id
    )
    order.delivery_fee_aed = delivery_fee_aed
    order.address_id = address.id
    await session.flush()

    # 6. Add items (each call recalculates subtotal)
    for dish, qty, notes in validated:
        await add_item(session, order=order, dish=dish, qty=qty, notes=notes)

    # Recompute total including delivery fee (add_item only tracks subtotal)
    order.total = order.subtotal + delivery_fee_aed
    await session.flush()

    # 7. Confirm order (draft → pending_confirmation → confirmed, starts SLA)
    await finalize_confirmation(session, order=order, actor="manager")

    # 8. Enqueue WhatsApp confirmation to customer
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=customer_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={
            "body": (
                f"Your order {order.order_number} has been placed! "
                f"Total: AED {order.total} (COD). "
                f"Your food will arrive in ~40 minutes \U0001f6f5"
            )
        },
        idempotency_key=f"manual-order-confirm-{order.id}",
    )

    return order
```

- [ ] **Step 2: Run service tests — all should pass**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/pytest tests/ordering/test_manual_order.py -v 2>&1 | tail -15
```

Expected: 6 passed.

- [ ] **Step 3: Run full suite to check no regressions**

```bash
.venv/bin/pytest --tb=no -q 2>&1 | tail -5
```

Expected: same pass count as before (≥473 passed, only pre-existing marketing failures).

- [ ] **Step 4: Commit**

```bash
git add src/app/ordering/service.py tests/ordering/test_manual_order.py
git commit -m "feat: create_manual_order service — walk-in order with WhatsApp confirm"
```

---

### Task 4: API Endpoint Tests (Failing)

**Files:**
- Modify: `tests/ordering/test_manual_order.py` (append HTTP tests)

- [ ] **Step 1: Append HTTP API tests to test_manual_order.py**

Add the following to the end of `tests/ordering/test_manual_order.py`:

```python
def _token(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token
    return create_access_token(restaurant_id=restaurant_id)


async def test_api_customer_lookup_found(client, db_session, restaurant):
    """GET /manual/customer-lookup returns name + last address for known phone."""
    from app.ordering.service import get_or_create_customer, upsert_address

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971509991001"
    )
    customer.name = "Lookup User"
    await db_session.flush()
    await upsert_address(
        db_session,
        customer_id=customer.id,
        latitude=None, longitude=None,
        room_apartment="B12",
        building="Creek Tower",
        receiver_name="Lookup User",
        additional_details=None,
        confirmed=True,
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/orders/manual/customer-lookup",
        params={"phone": "+971509991001"},
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Lookup User"
    assert data["last_address"]["building"] == "Creek Tower"
    assert data["last_address"]["apt_room"] == "B12"


async def test_api_customer_lookup_not_found(client, db_session, restaurant):
    """GET /manual/customer-lookup returns 404 for unknown phone."""
    resp = await client.get(
        "/api/v1/orders/manual/customer-lookup",
        params={"phone": "+971509999999"},
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 404


async def test_api_create_manual_order(client, db_session, restaurant):
    """POST /manual creates confirmed order, returns OrderOut."""
    menu = await _seed_menu(db_session, restaurant.id)
    biryani_id = await _get_dish_id(db_session, menu.id, "Chicken Biryani")

    body = {
        "customer_phone": "+971509992001",
        "customer_name": "Walk-in User",
        "items": [{"dish_id": biryani_id, "qty": 2, "notes": None}],
        "address": {
            "apt_room": "Room 7",
            "building": "Hotel Block",
            "receiver_name": "Walk-in User",
            "notes": None,
        },
        "delivery_fee_aed": "0.00",
    }
    resp = await client.post(
        "/api/v1/orders/manual",
        json=body,
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["customer_phone"] == "+971509992001"
    assert len(data["items"]) == 1
    assert data["items"][0]["qty"] == 2
    assert data["total_aed"] == "44.00"


async def test_api_create_manual_order_unavailable_dish_returns_422(client, db_session, restaurant):
    """POST /manual with unavailable dish → 422."""
    menu = await _seed_menu(db_session, restaurant.id)
    unavail_id = await _get_dish_id(db_session, menu.id, "Unavailable Dish")

    body = {
        "customer_phone": "+971509992002",
        "customer_name": None,
        "items": [{"dish_id": unavail_id, "qty": 1, "notes": None}],
        "address": {"apt_room": "1A", "building": "T", "receiver_name": "X", "notes": None},
        "delivery_fee_aed": "0.00",
    }
    resp = await client.post(
        "/api/v1/orders/manual",
        json=body,
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 422


async def test_api_create_manual_order_no_menu_returns_422(client, db_session, restaurant):
    """POST /manual with no active menu → 422."""
    body = {
        "customer_phone": "+971509992003",
        "customer_name": None,
        "items": [{"dish_id": 1, "qty": 1, "notes": None}],
        "address": {"apt_room": "1A", "building": "T", "receiver_name": "X", "notes": None},
        "delivery_fee_aed": "0.00",
    }
    resp = await client.post(
        "/api/v1/orders/manual",
        json=body,
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 422


async def test_api_get_active_menu(client, db_session, restaurant):
    """GET /menus/active returns active menu with dishes."""
    await _seed_menu(db_session, restaurant.id)

    resp = await client.get(
        "/api/v1/menus/active",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    available = [d for d in data["dishes"] if d["is_available"]]
    assert len(available) == 2
```

- [ ] **Step 2: Run new API tests — verify they all FAIL**

```bash
.venv/bin/pytest tests/ordering/test_manual_order.py::test_api_customer_lookup_found \
                 tests/ordering/test_manual_order.py::test_api_create_manual_order \
                 tests/ordering/test_manual_order.py::test_api_get_active_menu -v 2>&1 | tail -15
```

Expected: FAIL — endpoints do not exist yet (404 or connection error).

---

### Task 5: Implement Router Endpoints

**Files:**
- Modify: `src/app/ordering/router.py`
- Modify: `src/app/menu/router.py`

- [ ] **Step 1: Add manual order endpoints to ordering router**

Open `src/app/ordering/router.py`. Update imports at the top:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.ordering.schemas import (
    AddressOut,
    CustomerLookupOut,
    ManualOrderIn,
    OrderItemOut,
    OrderOut,
)
from app.ordering.service import (
    advance_kitchen_status,
    create_manual_order,
    get_last_address,
    get_order_for_tenant,
    get_or_create_customer,
    list_orders_for_tenant,
)
```

Then add two new endpoints **before** the existing `@router.post("/{order_id}/advance", ...)` route. Insert them right after the `_enrich` helper function (around line 75):

```python
@router.get("/manual/customer-lookup", response_model=CustomerLookupOut)
async def customer_lookup(
    phone: str,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CustomerLookupOut:
    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant.id,
            Customer.phone == phone,
        )
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    last_addr = await get_last_address(session, customer_id=customer.id)
    address_out: AddressOut | None = None
    if last_addr:
        address_out = AddressOut(
            apt_room=last_addr.room_apartment or "",
            building=last_addr.building or "",
            receiver_name=last_addr.receiver_name or "",
            notes=last_addr.additional_details,
        )
    return CustomerLookupOut(name=customer.name, last_address=address_out)


@router.post("/manual", response_model=OrderOut)
async def create_manual_order_endpoint(
    body: ManualOrderIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    try:
        order = await create_manual_order(
            session,
            restaurant_id=restaurant.id,
            customer_phone=body.customer_phone,
            customer_name=body.customer_name,
            items=[i.model_dump() for i in body.items],
            apt_room=body.address.apt_room,
            building=body.address.building,
            receiver_name=body.address.receiver_name,
            address_notes=body.address.notes,
            delivery_fee_aed=body.delivery_fee_aed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await session.commit()
    return await _enrich(session, order)
```

- [ ] **Step 2: Add GET /menus/active to menu router**

Open `src/app/menu/router.py`. Add this endpoint **before** the existing `@router.get("/menus/{menu_id}", ...)` route:

```python
@router.get("/menus/active", response_model=MenuOut)
async def get_active_menu(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Return the currently active menu with all dishes for this restaurant."""
    from sqlalchemy import select
    from app.menu.models import Menu
    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant.id,
            Menu.status == "active",
        )
    )
    if not menu:
        raise HTTPException(status_code=404, detail="No active menu")
    # Load dishes via relationship (lazy="selectin" on dishes)
    await session.refresh(menu)
    return menu
```

Make sure `MenuOut` is already imported in `menu/router.py` (it should be — check the existing imports).

- [ ] **Step 3: Run all API tests — all should pass**

```bash
.venv/bin/pytest tests/ordering/test_manual_order.py -v 2>&1 | tail -20
```

Expected: all 12 tests pass (6 service + 6 API).

- [ ] **Step 4: Run lint**

```bash
.venv/bin/ruff check src/app/ordering/router.py src/app/ordering/service.py src/app/ordering/schemas.py src/app/menu/router.py
```

Expected: `All checks passed!`

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest --tb=no -q 2>&1 | tail -5
```

Expected: ≥479 passed (473 previous + 6 new service tests + 6 new API tests — actual count may vary if prior pass count differed).

- [ ] **Step 6: Commit**

```bash
git add src/app/ordering/router.py src/app/ordering/schemas.py src/app/menu/router.py tests/ordering/test_manual_order.py
git commit -m "feat: manual order API endpoints + GET /menus/active"
```

---

### Task 6: Frontend API Layer

**Files:**
- Create: `frontend/src/lib/manualOrderApi.ts`
- Modify: `frontend/src/lib/menuApi.ts`

- [ ] **Step 1: Create `manualOrderApi.ts`**

```typescript
// frontend/src/lib/manualOrderApi.ts
import { ApiError, apiClient } from "./apiClient";
import type { OrderOut } from "./types";

export interface AddressOut {
  apt_room: string;
  building: string;
  receiver_name: string;
  notes: string | null;
}

export interface CustomerLookupOut {
  name: string | null;
  last_address: AddressOut | null;
}

export interface ManualOrderItemIn {
  dish_id: number;
  qty: number;
  notes: string | null;
}

export interface ManualOrderAddressIn {
  apt_room: string;
  building: string;
  receiver_name: string;
  notes: string | null;
}

export interface ManualOrderIn {
  customer_phone: string;
  customer_name: string | null;
  items: ManualOrderItemIn[];
  address: ManualOrderAddressIn;
  delivery_fee_aed: string;
}

export async function lookupCustomer(
  phone: string,
): Promise<CustomerLookupOut | null> {
  try {
    return await apiClient.get<CustomerLookupOut>(
      `/api/v1/orders/manual/customer-lookup?phone=${encodeURIComponent(phone)}`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function createManualOrder(body: ManualOrderIn): Promise<OrderOut> {
  return apiClient.post<OrderOut>("/api/v1/orders/manual", body);
}
```

- [ ] **Step 2: Add `fetchActiveMenu` to `menuApi.ts`**

Append to the end of `frontend/src/lib/menuApi.ts`:

```typescript
export async function fetchActiveMenu(): Promise<MenuOut | null> {
  try {
    return await apiClient.get<MenuOut>("/api/v1/menus/active");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/manualOrderApi.ts frontend/src/lib/menuApi.ts
git commit -m "feat: manualOrderApi + fetchActiveMenu frontend API layer"
```

---

### Task 7: NewOrderScreen Component

**Files:**
- Create: `frontend/src/screens/NewOrderScreen.tsx`
- Create: `frontend/src/screens/NewOrderScreen.module.css`

- [ ] **Step 1: Create `NewOrderScreen.module.css`**

```css
/* frontend/src/screens/NewOrderScreen.module.css */
.screen {
  display: flex;
  flex-direction: column;
  gap: 0;
  max-width: 1100px;
}

.heading {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary, #e2e8f0);
  margin: 0 0 20px 0;
  letter-spacing: 0.5px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  align-items: start;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sectionTitle {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: #0ea5e9;
  text-transform: uppercase;
  margin-bottom: 4px;
}

.divider {
  border: none;
  border-top: 1px solid #1e293b;
  margin: 8px 0;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #64748b;
  text-transform: uppercase;
}

.input {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 4px;
  padding: 7px 10px;
  color: #e2e8f0;
  font-size: 13px;
  outline: none;
  width: 100%;
  box-sizing: border-box;
  font-family: inherit;
}

.input:focus {
  border-color: #0ea5e9;
}

.inputRow {
  display: flex;
  gap: 8px;
}

.inputRow .input {
  flex: 1;
}

.lookupBtn {
  background: #334155;
  border: 1px solid #475569;
  border-radius: 4px;
  padding: 7px 14px;
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.lookupBtn:hover {
  background: #475569;
}

.lookupHint {
  font-size: 10px;
  color: #22c55e;
  min-height: 14px;
}

.lookupHintNew {
  color: #94a3b8;
}

.feeRow {
  display: flex;
  gap: 6px;
}

.feeBtn {
  flex: 1;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 4px;
  padding: 6px 0;
  color: #94a3b8;
  font-size: 11px;
  cursor: pointer;
  text-align: center;
}

.feeBtnActive {
  background: #0ea5e9;
  border-color: #0ea5e9;
  color: #000;
  font-weight: 700;
}

.searchInput {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 4px;
  padding: 6px 10px;
  color: #e2e8f0;
  font-size: 12px;
  outline: none;
  width: 100%;
  box-sizing: border-box;
  font-family: inherit;
  margin-bottom: 4px;
}

.searchInput:focus {
  border-color: #0ea5e9;
}

.categoryLabel {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: #475569;
  text-transform: uppercase;
  margin: 10px 0 4px;
}

.dishRow {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 10px;
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 4px;
  margin-bottom: 3px;
}

.dishRowActive {
  background: #1a2744;
  border-color: #0ea5e9;
}

.dishName {
  font-size: 12px;
  color: #94a3b8;
}

.dishNameActive {
  color: #e2e8f0;
}

.dishPrice {
  font-size: 11px;
  color: #64748b;
  margin-left: 6px;
}

.qtyControls {
  display: flex;
  align-items: center;
  gap: 6px;
}

.qtyBtn {
  width: 22px;
  height: 22px;
  border-radius: 3px;
  border: 1px solid #334155;
  background: #1e293b;
  color: #94a3b8;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.qtyBtnActive {
  background: #0ea5e9;
  border-color: #0ea5e9;
  color: #000;
  font-weight: 700;
}

.qtyValue {
  font-size: 13px;
  color: #475569;
  min-width: 14px;
  text-align: center;
}

.qtyValueActive {
  color: #0ea5e9;
  font-weight: 700;
}

.summary {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 12px;
  margin-top: 12px;
}

.summaryTitle {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: #64748b;
  text-transform: uppercase;
  margin-bottom: 8px;
}

.summaryLine {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 3px;
}

.summaryDivider {
  border: none;
  border-top: 1px solid #1e293b;
  margin: 6px 0;
}

.summaryTotal {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 700;
  color: #e2e8f0;
}

.summaryTotalAmount {
  color: #0ea5e9;
}

.emptyHint {
  font-size: 11px;
  color: #475569;
  text-align: center;
  padding: 12px 0;
}

.bottomBar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #1e293b;
}

.waHint {
  font-size: 11px;
  color: #64748b;
}

.actions {
  display: flex;
  gap: 10px;
}

.cancelBtn {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 4px;
  padding: 8px 18px;
  color: #94a3b8;
  font-size: 13px;
  cursor: pointer;
}

.cancelBtn:hover {
  background: #334155;
}

.placeBtn {
  background: #0ea5e9;
  border: none;
  border-radius: 4px;
  padding: 8px 20px;
  color: #000;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.placeBtn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.errorBanner {
  background: #450a0a;
  border: 1px solid #dc2626;
  border-radius: 4px;
  padding: 10px 14px;
  color: #fca5a5;
  font-size: 12px;
  margin-bottom: 12px;
}

.noMenuBanner {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 13px;
}
```

- [ ] **Step 2: Create `NewOrderScreen.tsx`**

```tsx
// frontend/src/screens/NewOrderScreen.tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchActiveMenu } from "../lib/menuApi";
import {
  createManualOrder,
  lookupCustomer,
} from "../lib/manualOrderApi";
import type { DishOut, MenuOut } from "../lib/types";
import s from "./NewOrderScreen.module.css";

type FeeOption = "0.00" | "5.00" | "10.00";

export function NewOrderScreen() {
  const navigate = useNavigate();

  // Menu
  const [menu, setMenu] = useState<MenuOut | null | "loading">("loading");

  // Customer
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [lookupStatus, setLookupStatus] = useState<
    "idle" | "found" | "new" | "error"
  >("idle");

  // Items
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [search, setSearch] = useState("");

  // Address
  const [aptRoom, setAptRoom] = useState("");
  const [building, setBuilding] = useState("");
  const [receiverName, setReceiverName] = useState("");
  const [addressNotes, setAddressNotes] = useState("");

  // Delivery fee
  const [fee, setFee] = useState<FeeOption>("0.00");

  // Submit
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchActiveMenu().then((m) => setMenu(m));
  }, []);

  async function onLookup() {
    if (!phone.trim()) return;
    try {
      const result = await lookupCustomer(phone.trim());
      if (result) {
        setLookupStatus("found");
        if (result.name) setName(result.name);
        if (result.last_address) {
          setAptRoom(result.last_address.apt_room);
          setBuilding(result.last_address.building);
          setReceiverName(result.last_address.receiver_name);
          setAddressNotes(result.last_address.notes ?? "");
        }
      } else {
        setLookupStatus("new");
      }
    } catch {
      setLookupStatus("error");
    }
  }

  function setQty(dishId: number, delta: number) {
    setQuantities((prev) => {
      const next = (prev[dishId] ?? 0) + delta;
      if (next <= 0) {
        const copy = { ...prev };
        delete copy[dishId];
        return copy;
      }
      return { ...prev, [dishId]: next };
    });
  }

  const dishes: DishOut[] = useMemo(() => {
    if (!menu || menu === "loading") return [];
    return menu.dishes.filter((d) => d.is_available);
  }, [menu]);

  const filteredDishes = useMemo(() => {
    const q = search.toLowerCase();
    return q
      ? dishes.filter(
          (d) =>
            d.name.toLowerCase().includes(q) ||
            String(d.dish_number).includes(q),
        )
      : dishes;
  }, [dishes, search]);

  const categories = useMemo(() => {
    const cats = new Set(filteredDishes.map((d) => d.category ?? "Other"));
    return Array.from(cats).sort();
  }, [filteredDishes]);

  const selectedItems = useMemo(
    () =>
      Object.entries(quantities)
        .filter(([, qty]) => qty > 0)
        .map(([id, qty]) => {
          const dish = dishes.find((d) => d.id === Number(id));
          return dish ? { dish, qty } : null;
        })
        .filter(Boolean) as { dish: DishOut; qty: number }[],
    [quantities, dishes],
  );

  const subtotal = selectedItems.reduce(
    (acc, { dish, qty }) => acc + parseFloat(dish.price_aed ?? "0") * qty,
    0,
  );
  const total = subtotal + parseFloat(fee);

  const canSubmit =
    phone.trim().length >= 7 &&
    selectedItems.length > 0 &&
    aptRoom.trim() &&
    building.trim() &&
    receiverName.trim() &&
    !submitting;

  async function onSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await createManualOrder({
        customer_phone: phone.trim(),
        customer_name: name.trim() || null,
        items: selectedItems.map(({ dish, qty }) => ({
          dish_id: dish.id,
          qty,
          notes: null,
        })),
        address: {
          apt_room: aptRoom.trim(),
          building: building.trim(),
          receiver_name: receiverName.trim(),
          notes: addressNotes.trim() || null,
        },
        delivery_fee_aed: fee,
      });
      navigate("/orders");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to place order.");
      setSubmitting(false);
    }
  }

  if (menu === "loading") return <div className={s.screen}>Loading menu…</div>;

  if (!menu) {
    return (
      <div className={s.screen}>
        <h1 className={s.heading}>New Order</h1>
        <div className={s.noMenuBanner}>
          No active menu found. Activate a menu before placing manual orders.
        </div>
      </div>
    );
  }

  return (
    <div className={s.screen}>
      <h1 className={s.heading}>New Order</h1>

      {error && <div className={s.errorBanner}>{error}</div>}

      <div className={s.grid}>
        {/* LEFT COLUMN */}
        <div>
          <div className={s.section}>
            <div className={s.sectionTitle}>Customer</div>

            <div className={s.field}>
              <label className={s.label}>Phone *</label>
              <div className={s.inputRow}>
                <input
                  className={s.input}
                  value={phone}
                  onChange={(e) => {
                    setPhone(e.target.value);
                    setLookupStatus("idle");
                  }}
                  placeholder="+971 50 123 4567"
                />
                <button className={s.lookupBtn} onClick={onLookup} type="button">
                  Look up
                </button>
              </div>
              <span
                className={`${s.lookupHint} ${lookupStatus === "new" ? s.lookupHintNew : ""}`}
              >
                {lookupStatus === "found" && "✓ Existing customer — details prefilled"}
                {lookupStatus === "new" && "New customer — will be created"}
                {lookupStatus === "error" && "Lookup failed"}
              </span>
            </div>

            <div className={s.field}>
              <label className={s.label}>Name (optional)</label>
              <input
                className={s.input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Customer name"
              />
            </div>
          </div>

          <hr className={s.divider} />

          <div className={s.section}>
            <div className={s.sectionTitle}>Delivery Address</div>

            <div className={s.field}>
              <label className={s.label}>Apt / Room *</label>
              <input
                className={s.input}
                value={aptRoom}
                onChange={(e) => setAptRoom(e.target.value)}
                placeholder="Apt 404"
              />
            </div>

            <div className={s.field}>
              <label className={s.label}>Building *</label>
              <input
                className={s.input}
                value={building}
                onChange={(e) => setBuilding(e.target.value)}
                placeholder="Marina Tower"
              />
            </div>

            <div className={s.field}>
              <label className={s.label}>Receiver Name *</label>
              <input
                className={s.input}
                value={receiverName}
                onChange={(e) => setReceiverName(e.target.value)}
                placeholder="Who receives the order"
              />
            </div>

            <div className={s.field}>
              <label className={s.label}>Notes (optional)</label>
              <input
                className={s.input}
                value={addressNotes}
                onChange={(e) => setAddressNotes(e.target.value)}
                placeholder="Gate code, floor, landmarks…"
              />
            </div>

            <div className={s.field}>
              <label className={s.label}>Delivery Fee</label>
              <div className={s.feeRow}>
                {(
                  [
                    { value: "0.00", label: "Free (≤3 km)" },
                    { value: "5.00", label: "AED 5 (3–5 km)" },
                    { value: "10.00", label: "AED 10 (>5 km)" },
                  ] as { value: FeeOption; label: string }[]
                ).map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    className={`${s.feeBtn} ${fee === value ? s.feeBtnActive : ""}`}
                    onClick={() => setFee(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className={s.section}>
          <div className={s.sectionTitle}>Items</div>

          <input
            className={s.searchInput}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search dishes…"
          />

          {categories.map((cat) => (
            <div key={cat}>
              <div className={s.categoryLabel}>{cat}</div>
              {filteredDishes
                .filter((d) => (d.category ?? "Other") === cat)
                .map((dish) => {
                  const qty = quantities[dish.id] ?? 0;
                  return (
                    <div
                      key={dish.id}
                      className={`${s.dishRow} ${qty > 0 ? s.dishRowActive : ""}`}
                    >
                      <span>
                        <span
                          className={`${s.dishName} ${qty > 0 ? s.dishNameActive : ""}`}
                        >
                          {dish.dish_number}. {dish.name}
                        </span>
                        <span className={s.dishPrice}>
                          · AED {dish.price_aed}
                        </span>
                      </span>
                      <div className={s.qtyControls}>
                        <button
                          type="button"
                          className={s.qtyBtn}
                          onClick={() => setQty(dish.id, -1)}
                          disabled={qty === 0}
                        >
                          −
                        </button>
                        <span
                          className={`${s.qtyValue} ${qty > 0 ? s.qtyValueActive : ""}`}
                        >
                          {qty}
                        </span>
                        <button
                          type="button"
                          className={`${s.qtyBtn} ${qty > 0 ? s.qtyBtnActive : ""}`}
                          onClick={() => setQty(dish.id, 1)}
                        >
                          +
                        </button>
                      </div>
                    </div>
                  );
                })}
            </div>
          ))}

          {selectedItems.length === 0 && (
            <p className={s.emptyHint}>Add at least 1 item to continue.</p>
          )}

          <div className={s.summary}>
            <div className={s.summaryTitle}>Order Summary</div>
            {selectedItems.map(({ dish, qty }) => (
              <div key={dish.id} className={s.summaryLine}>
                <span>
                  {qty}× {dish.name}
                </span>
                <span>
                  AED {(parseFloat(dish.price_aed ?? "0") * qty).toFixed(2)}
                </span>
              </div>
            ))}
            <hr className={s.summaryDivider} />
            <div className={s.summaryLine}>
              <span>Subtotal</span>
              <span>AED {subtotal.toFixed(2)}</span>
            </div>
            <div className={s.summaryLine}>
              <span>Delivery</span>
              <span>{fee === "0.00" ? "Free" : `AED ${fee}`}</span>
            </div>
            <hr className={s.summaryDivider} />
            <div className={s.summaryTotal}>
              <span>TOTAL</span>
              <span className={s.summaryTotalAmount}>
                AED {total.toFixed(2)}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className={s.bottomBar}>
        <span className={s.waHint}>
          {phone.trim()
            ? `📱 WhatsApp confirmation will be sent to ${phone.trim()}`
            : "📱 Enter phone to receive WhatsApp confirmation"}
        </span>
        <div className={s.actions}>
          <button
            className={s.cancelBtn}
            type="button"
            onClick={() => navigate("/orders")}
          >
            Cancel
          </button>
          <button
            className={s.placeBtn}
            type="button"
            disabled={!canSubmit}
            onClick={onSubmit}
          >
            {submitting
              ? "Placing…"
              : `Place Order${total > 0 ? ` — AED ${total.toFixed(2)}` : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/NewOrderScreen.tsx frontend/src/screens/NewOrderScreen.module.css
git commit -m "feat: NewOrderScreen — single-page manual order form"
```

---

### Task 8: NewOrderScreen Tests

**Files:**
- Create: `frontend/src/screens/NewOrderScreen.test.tsx`

- [ ] **Step 1: Create test file**

```tsx
// frontend/src/screens/NewOrderScreen.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NewOrderScreen } from "./NewOrderScreen";

const mockMenu = {
  id: 1,
  version: 1,
  status: "active",
  dishes: [
    {
      id: 10,
      dish_number: 101,
      name: "Chicken Biryani",
      price_aed: "22.00",
      category: "Rice",
      description: null,
      is_available: true,
    },
    {
      id: 11,
      dish_number: 201,
      name: "Mutton Karahi",
      price_aed: "35.00",
      category: "Curries",
      description: null,
      is_available: true,
    },
    {
      id: 12,
      dish_number: 301,
      name: "Unavailable",
      price_aed: "10.00",
      category: "Other",
      description: null,
      is_available: false,
    },
  ],
};

function renderScreen() {
  return render(
    <MemoryRouter>
      <NewOrderScreen />
    </MemoryRouter>,
  );
}

describe("NewOrderScreen", () => {
  beforeEach(() => {
    // Default: active menu exists
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockMenu), { status: 200 }),
      ),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders all main sections", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText("Chicken Biryani")).toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText("+971 50 123 4567")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Apt 404")).toBeInTheDocument();
    expect(screen.getByText(/Place Order/)).toBeInTheDocument();
  });

  it("shows unavailable dishes are hidden", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText("Chicken Biryani")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
  });

  it("+ button increments qty and updates summary total", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText("Chicken Biryani")).toBeInTheDocument(),
    );

    const plusButtons = screen.getAllByText("+");
    fireEvent.click(plusButtons[0]); // first dish (Chicken Biryani)

    await waitFor(() =>
      expect(screen.getByText(/AED 22\.00/)).toBeInTheDocument(),
    );
  });

  it("Place Order button disabled when no items selected", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText("Chicken Biryani")).toBeInTheDocument(),
    );
    const btn = screen.getByRole("button", { name: /Place Order/ });
    expect(btn).toBeDisabled();
  });

  it("phone lookup prefills name and address on found response", async () => {
    const lookupResult = {
      name: "Ahmed Al Rashid",
      last_address: {
        apt_room: "Apt 404",
        building: "Marina Tower",
        receiver_name: "Ahmed",
        notes: null,
      },
    };

    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mockMenu), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(lookupResult), { status: 200 }),
      );

    renderScreen();
    await waitFor(() =>
      expect(screen.getByText("Chicken Biryani")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByPlaceholderText("+971 50 123 4567"), {
      target: { value: "+971501234567" },
    });
    fireEvent.click(screen.getByText("Look up"));

    await waitFor(() =>
      expect(
        screen.getByDisplayValue("Ahmed Al Rashid"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("Marina Tower")).toBeInTheDocument();
  });

  it("shows 'New customer' hint when lookup returns 404", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mockMenu), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
      );

    renderScreen();
    await waitFor(() =>
      expect(screen.getByText("Chicken Biryani")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByPlaceholderText("+971 50 123 4567"), {
      target: { value: "+971509999999" },
    });
    fireEvent.click(screen.getByText("Look up"));

    await waitFor(() =>
      expect(screen.getByText(/New customer/)).toBeInTheDocument(),
    );
  });

  it("no active menu shows banner instead of form", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "No active menu" }), {
        status: 404,
      }),
    );
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/No active menu found/)).toBeInTheDocument(),
    );
    expect(
      screen.queryByPlaceholderText("+971 50 123 4567"),
    ).not.toBeInTheDocument();
  });

  it("successful submit calls POST /manual and navigates to /orders", async () => {
    const confirmedOrder = { id: 99, status: "confirmed", order_number: "R1-0001" };

    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mockMenu), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(confirmedOrder), { status: 200 }),
      );

    renderScreen();
    await waitFor(() =>
      expect(screen.getByText("Chicken Biryani")).toBeInTheDocument(),
    );

    // Fill required fields
    fireEvent.change(screen.getByPlaceholderText("+971 50 123 4567"), {
      target: { value: "+971501234567" },
    });
    fireEvent.click(screen.getAllByText("+")[0]); // add biryani
    fireEvent.change(screen.getByPlaceholderText("Apt 404"), {
      target: { value: "Apt 1" },
    });
    fireEvent.change(screen.getByPlaceholderText("Marina Tower"), {
      target: { value: "Tower A" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("Who receives the order"),
      { target: { value: "Test User" } },
    );

    fireEvent.click(screen.getByRole("button", { name: /Place Order/ }));

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls;
      const postCall = calls.find(
        ([url, opts]) =>
          typeof url === "string" &&
          url.includes("/manual") &&
          (opts as RequestInit)?.method === "POST",
      );
      expect(postCall).toBeDefined();
    });
  });
});
```

- [ ] **Step 2: Run frontend tests**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npx vitest run src/screens/NewOrderScreen.test.tsx 2>&1 | tail -15
```

Expected: 8 tests pass.

- [ ] **Step 3: Run full frontend suite**

```bash
npx vitest run 2>&1 | tail -5
```

Expected: all previous tests still pass + 8 new.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/NewOrderScreen.test.tsx
git commit -m "test: NewOrderScreen — 8 vitest tests"
```

---

### Task 9: Wire Nav and Route

**Files:**
- Modify: `frontend/src/components/NavSidebar.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add nav item to NavSidebar.tsx**

In `frontend/src/components/NavSidebar.tsx`, add the new item to the `ITEMS` array after the `Orders` entry:

```typescript
const ITEMS: Array<{ to: string; label: string; icon: string }> = [
  { to: "/", label: "Home", icon: "🏠" },
  { to: "/orders", label: "Orders", icon: "📋" },
  { to: "/new-order", label: "New Order", icon: "➕" },
  { to: "/menu", label: "Menu", icon: "🍽️" },
  { to: "/riders", label: "Riders", icon: "🛵" },
  { to: "/conversations", label: "Chats", icon: "💬" },
  { to: "/analytics", label: "Reports", icon: "📊" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
];
```

- [ ] **Step 2: Add route to App.tsx**

In `frontend/src/App.tsx`, add the import and route:

```tsx
import { NewOrderScreen } from "./screens/NewOrderScreen";
```

Add the route inside the `<Routes>` block, after the `/orders` route:

```tsx
<Route path="/new-order" element={<Guarded><NewOrderScreen /></Guarded>} />
```

- [ ] **Step 3: TypeScript check**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 4: Run full frontend test suite**

```bash
npx vitest run 2>&1 | tail -5
```

Expected: all tests pass (no regressions from nav changes).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/NavSidebar.tsx frontend/src/App.tsx
git commit -m "feat: wire New Order nav item and route"
```

---

### Task 10: Final Verification + Update understanding.txt

**Files:**
- Modify: `understanding.txt`

- [ ] **Step 1: Run full backend test suite**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/pytest --tb=short -q 2>&1 | tail -10
```

Expected: ≥485 passed (all previous + 12 new backend tests), only pre-existing marketing failures.

- [ ] **Step 2: Run full frontend test suite**

```bash
cd frontend && npx vitest run 2>&1 | tail -5
```

Expected: ≥99 tests passed (91 previous + 8 new).

- [ ] **Step 3: Lint**

```bash
cd ..
.venv/bin/ruff check src apps tests
```

Expected: `All checks passed!`

- [ ] **Step 4: Update understanding.txt**

Append to `understanding.txt`:

```
- [2026-06-10 HH:MM +04] Manual order creation shipped. Walk-in/phone customers can be ordered for directly from dashboard (/new-order screen). Backend: create_manual_order service (get_or_create_customer → upsert_address → create_draft_order → add_item × N → finalize_confirmation → enqueue WhatsApp confirm). Two new endpoints: GET /api/v1/orders/manual/customer-lookup (phone prefill), POST /api/v1/orders/manual (confirmed order). GET /api/v1/menus/active added to menu router. Frontend: NewOrderScreen single-page form (customer + address left, item picker + summary right), manualOrderApi.ts, fetchActiveMenu. Nav: ➕ New Order between Orders and Menu. 12 backend tests + 8 frontend tests all green.
```

- [ ] **Step 5: Final commit**

```bash
git add understanding.txt
git commit -m "chore: update understanding.txt — manual order feature complete"
```

---

## Summary

| Task | Files | Tests |
|---|---|---|
| 1 | `schemas.py` | — |
| 2 | `test_manual_order.py` (service) | 6 failing → |
| 3 | `service.py` | → 6 passing |
| 4 | `test_manual_order.py` (API) | 6 failing → |
| 5 | `router.py`, `menu/router.py` | → 12 passing |
| 6 | `manualOrderApi.ts`, `menuApi.ts` | tsc |
| 7 | `NewOrderScreen.tsx`, `.module.css` | tsc |
| 8 | `NewOrderScreen.test.tsx` | 8 passing |
| 9 | `NavSidebar.tsx`, `App.tsx` | tsc + vitest |
| 10 | `understanding.txt` | final suite |
