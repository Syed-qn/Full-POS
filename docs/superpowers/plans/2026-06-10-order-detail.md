# Order Detail Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a manager clicks an order in the Orders list, a wide tabbed drawer shows full detail: items, address, status timeline with Leaflet GPS route map, WhatsApp chat history, and an inline-editable customer form with marketing opt-in toggle.

**Architecture:** Single rich `GET /api/v1/orders/{id}/detail` endpoint assembles all data server-side. Two PATCH endpoints handle customer and address edits. Frontend upgrades the existing `OrderDetailDrawer` with four tabs — OverviewTab, TimelineTab (Leaflet map), ChatTab, CustomerTab (inline form).

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy 2, Pydantic v2. React 18 + TypeScript, Leaflet.js, Vitest, CSS Modules.

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/app/ordering/detail_schemas.py` | `OrderDetailOut` and all nested schemas |
| Modify | `src/app/ordering/service.py` | add `get_order_detail`, `patch_customer`, `patch_address` |
| Modify | `src/app/marketing/optout.py` | add `record_opt_in` (if not done in AI opt-out plan) |
| Modify | `src/app/ordering/router.py` | add 3 new endpoints before `/{order_id}` routes |
| Create | `tests/ordering/test_order_detail.py` | service + API tests |
| Create | `tests/ordering/test_customer_patch.py` | patch endpoint tests |
| Modify | `frontend/src/lib/types.ts` | add `OrderDetailOut` and nested interfaces |
| Create | `frontend/src/lib/orderDetailApi.ts` | `fetchOrderDetail`, `patchCustomer`, `patchAddress` |
| Modify | `frontend/src/screens/OrderDetailDrawer.tsx` | rewrite with tabs |
| Modify | `frontend/src/screens/OrderDetailDrawer.module.css` | tab styles |

---

### Task 1: `OrderDetailOut` schema

**Files:**
- Create: `src/app/ordering/detail_schemas.py`
- Test: `tests/ordering/test_order_detail.py` (partial)

- [ ] **Step 1: Create `src/app/ordering/detail_schemas.py`**

```python
# src/app/ordering/detail_schemas.py
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, computed_field


class OrderItemDetailOut(BaseModel):
    dish_number: int
    dish_name: str
    qty: int
    price_aed: Decimal

    @computed_field  # type: ignore[misc]
    @property
    def line_total(self) -> Decimal:
        return self.price_aed * self.qty

    model_config = {"from_attributes": True}


class AddressDetailOut(BaseModel):
    id: int
    room_apartment: str | None
    building: str | None
    receiver_name: str | None
    additional_details: str | None
    latitude: float | None
    longitude: float | None

    model_config = {"from_attributes": True}


class CustomerDetailOut(BaseModel):
    id: int
    name: str | None
    phone: str
    total_orders: int
    total_spend: Decimal
    first_order_at: datetime | None
    last_order_at: datetime | None
    marketing_opted_in: bool

    model_config = {"from_attributes": True}


class RiderDetailOut(BaseModel):
    id: int
    name: str
    phone: str

    model_config = {"from_attributes": True}


class TimelineEventOut(BaseModel):
    ts: datetime
    action: str
    actor: str
    after: dict | None


class ChatMessageOut(BaseModel):
    direction: str   # "inbound" | "outbound"
    text: str | None
    ts: int          # unix epoch


class GpsPingOut(BaseModel):
    latitude: float
    longitude: float
    ts: datetime


class OrderDetailOut(BaseModel):
    id: int
    order_number: str
    status: str
    items: list[OrderItemDetailOut]
    address: AddressDetailOut | None
    customer: CustomerDetailOut
    rider: RiderDetailOut | None
    subtotal: Decimal
    delivery_fee_aed: Decimal
    total: Decimal
    created_at: datetime
    delivered_at: datetime | None
    sla_deadline: datetime | None
    timeline: list[TimelineEventOut]
    chat: list[ChatMessageOut]
    route: list[GpsPingOut]


class CustomerPatchIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    marketing_opted_in: bool | None = None


class AddressPatchIn(BaseModel):
    room_apartment: str | None = None
    building: str | None = None
    receiver_name: str | None = None
    additional_details: str | None = None
```

- [ ] **Step 2: Write a minimal import test to confirm schema loads**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/python -c "from app.ordering.detail_schemas import OrderDetailOut; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/app/ordering/detail_schemas.py
git commit -m "feat: add OrderDetailOut and nested schemas in detail_schemas.py"
```

---

### Task 2: `get_order_detail()` service function

**Files:**
- Modify: `src/app/ordering/service.py` (append at end)
- Test: `tests/ordering/test_order_detail.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/ordering/test_order_detail.py`:

```python
# tests/ordering/test_order_detail.py
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ordering.detail_schemas import OrderDetailOut
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.ordering.service import get_order_detail


async def _seed_full_order(db_session, restaurant_id):
    """Seed: menu + customer + address + confirmed order with one item."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()

    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True,
    )
    db_session.add(dish)
    await db_session.flush()

    customer = Customer(
        restaurant_id=restaurant_id, phone="+971501112233",
        name="Sara Al Rashid", total_orders=1,
        total_spend=Decimal("22.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id, room_apartment="Apt 404",
        building="Marina Tower", receiver_name="Sara Al Rashid",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant_id, customer_id=customer.id,
        order_number="R1-0099", status="delivered",
        address_id=addr.id, subtotal=Decimal("22.00"),
        delivery_fee_aed=Decimal("0.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=110,
        dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1,
    )
    db_session.add(item)
    await db_session.commit()
    return order, customer, addr


async def test_get_order_detail_returns_correct_shape(db_session, restaurant):
    order, customer, addr = await _seed_full_order(db_session, restaurant.id)

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert isinstance(detail, OrderDetailOut)
    assert detail.order_number == "R1-0099"
    assert detail.status == "delivered"
    assert len(detail.items) == 1
    assert detail.items[0].dish_number == 110
    assert detail.items[0].dish_name == "Chicken Biryani"
    assert detail.items[0].line_total == Decimal("22.00")
    assert detail.customer.name == "Sara Al Rashid"
    assert detail.customer.phone == "+971501112233"
    assert detail.address is not None
    assert detail.address.room_apartment == "Apt 404"
    assert detail.address.building == "Marina Tower"


async def test_get_order_detail_no_rider_returns_null(db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert detail.rider is None
    assert detail.route == []


async def test_get_order_detail_timeline_from_audit_log(db_session, restaurant):
    from app.audit.service import record_audit

    order, _, _ = await _seed_full_order(db_session, restaurant.id)
    await record_audit(
        db_session, actor="manager", restaurant_id=restaurant.id,
        entity="order", entity_id=str(order.id),
        action="status_change", after={"status": "confirmed"},
    )
    await db_session.commit()

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert len(detail.timeline) >= 1
    assert detail.timeline[0].action == "status_change"
    assert detail.timeline[0].actor == "manager"


async def test_get_order_detail_chat_from_conversation(db_session, restaurant):
    from app.conversation.models import Conversation, Message

    order, customer, _ = await _seed_full_order(db_session, restaurant.id)

    conv = Conversation(
        restaurant_id=restaurant.id, phone=customer.phone,
        counterpart="customer", state={},
    )
    db_session.add(conv)
    await db_session.flush()

    db_session.add(Message(
        conversation_id=conv.id, direction="inbound",
        type="text", payload={"text": "I want biryani"}, ts=1717660800,
    ))
    db_session.add(Message(
        conversation_id=conv.id, direction="outbound",
        type="text", payload={"text": "Added 1x Chicken Biryani!"}, ts=1717660810,
    ))
    await db_session.commit()

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert len(detail.chat) == 2
    assert detail.chat[0].direction == "inbound"
    assert detail.chat[0].text == "I want biryani"
    assert detail.chat[1].direction == "outbound"


async def test_get_order_detail_no_conversation_returns_empty_chat(db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert detail.chat == []


async def test_get_order_detail_marketing_opted_in_flag(db_session, restaurant):
    from app.marketing.optout import record_opt_out

    order, customer, _ = await _seed_full_order(db_session, restaurant.id)
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone=customer.phone)
    await db_session.commit()

    detail = await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=order.id)

    assert detail.customer.marketing_opted_in is False


async def test_get_order_detail_wrong_tenant_raises(db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    with pytest.raises(ValueError, match="Order not found"):
        await get_order_detail(db_session, restaurant_id=99999, order_id=order.id)


async def test_get_order_detail_unknown_id_raises(db_session, restaurant):
    with pytest.raises(ValueError, match="Order not found"):
        await get_order_detail(db_session, restaurant_id=restaurant.id, order_id=99999)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/ordering/test_order_detail.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'get_order_detail'`

- [ ] **Step 3: Implement `get_order_detail()` — append to `src/app/ordering/service.py`**

First add these imports to the top of `service.py` (after the existing imports):

The file already imports from `app.audit.service`, `app.ordering.models`, etc. Add what's missing:

```python
# Add these to the existing imports block at the top of service.py:
from datetime import timezone
```

Then append this function at the end of `src/app/ordering/service.py`:

```python
async def get_order_detail(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    order_id: int,
) -> "OrderDetailOut":
    """Assemble all data for the Order Detail drawer in one call."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.audit.models import AuditLog
    from app.conversation.models import Conversation, Message
    from app.dispatch.models import Assignment, RiderLocation
    from app.identity.models import Rider
    from app.marketing.optout import is_opted_out
    from app.ordering.detail_schemas import (
        AddressDetailOut,
        ChatMessageOut,
        CustomerDetailOut,
        GpsPingOut,
        OrderDetailOut,
        OrderItemDetailOut,
        RiderDetailOut,
        TimelineEventOut,
    )

    # 1. Order — 404 if wrong tenant
    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.restaurant_id == restaurant_id)
    )
    if not order:
        raise ValueError("Order not found")

    # 2. Items
    items_rows = list(
        (await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    )
    items = [
        OrderItemDetailOut(
            dish_number=i.dish_number,
            dish_name=i.dish_name,
            qty=i.qty,
            price_aed=i.price_aed,
        )
        for i in items_rows
    ]

    # 3. Customer
    customer = await session.get(Customer, order.customer_id)

    # 4. Address
    address: AddressDetailOut | None = None
    if order.address_id:
        addr = await session.get(CustomerAddress, order.address_id)
        if addr:
            address = AddressDetailOut(
                id=addr.id,
                room_apartment=addr.room_apartment,
                building=addr.building,
                receiver_name=addr.receiver_name,
                additional_details=addr.additional_details,
                latitude=addr.latitude,
                longitude=addr.longitude,
            )

    # 5. Rider
    rider: RiderDetailOut | None = None
    if order.rider_id:
        r = await session.get(Rider, order.rider_id)
        if r:
            rider = RiderDetailOut(id=r.id, name=r.name, phone=r.phone)

    # 6. Timeline from audit log
    audit_rows = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.entity == "order", AuditLog.entity_id == str(order.id))
                .order_by(AuditLog.created_at)
            )
        ).all()
    )
    timeline = [
        TimelineEventOut(
            ts=row.created_at,
            action=row.action,
            actor=row.actor,
            after=row.after,
        )
        for row in audit_rows
    ]

    # 7. Chat history
    chat: list[ChatMessageOut] = []
    if customer:
        conv = await session.scalar(
            select(Conversation).where(
                Conversation.restaurant_id == restaurant_id,
                Conversation.phone == customer.phone,
                Conversation.counterpart == "customer",
            )
        )
        if conv:
            msg_rows = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == conv.id)
                        .order_by(Message.ts)
                    )
                ).all()
            )
            chat = [
                ChatMessageOut(
                    direction=m.direction,
                    text=m.payload.get("text") if m.type == "text" else None,
                    ts=m.ts,
                )
                for m in msg_rows
            ]

    # 8. Rider GPS route
    route: list[GpsPingOut] = []
    if order.rider_id:
        assignment = await session.scalar(
            select(Assignment).where(Assignment.order_id == order.id)
        )
        if assignment:
            upper = order.delivered_at or datetime.now(timezone.utc)
            ping_rows = list(
                (
                    await session.scalars(
                        select(RiderLocation)
                        .where(
                            RiderLocation.rider_id == order.rider_id,
                            RiderLocation.ts >= assignment.assigned_at,
                            RiderLocation.ts <= upper,
                        )
                        .order_by(RiderLocation.ts)
                    )
                ).all()
            )
            route = [
                GpsPingOut(latitude=p.latitude, longitude=p.longitude, ts=p.ts)
                for p in ping_rows
            ]

    # 9. Marketing opt-in
    opted_out = (
        await is_opted_out(session, restaurant_id=restaurant_id, phone=customer.phone)
        if customer
        else False
    )

    return OrderDetailOut(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        items=items,
        address=address,
        customer=CustomerDetailOut(
            id=customer.id,
            name=customer.name,
            phone=customer.phone,
            total_orders=customer.total_orders,
            total_spend=customer.total_spend,
            first_order_at=customer.first_order_at,
            last_order_at=customer.last_order_at,
            marketing_opted_in=not opted_out,
        ),
        rider=rider,
        subtotal=order.subtotal,
        delivery_fee_aed=order.delivery_fee_aed,
        total=order.total,
        created_at=order.created_at,
        delivered_at=order.delivered_at,
        sla_deadline=order.sla_deadline,
        timeline=timeline,
        chat=chat,
        route=route,
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/ordering/test_order_detail.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/ordering/service.py tests/ordering/test_order_detail.py
git commit -m "feat: add get_order_detail() service — assembles full order context"
```

---

### Task 3: `record_opt_in`, `patch_customer`, `patch_address` service functions

**Files:**
- Modify: `src/app/marketing/optout.py` — add `record_opt_in` (skip if done in AI opt-out plan)
- Modify: `src/app/ordering/service.py` — append `patch_customer` and `patch_address`
- Test: `tests/ordering/test_customer_patch.py`

- [ ] **Step 1: Check if `record_opt_in` already exists**

```bash
grep -n "record_opt_in" src/app/marketing/optout.py
```

If it prints nothing, add it. If it already prints a line, skip to Step 2.

To add `record_opt_in`, append to `src/app/marketing/optout.py` (also add `delete` to the sqlalchemy import at top):

```python
# Add 'delete' to the existing sqlalchemy import at the top:
from sqlalchemy import delete, select
```

```python
# Append at end of src/app/marketing/optout.py:
async def record_opt_in(
    session: AsyncSession,
    *,
    restaurant_id: int,
    phone: str,
) -> None:
    """Remove opt-out record if present. Idempotent — safe when no row exists."""
    await session.execute(
        delete(OptOut).where(
            OptOut.restaurant_id == restaurant_id,
            OptOut.phone == phone,
        )
    )
```

- [ ] **Step 2: Write failing tests for customer and address patch**

Create `tests/ordering/test_customer_patch.py`:

```python
# tests/ordering/test_customer_patch.py
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ordering.models import Customer, CustomerAddress, Order
from app.ordering.service import patch_customer, patch_address


async def _seed_customer_with_address(db_session, restaurant_id):
    customer = Customer(
        restaurant_id=restaurant_id, phone="+971502223333",
        name="Original Name", total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id, room_apartment="Room 1",
        building="Old Building", receiver_name="Original Name",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()
    return customer, addr


async def test_patch_customer_name(db_session, restaurant):
    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)

    updated = await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, name="New Name", phone=None, marketing_opted_in=None,
    )
    await db_session.commit()

    assert updated.name == "New Name"


async def test_patch_customer_phone(db_session, restaurant):
    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)

    updated = await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, name=None, phone="+971509998888", marketing_opted_in=None,
    )
    await db_session.commit()

    assert updated.phone == "+971509998888"


async def test_patch_customer_opt_out(db_session, restaurant):
    from app.marketing.optout import is_opted_out

    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)

    await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, name=None, phone=None, marketing_opted_in=False,
    )
    await db_session.commit()

    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone=customer.phone)


async def test_patch_customer_opt_in(db_session, restaurant):
    from app.marketing.optout import is_opted_out, record_opt_out

    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone=customer.phone)
    await db_session.commit()

    await patch_customer(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, name=None, phone=None, marketing_opted_in=True,
    )
    await db_session.commit()

    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone=customer.phone)


async def test_patch_customer_wrong_tenant_raises(db_session, restaurant):
    customer, _ = await _seed_customer_with_address(db_session, restaurant.id)

    with pytest.raises(ValueError, match="Customer not found"):
        await patch_customer(
            db_session, restaurant_id=99999,
            customer_id=customer.id, name="X", phone=None, marketing_opted_in=None,
        )


async def test_patch_address_updates_fields(db_session, restaurant):
    customer, addr = await _seed_customer_with_address(db_session, restaurant.id)

    updated = await patch_address(
        db_session, restaurant_id=restaurant.id,
        customer_id=customer.id, address_id=addr.id,
        room_apartment="Suite 10", building="New Tower",
        receiver_name="Updated Name", additional_details="Ring bell",
    )
    await db_session.commit()

    assert updated.room_apartment == "Suite 10"
    assert updated.building == "New Tower"
    assert updated.receiver_name == "Updated Name"
    assert updated.additional_details == "Ring bell"


async def test_patch_address_wrong_customer_raises(db_session, restaurant):
    customer, addr = await _seed_customer_with_address(db_session, restaurant.id)

    with pytest.raises(ValueError, match="Address not found"):
        await patch_address(
            db_session, restaurant_id=restaurant.id,
            customer_id=99999, address_id=addr.id,
            room_apartment=None, building=None, receiver_name=None, additional_details=None,
        )
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/ordering/test_customer_patch.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'patch_customer'`

- [ ] **Step 4: Append `patch_customer` and `patch_address` to `src/app/ordering/service.py`**

```python
async def patch_customer(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
    name: str | None,
    phone: str | None,
    marketing_opted_in: bool | None,
) -> Customer:
    """Update customer name/phone and/or marketing opt preference."""
    from sqlalchemy import select
    from app.marketing.optout import record_opt_in, record_opt_out

    customer = await session.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant_id,
        )
    )
    if not customer:
        raise ValueError("Customer not found")

    if name is not None:
        customer.name = name
    if phone is not None:
        customer.phone = phone
    if marketing_opted_in is True:
        await record_opt_in(session, restaurant_id=restaurant_id, phone=customer.phone)
    elif marketing_opted_in is False:
        await record_opt_out(
            session, restaurant_id=restaurant_id,
            phone=customer.phone, source="manager_dashboard",
        )

    await session.flush()
    return customer


async def patch_address(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
    address_id: int,
    room_apartment: str | None,
    building: str | None,
    receiver_name: str | None,
    additional_details: str | None,
) -> CustomerAddress:
    """Update address fields. Raises ValueError if address not owned by customer."""
    from sqlalchemy import select

    customer = await session.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant_id,
        )
    )
    if not customer:
        raise ValueError("Customer not found")

    addr = await session.scalar(
        select(CustomerAddress).where(
            CustomerAddress.id == address_id,
            CustomerAddress.customer_id == customer_id,
        )
    )
    if not addr:
        raise ValueError("Address not found")

    if room_apartment is not None:
        addr.room_apartment = room_apartment
    if building is not None:
        addr.building = building
    if receiver_name is not None:
        addr.receiver_name = receiver_name
    if additional_details is not None:
        addr.additional_details = additional_details

    await session.flush()
    return addr
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/ordering/test_customer_patch.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/ordering/service.py src/app/marketing/optout.py tests/ordering/test_customer_patch.py
git commit -m "feat: add patch_customer and patch_address service functions"
```

---

### Task 4: API endpoints — detail + patch

**Files:**
- Modify: `src/app/ordering/router.py`
- Test: `tests/ordering/test_order_detail.py` (add API tests)

- [ ] **Step 1: Write failing API tests — append to `tests/ordering/test_order_detail.py`**

```python
# Append to tests/ordering/test_order_detail.py


async def test_api_order_detail_returns_200(client, db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    resp = await client.get(f"/api/v1/orders/{order.id}/detail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_number"] == "R1-0099"
    assert data["status"] == "delivered"
    assert len(data["items"]) == 1
    assert data["items"][0]["dish_name"] == "Chicken Biryani"
    assert "customer" in data
    assert "timeline" in data
    assert "chat" in data
    assert "route" in data


async def test_api_order_detail_wrong_tenant_404(client, db_session, restaurant):
    order, _, _ = await _seed_full_order(db_session, restaurant.id)

    resp = await client.get(f"/api/v1/orders/99999/detail")
    assert resp.status_code == 404


async def test_api_patch_customer_name(client, db_session, restaurant):
    order, customer, _ = await _seed_full_order(db_session, restaurant.id)

    resp = await client.patch(
        f"/api/v1/ordering/customers/{customer.id}",
        json={"name": "Updated Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


async def test_api_patch_address(client, db_session, restaurant):
    order, customer, addr = await _seed_full_order(db_session, restaurant.id)

    resp = await client.patch(
        f"/api/v1/ordering/customers/{customer.id}/addresses/{addr.id}",
        json={"building": "New Tower"},
    )
    assert resp.status_code == 200
    assert resp.json()["building"] == "New Tower"


async def test_api_patch_customer_wrong_tenant_404(client, db_session, restaurant):
    resp = await client.patch(
        "/api/v1/ordering/customers/99999",
        json={"name": "X"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run API tests to verify they fail**

```bash
.venv/bin/pytest tests/ordering/test_order_detail.py -k "api" -v 2>&1 | head -20
```

Expected: 404 on detail endpoint (route not registered yet)

- [ ] **Step 3: Add three endpoints to `src/app/ordering/router.py`**

Add to imports at top of `router.py`:

```python
from app.ordering.detail_schemas import (
    AddressDetailOut,
    AddressPatchIn,
    CustomerDetailOut,
    CustomerPatchIn,
    OrderDetailOut,
)
from app.ordering.service import get_order_detail, patch_address, patch_customer
```

Add a second router for the `/ordering/customers` prefix (add after the `router = APIRouter(...)` line):

```python
customers_router = APIRouter(prefix="/api/v1/ordering/customers", tags=["customers"])
```

Add before the `/{order_id}/advance` route:

```python
@router.get("/{order_id}/detail", response_model=OrderDetailOut)
async def get_order_detail_endpoint(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderDetailOut:
    try:
        return await get_order_detail(session, restaurant_id=restaurant.id, order_id=order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
```

After all existing routes at the bottom, add:

```python
@customers_router.patch("/{customer_id}", response_model=CustomerDetailOut)
async def patch_customer_endpoint(
    customer_id: int,
    body: CustomerPatchIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CustomerDetailOut:
    try:
        customer = await patch_customer(
            session,
            restaurant_id=restaurant.id,
            customer_id=customer_id,
            name=body.name,
            phone=body.phone,
            marketing_opted_in=body.marketing_opted_in,
        )
        await session.commit()
        from app.marketing.optout import is_opted_out
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
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@customers_router.patch("/{customer_id}/addresses/{address_id}", response_model=AddressDetailOut)
async def patch_address_endpoint(
    customer_id: int,
    address_id: int,
    body: AddressPatchIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> AddressDetailOut:
    try:
        addr = await patch_address(
            session,
            restaurant_id=restaurant.id,
            customer_id=customer_id,
            address_id=address_id,
            room_apartment=body.room_apartment,
            building=body.building,
            receiver_name=body.receiver_name,
            additional_details=body.additional_details,
        )
        await session.commit()
        return AddressDetailOut(
            id=addr.id,
            room_apartment=addr.room_apartment,
            building=addr.building,
            receiver_name=addr.receiver_name,
            additional_details=addr.additional_details,
            latitude=addr.latitude,
            longitude=addr.longitude,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
```

- [ ] **Step 4: Mount `customers_router` in `src/app/main.py`**

In `src/app/main.py`, add at the top:

```python
from app.ordering.router import customers_router
```

And in the `create_app()` function after `app.include_router(ordering_router)`:

```python
app.include_router(customers_router)
```

- [ ] **Step 5: Check conftest.py has a `client` fixture**

```bash
grep -n "def client\|async def client" tests/conftest.py | head -5
```

If no `client` fixture exists, add to `tests/conftest.py`:

```python
from httpx import AsyncClient, ASGITransport

@pytest.fixture
async def client(db_session):
    from app.main import create_app
    from app.db import get_session
    from app.identity.deps import current_restaurant

    app = create_app()

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

Actually — check how existing API tests work in this codebase first:

```bash
grep -rn "def client\|AsyncClient\|TestClient" tests/ | head -10
```

Match the existing pattern.

- [ ] **Step 6: Run API tests**

```bash
.venv/bin/pytest tests/ordering/test_order_detail.py -v
```

Expected: all 13 tests PASS

- [ ] **Step 7: Run full suite for regressions**

```bash
.venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add src/app/ordering/router.py src/app/main.py tests/ordering/test_order_detail.py
git commit -m "feat: add GET /orders/{id}/detail and PATCH /ordering/customers endpoints"
```

---

### Task 5: Frontend — types and API client

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/lib/orderDetailApi.ts`

- [ ] **Step 1: Add `OrderDetailOut` types to `frontend/src/lib/types.ts`**

Append to `frontend/src/lib/types.ts`:

```typescript
// ── Order Detail (rich view) ─────────────────────────────────────────────────

export interface OrderItemDetailOut {
  dish_number: number;
  dish_name: string;
  qty: number;
  price_aed: string;
  line_total: string;
}

export interface AddressDetailOut {
  id: number;
  room_apartment: string | null;
  building: string | null;
  receiver_name: string | null;
  additional_details: string | null;
  latitude: number | null;
  longitude: number | null;
}

export interface CustomerDetailOut {
  id: number;
  name: string | null;
  phone: string;
  total_orders: number;
  total_spend: string;
  first_order_at: string | null;
  last_order_at: string | null;
  marketing_opted_in: boolean;
}

export interface RiderDetailOut {
  id: number;
  name: string;
  phone: string;
}

export interface TimelineEventOut {
  ts: string;   // ISO 8601
  action: string;
  actor: string;
  after: Record<string, unknown> | null;
}

export interface ChatMessageOut {
  direction: "inbound" | "outbound";
  text: string | null;
  ts: number;   // unix epoch
}

export interface GpsPingOut {
  latitude: number;
  longitude: number;
  ts: string;   // ISO 8601
}

export interface OrderDetailOut {
  id: number;
  order_number: string;
  status: OrderStatus;
  items: OrderItemDetailOut[];
  address: AddressDetailOut | null;
  customer: CustomerDetailOut;
  rider: RiderDetailOut | null;
  subtotal: string;
  delivery_fee_aed: string;
  total: string;
  created_at: string;
  delivered_at: string | null;
  sla_deadline: string | null;
  timeline: TimelineEventOut[];
  chat: ChatMessageOut[];
  route: GpsPingOut[];
}

export interface CustomerPatchIn {
  name?: string | null;
  phone?: string | null;
  marketing_opted_in?: boolean | null;
}

export interface AddressPatchIn {
  room_apartment?: string | null;
  building?: string | null;
  receiver_name?: string | null;
  additional_details?: string | null;
}
```

- [ ] **Step 2: Create `frontend/src/lib/orderDetailApi.ts`**

```typescript
// frontend/src/lib/orderDetailApi.ts
import { apiClient } from "./apiClient";
import type {
  AddressDetailOut,
  AddressPatchIn,
  CustomerDetailOut,
  CustomerPatchIn,
  OrderDetailOut,
} from "./types";

export async function fetchOrderDetail(orderId: number): Promise<OrderDetailOut> {
  return apiClient.get<OrderDetailOut>(`/api/v1/orders/${orderId}/detail`);
}

export async function patchCustomer(
  customerId: number,
  body: CustomerPatchIn,
): Promise<CustomerDetailOut> {
  return apiClient.patch<CustomerDetailOut>(
    `/api/v1/ordering/customers/${customerId}`,
    body,
  );
}

export async function patchAddress(
  customerId: number,
  addressId: number,
  body: AddressPatchIn,
): Promise<AddressDetailOut> {
  return apiClient.patch<AddressDetailOut>(
    `/api/v1/ordering/customers/${customerId}/addresses/${addressId}`,
    body,
  );
}
```

- [ ] **Step 3: Check `apiClient` has a `patch` method**

```bash
grep -n "patch\|PATCH" frontend/src/lib/apiClient.ts | head -10
```

If no `patch` method exists, add it to `apiClient.ts`:

```typescript
patch<T>(path: string, body?: unknown): Promise<T> {
  return this.request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined });
}
```

- [ ] **Step 4: Run frontend type-check**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npm run typecheck 2>&1 | tail -10
```

Expected: no errors (or same count as before)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/orderDetailApi.ts frontend/src/lib/apiClient.ts
git commit -m "feat: add OrderDetailOut types and orderDetailApi client"
```

---

### Task 6: Frontend — OrderDetailDrawer with tabs

**Files:**
- Modify: `frontend/src/screens/OrderDetailDrawer.tsx`
- Modify: `frontend/src/screens/OrderDetailDrawer.module.css`

- [ ] **Step 1: Rewrite `frontend/src/screens/OrderDetailDrawer.tsx`**

```tsx
// frontend/src/screens/OrderDetailDrawer.tsx
import { useEffect, useRef, useState } from "react";
import { SideDrawer } from "../components/SideDrawer";
import { Spinner } from "../components/Spinner";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/Button";
import { CountdownTimer } from "../components/CountdownTimer";
import { apiClient } from "../lib/apiClient";
import { fetchOrderDetail, patchAddress, patchCustomer } from "../lib/orderDetailApi";
import { fetchOrder } from "../lib/ordersApi";
import type {
  AddressDetailOut,
  CustomerDetailOut,
  OrderDetailOut,
  OrderOut,
} from "../lib/types";
import s from "./OrderDetailDrawer.module.css";

type Tab = "overview" | "timeline" | "chat" | "customer";

const KITCHEN_ADVANCEABLE = new Set(["confirmed", "preparing"]);
const ADVANCE_LABEL: Record<string, string> = {
  confirmed: "Start Preparing",
  preparing: "Mark as Ready",
};

export function OrderDetailDrawer({
  orderId,
  onClose,
}: {
  orderId: number | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<OrderDetailOut | null>(null);
  const [basicOrder, setBasicOrder] = useState<OrderOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");
  const [advancing, setAdvancing] = useState(false);

  useEffect(() => {
    if (orderId === null) {
      setDetail(null);
      setBasicOrder(null);
      return;
    }
    setLoading(true);
    setTab("overview");
    Promise.all([
      fetchOrderDetail(orderId),
      fetchOrder(orderId),
    ])
      .then(([d, b]) => {
        setDetail(d);
        setBasicOrder(b);
      })
      .finally(() => setLoading(false));
  }, [orderId]);

  async function advanceStatus() {
    if (!basicOrder) return;
    setAdvancing(true);
    try {
      const updated = await apiClient.post<OrderOut>(`/api/v1/orders/${basicOrder.id}/advance`);
      setBasicOrder(updated);
      // Refresh detail to update timeline
      const d = await fetchOrderDetail(basicOrder.id);
      setDetail(d);
    } finally {
      setAdvancing(false);
    }
  }

  function onCustomerSaved(updated: CustomerDetailOut) {
    if (!detail) return;
    setDetail({ ...detail, customer: updated });
  }

  function onAddressSaved(updated: AddressDetailOut) {
    if (!detail) return;
    setDetail({ ...detail, address: updated });
  }

  const title = basicOrder
    ? `Order ${basicOrder.order_number ?? `#${basicOrder.id}`}`
    : "Order";

  return (
    <SideDrawer open={orderId !== null} title={title} onClose={onClose}>
      {loading || !detail || !basicOrder ? (
        <Spinner />
      ) : (
        <div className={s.detail}>
          <div className={s.head}>
            <StatusPill status={detail.status} />
            <CountdownTimer slaStartedAt={basicOrder.sla_started_at} />
          </div>

          {KITCHEN_ADVANCEABLE.has(detail.status) && (
            <div className={s.actionBar}>
              <Button onClick={advanceStatus} disabled={advancing}>
                {advancing ? "Saving…" : ADVANCE_LABEL[detail.status]}
              </Button>
            </div>
          )}

          <div className={s.tabs} role="tablist">
            {(["overview", "timeline", "chat", "customer"] as Tab[]).map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={tab === t}
                className={`${s.tab} ${tab === t ? s.activeTab : ""}`}
                onClick={() => setTab(t)}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>

          <div className={s.tabContent}>
            {tab === "overview" && <OverviewTab detail={detail} />}
            {tab === "timeline" && <TimelineTab detail={detail} />}
            {tab === "chat" && <ChatTab detail={detail} />}
            {tab === "customer" && (
              <CustomerTab
                detail={detail}
                onCustomerSaved={onCustomerSaved}
                onAddressSaved={onAddressSaved}
              />
            )}
          </div>
        </div>
      )}
    </SideDrawer>
  );
}

// ── Overview Tab ─────────────────────────────────────────────────────────────

function OverviewTab({ detail }: { detail: OrderDetailOut }) {
  return (
    <div className={s.overview}>
      <section className={s.section}>
        <h4 className={s.sectionTitle}>Items</h4>
        {detail.items.map((item, i) => (
          <div key={i} className={s.itemRow}>
            <span className={s.itemNum}>{item.dish_number}.</span>
            <span className={s.itemName}>{item.dish_name}</span>
            <span className={s.itemQty}>×{item.qty}</span>
            <span className={s.itemPrice}>AED {item.line_total}</span>
          </div>
        ))}
        <div className={s.totals}>
          <div className={s.totalRow}>
            <span>Subtotal</span><span>AED {detail.subtotal}</span>
          </div>
          <div className={s.totalRow}>
            <span>Delivery</span><span>AED {detail.delivery_fee_aed}</span>
          </div>
          <div className={`${s.totalRow} ${s.grandTotal}`}>
            <span>Total</span><span>AED {detail.total}</span>
          </div>
          <div className={s.totalRow}>
            <span>Payment</span><span>COD</span>
          </div>
        </div>
      </section>

      <section className={s.section}>
        <h4 className={s.sectionTitle}>Delivery</h4>
        {detail.address ? (
          <>
            <Field label="Receiver" value={detail.address.receiver_name ?? "—"} />
            <Field
              label="Address"
              value={[detail.address.room_apartment, detail.address.building]
                .filter(Boolean)
                .join(", ") || "—"}
            />
            {detail.address.additional_details && (
              <Field label="Notes" value={detail.address.additional_details} />
            )}
          </>
        ) : (
          <p className={s.empty}>No address</p>
        )}
        <Field
          label="Rider"
          value={detail.rider ? `${detail.rider.name} · ${detail.rider.phone}` : "Unassigned"}
        />
      </section>
    </div>
  );
}

// ── Timeline Tab ──────────────────────────────────────────────────────────────

function TimelineTab({ detail }: { detail: OrderDetailOut }) {
  const mapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mapRef.current || detail.route.length === 0) return;

    import("leaflet").then((L) => {
      // Clean up any existing map instance
      (mapRef.current as HTMLDivElement & { _leaflet_id?: number })._leaflet_id = undefined;
      const container = mapRef.current!;
      container.innerHTML = "";

      const map = L.map(container, { zoomControl: true });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
      }).addTo(map);

      const coords: [number, number][] = detail.route.map((p) => [p.latitude, p.longitude]);
      const polyline = L.polyline(coords, { color: "#0ea5e9", weight: 3 }).addTo(map);
      map.fitBounds(polyline.getBounds(), { padding: [20, 20] });

      // Start marker (restaurant / pickup)
      L.circleMarker(coords[0], { radius: 7, color: "#f59e0b", fillColor: "#f59e0b", fillOpacity: 1 })
        .bindTooltip("Pickup")
        .addTo(map);

      // End marker (delivery)
      const last = coords[coords.length - 1];
      L.circleMarker(last, { radius: 7, color: "#22c55e", fillColor: "#22c55e", fillOpacity: 1 })
        .bindTooltip("Delivered")
        .addTo(map);
    });

    return () => {
      if (mapRef.current) mapRef.current.innerHTML = "";
    };
  }, [detail.route]);

  return (
    <div className={s.timeline}>
      {detail.timeline.length === 0 ? (
        <p className={s.empty}>No timeline events</p>
      ) : (
        <ol className={s.timelineList}>
          {detail.timeline.map((event, i) => (
            <li key={i} className={s.timelineEvent}>
              <span className={s.timelineDot} />
              <div className={s.timelineBody}>
                <span className={s.timelineAction}>{event.action.replace(/_/g, " ")}</span>
                <span className={s.timelineMeta}>
                  {new Date(event.ts).toLocaleTimeString()} · {event.actor}
                </span>
              </div>
            </li>
          ))}
        </ol>
      )}

      {detail.route.length > 0 ? (
        <div className={s.mapWrapper}>
          <h4 className={s.sectionTitle}>Delivery Route</h4>
          <div ref={mapRef} className={s.map} />
        </div>
      ) : (
        detail.rider && <p className={s.empty}>No GPS pings recorded for this order</p>
      )}
    </div>
  );
}

// ── Chat Tab ──────────────────────────────────────────────────────────────────

function ChatTab({ detail }: { detail: OrderDetailOut }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "instant" });
  }, [detail.chat]);

  if (detail.chat.length === 0) {
    return <p className={s.empty}>No WhatsApp conversation found for this order</p>;
  }

  return (
    <div className={s.chatContainer}>
      {detail.chat.map((msg, i) => (
        <div
          key={i}
          className={`${s.bubble} ${msg.direction === "inbound" ? s.inbound : s.outbound}`}
        >
          <span className={s.bubbleText}>
            {msg.text ?? (msg.direction === "inbound" ? "[📍 location / media]" : "[📤 automated]")}
          </span>
          <span className={s.bubbleTime}>
            {new Date(msg.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

// ── Customer Tab ──────────────────────────────────────────────────────────────

function CustomerTab({
  detail,
  onCustomerSaved,
  onAddressSaved,
}: {
  detail: OrderDetailOut;
  onCustomerSaved: (c: CustomerDetailOut) => void;
  onAddressSaved: (a: AddressDetailOut) => void;
}) {
  const { customer, address } = detail;
  const [name, setName] = useState(customer.name ?? "");
  const [phone, setPhone] = useState(customer.phone);
  const [optIn, setOptIn] = useState(customer.marketing_opted_in);
  const [aptRoom, setAptRoom] = useState(address?.room_apartment ?? "");
  const [building, setBuilding] = useState(address?.building ?? "");
  const [receiverName, setReceiverName] = useState(address?.receiver_name ?? "");
  const [addrNotes, setAddrNotes] = useState(address?.additional_details ?? "");
  const [saving, setSaving] = useState(false);

  const dirty =
    name !== (customer.name ?? "") ||
    phone !== customer.phone ||
    optIn !== customer.marketing_opted_in ||
    aptRoom !== (address?.room_apartment ?? "") ||
    building !== (address?.building ?? "") ||
    receiverName !== (address?.receiver_name ?? "") ||
    addrNotes !== (address?.additional_details ?? "");

  async function save() {
    setSaving(true);
    try {
      const [updatedCustomer, updatedAddress] = await Promise.all([
        patchCustomer(customer.id, {
          name: name || null,
          phone: phone || null,
          marketing_opted_in: optIn,
        }),
        address
          ? patchAddress(customer.id, address.id, {
              room_apartment: aptRoom || null,
              building: building || null,
              receiver_name: receiverName || null,
              additional_details: addrNotes || null,
            })
          : Promise.resolve(null),
      ]);
      onCustomerSaved(updatedCustomer);
      if (updatedAddress) onAddressSaved(updatedAddress);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={s.customerTab}>
      <div className={s.customerStats}>
        <Stat label="Orders" value={String(customer.total_orders)} />
        <Stat label="Spend" value={`AED ${customer.total_spend}`} />
        <Stat
          label="First Order"
          value={customer.first_order_at ? new Date(customer.first_order_at).toLocaleDateString() : "—"}
        />
      </div>

      <section className={s.section}>
        <h4 className={s.sectionTitle}>Identity</h4>
        <label className={s.fieldLabel}>Name</label>
        <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} />
        <label className={s.fieldLabel}>Phone</label>
        <input className={s.input} value={phone} onChange={(e) => setPhone(e.target.value)} />
        <div className={s.toggleRow}>
          <label className={s.fieldLabel}>Marketing (WhatsApp)</label>
          <button
            className={`${s.toggle} ${optIn ? s.toggleOn : s.toggleOff}`}
            onClick={() => setOptIn(!optIn)}
            aria-label={optIn ? "Opt out" : "Opt in"}
          >
            {optIn ? "OPT-IN" : "OPT-OUT"}
          </button>
        </div>
      </section>

      {address && (
        <section className={s.section}>
          <h4 className={s.sectionTitle}>Address</h4>
          <label className={s.fieldLabel}>Apt / Room</label>
          <input className={s.input} value={aptRoom} onChange={(e) => setAptRoom(e.target.value)} />
          <label className={s.fieldLabel}>Building</label>
          <input className={s.input} value={building} onChange={(e) => setBuilding(e.target.value)} />
          <label className={s.fieldLabel}>Receiver Name</label>
          <input className={s.input} value={receiverName} onChange={(e) => setReceiverName(e.target.value)} />
          <label className={s.fieldLabel}>Notes</label>
          <input className={s.input} value={addrNotes} onChange={(e) => setAddrNotes(e.target.value)} />
        </section>
      )}

      <div className={s.saveRow}>
        <Button onClick={save} disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save Changes"}
        </Button>
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.field}>
      <span className={s.fieldLabel}>{label}</span>
      <span className={s.val}>{value}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.stat}>
      <span className={s.statValue}>{value}</span>
      <span className={s.statLabel}>{label}</span>
    </div>
  );
}
```

- [ ] **Step 2: Install Leaflet**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npm install leaflet @types/leaflet
```

- [ ] **Step 3: Add Leaflet CSS import to main entry**

Check `frontend/src/main.tsx` or `frontend/src/index.tsx`:

```bash
grep -n "import.*css\|leaflet" frontend/src/main.tsx frontend/src/index.tsx 2>/dev/null | head -10
```

Add after existing CSS imports in `main.tsx`:

```typescript
import "leaflet/dist/leaflet.css";
```

- [ ] **Step 4: Update `OrderDetailDrawer.module.css`**

Replace entire content of `frontend/src/screens/OrderDetailDrawer.module.css`:

```css
/* OrderDetailDrawer.module.css */
.detail { display: flex; flex-direction: column; height: 100%; }

.head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 0 12px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 12px;
}

.actionBar { margin-bottom: 12px; }

/* ── Tabs ── */
.tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 16px;
}
.tab {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 6px 12px;
  text-transform: uppercase;
  transition: color 0.15s, border-color 0.15s;
}
.tab:hover { color: var(--text-primary); }
.activeTab {
  border-bottom-color: var(--accent);
  color: var(--accent);
}

.tabContent { flex: 1; overflow-y: auto; }

/* ── Shared ── */
.section { margin-bottom: 20px; }
.sectionTitle {
  color: var(--accent);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
  text-transform: uppercase;
}
.field { display: flex; flex-direction: column; margin-bottom: 8px; }
.fieldLabel {
  color: var(--text-secondary);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  margin-bottom: 2px;
  text-transform: uppercase;
}
.val { color: var(--text-primary); font-size: 0.88rem; }
.empty { color: var(--text-secondary); font-size: 0.85rem; font-style: italic; }

/* ── Overview ── */
.overview {}
.itemRow {
  align-items: baseline;
  display: grid;
  font-size: 0.85rem;
  gap: 6px;
  grid-template-columns: 28px 1fr 32px 80px;
  margin-bottom: 4px;
}
.itemNum { color: var(--text-secondary); }
.itemName { color: var(--text-primary); }
.itemQty { color: var(--text-secondary); text-align: center; }
.itemPrice { color: var(--text-primary); font-variant-numeric: tabular-nums; text-align: right; }

.totals { border-top: 1px solid var(--border); margin-top: 8px; padding-top: 8px; }
.totalRow {
  display: flex;
  font-size: 0.82rem;
  justify-content: space-between;
  padding: 2px 0;
  color: var(--text-secondary);
}
.grandTotal { color: var(--text-primary); font-size: 0.9rem; font-weight: 700; margin-top: 4px; }

/* ── Timeline ── */
.timeline {}
.timelineList { list-style: none; padding: 0; }
.timelineEvent {
  align-items: flex-start;
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  padding-left: 4px;
  position: relative;
}
.timelineDot {
  background: var(--accent);
  border-radius: 50%;
  flex-shrink: 0;
  height: 8px;
  margin-top: 4px;
  width: 8px;
}
.timelineBody { display: flex; flex-direction: column; }
.timelineAction { color: var(--text-primary); font-size: 0.85rem; font-weight: 500; text-transform: capitalize; }
.timelineMeta { color: var(--text-secondary); font-size: 0.75rem; }

.mapWrapper { margin-top: 16px; }
.map { border-radius: 6px; height: 220px; width: 100%; }

/* ── Chat ── */
.chatContainer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-bottom: 8px;
}
.bubble {
  display: flex;
  flex-direction: column;
  max-width: 78%;
  padding: 6px 10px;
  border-radius: 10px;
  font-size: 0.85rem;
}
.inbound {
  align-self: flex-start;
  background: var(--bg-tertiary);
  border-bottom-left-radius: 2px;
}
.outbound {
  align-self: flex-end;
  background: var(--accent);
  border-bottom-right-radius: 2px;
}
.bubbleText { color: var(--text-primary); word-break: break-word; }
.outbound .bubbleText { color: #fff; }
.bubbleTime {
  color: var(--text-secondary);
  font-size: 0.68rem;
  margin-top: 2px;
  text-align: right;
}
.outbound .bubbleTime { color: rgba(255,255,255,0.7); }

/* ── Customer ── */
.customerTab {}
.customerStats {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  padding: 10px 12px;
  background: var(--bg-tertiary);
  border-radius: 6px;
}
.stat { display: flex; flex-direction: column; align-items: center; }
.statValue { color: var(--text-primary); font-size: 1rem; font-weight: 700; }
.statLabel { color: var(--text-secondary); font-size: 0.7rem; text-transform: uppercase; }

.input {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 0.85rem;
  margin-bottom: 10px;
  padding: 6px 8px;
  width: 100%;
}
.input:focus { border-color: var(--accent); outline: none; }

.toggleRow { align-items: center; display: flex; gap: 10px; margin-bottom: 10px; }
.toggle {
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 4px 10px;
}
.toggleOn { background: #22c55e; color: #000; }
.toggleOff { background: var(--bg-tertiary); color: var(--text-secondary); }

.saveRow { margin-top: 12px; }
```

- [ ] **Step 5: Run frontend tests**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npm test -- --run 2>&1 | tail -20
```

Expected: all existing tests pass (new component not yet tested)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/screens/OrderDetailDrawer.tsx frontend/src/screens/OrderDetailDrawer.module.css frontend/src/main.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat: upgrade OrderDetailDrawer with Overview/Timeline/Chat/Customer tabs and Leaflet route map"
```

---

### Task 7: Frontend tests for OrderDetailDrawer

**Files:**
- Create: `frontend/src/screens/OrderDetailDrawer.test.tsx`

- [ ] **Step 1: Create `frontend/src/screens/OrderDetailDrawer.test.tsx`**

```tsx
// frontend/src/screens/OrderDetailDrawer.test.tsx
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { OrderDetailDrawer } from "./OrderDetailDrawer";
import type { OrderDetailOut, OrderOut } from "../lib/types";

const mockDetail: OrderDetailOut = {
  id: 1,
  order_number: "R1-0001",
  status: "delivered",
  items: [
    { dish_number: 110, dish_name: "Chicken Biryani", qty: 2, price_aed: "22.00", line_total: "44.00" },
  ],
  address: {
    id: 1,
    room_apartment: "Apt 404",
    building: "Marina Tower",
    receiver_name: "Sara Al Rashid",
    additional_details: null,
    latitude: 25.2,
    longitude: 55.2,
  },
  customer: {
    id: 1,
    name: "Sara Al Rashid",
    phone: "+971509876543",
    total_orders: 5,
    total_spend: "220.00",
    first_order_at: "2026-01-01T10:00:00Z",
    last_order_at: "2026-06-10T10:00:00Z",
    marketing_opted_in: true,
  },
  rider: { id: 1, name: "Ahmed Hassan", phone: "+971501111111" },
  subtotal: "44.00",
  delivery_fee_aed: "0.00",
  total: "44.00",
  created_at: "2026-06-10T09:00:00Z",
  delivered_at: "2026-06-10T09:38:00Z",
  sla_deadline: null,
  timeline: [
    { ts: "2026-06-10T09:10:00Z", action: "status_change", actor: "manager", after: { status: "confirmed" } },
  ],
  chat: [
    { direction: "inbound", text: "I want 2 biryani", ts: 1717660800 },
    { direction: "outbound", text: "Added 2× Chicken Biryani!", ts: 1717660810 },
  ],
  route: [],
};

const mockBasicOrder: OrderOut = {
  id: 1,
  order_number: "R1-0001",
  status: "delivered",
  customer_name: "Sara Al Rashid",
  customer_phone: "+971509876543",
  items: [{ dish_number: 110, name: "Chicken Biryani", qty: 2, price_aed: "22.00" }],
  total_aed: "44.00",
  rider_id: 1,
  rider_name: "Ahmed Hassan",
  sla_started_at: null,
  created_at: "2026-06-10T09:00:00Z",
  address: "Apt 404, Marina Tower",
  lat: 25.2,
  lng: 55.2,
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(mockDetail), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(mockBasicOrder), { status: 200 })),
  );
});

it("renders overview tab with items when open", async () => {
  render(<OrderDetailDrawer orderId={1} onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText(/Chicken Biryani/)).toBeTruthy());
  expect(screen.getByText(/AED 44.00/)).toBeTruthy();
});

it("switches to timeline tab", async () => {
  render(<OrderDetailDrawer orderId={1} onClose={() => {}} />);
  await waitFor(() => screen.getByRole("tab", { name: /timeline/i }));
  fireEvent.click(screen.getByRole("tab", { name: /timeline/i }));
  expect(screen.getByText(/status.change/i)).toBeTruthy();
});

it("switches to chat tab and shows messages", async () => {
  render(<OrderDetailDrawer orderId={1} onClose={() => {}} />);
  await waitFor(() => screen.getByRole("tab", { name: /chat/i }));
  fireEvent.click(screen.getByRole("tab", { name: /chat/i }));
  expect(screen.getByText("I want 2 biryani")).toBeTruthy();
  expect(screen.getByText("Added 2× Chicken Biryani!")).toBeTruthy();
});

it("switches to customer tab and shows opt-in toggle", async () => {
  render(<OrderDetailDrawer orderId={1} onClose={() => {}} />);
  await waitFor(() => screen.getByRole("tab", { name: /customer/i }));
  fireEvent.click(screen.getByRole("tab", { name: /customer/i }));
  expect(screen.getByText("Sara Al Rashid")).toBeTruthy();
  expect(screen.getByText(/OPT-IN/i)).toBeTruthy();
});

it("save button disabled when no changes", async () => {
  render(<OrderDetailDrawer orderId={1} onClose={() => {}} />);
  await waitFor(() => screen.getByRole("tab", { name: /customer/i }));
  fireEvent.click(screen.getByRole("tab", { name: /customer/i }));
  const saveBtn = screen.getByRole("button", { name: /save changes/i });
  expect(saveBtn).toBeDisabled();
});

it("renders nothing when orderId is null", () => {
  render(<OrderDetailDrawer orderId={null} onClose={() => {}} />);
  expect(screen.queryByText("Overview")).toBeNull();
});
```

- [ ] **Step 2: Run frontend tests**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npm test -- --run 2>&1 | tail -20
```

Expected: all tests pass including 6 new OrderDetailDrawer tests

- [ ] **Step 3: Commit**

```bash
git add frontend/src/screens/OrderDetailDrawer.test.tsx
git commit -m "test: add OrderDetailDrawer tab switching and render tests"
```

---

### Task 8: Widen the SideDrawer for order detail

The existing `SideDrawer` may be narrow. The Order Detail design calls for 60% viewport width.

**Files:**
- Modify: `frontend/src/components/SideDrawer.module.css`
- Modify: `frontend/src/components/SideDrawer.tsx` (add `wide` prop if needed)

- [ ] **Step 1: Check current SideDrawer width**

```bash
grep -n "width\|max-width" frontend/src/components/SideDrawer.module.css
```

- [ ] **Step 2: Add a `wide` prop to `SideDrawer.tsx`**

Read `frontend/src/components/SideDrawer.tsx`, then add a `wide?: boolean` prop. Pass `wide={true}` from `OrderDetailDrawer`.

In `SideDrawer.tsx`, find the drawer panel div and conditionally add a `wide` class:

```tsx
// In SideDrawer.tsx — add wide prop
export function SideDrawer({
  open,
  title,
  onClose,
  children,
  wide,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  // ... existing code ...
  // In the panel div, add: className={`${s.panel} ${wide ? s.wide : ""}`}
}
```

In `SideDrawer.module.css`, add:

```css
.wide { width: min(60vw, 860px); }
```

In `OrderDetailDrawer.tsx`, pass `wide` to `SideDrawer`:

```tsx
<SideDrawer open={orderId !== null} title={title} onClose={onClose} wide>
```

- [ ] **Step 3: Verify frontend renders correctly**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/uvicorn app.main:app --reload --port 8000 &
cd frontend && npm run dev &
```

Open http://localhost:5173, log in, go to Orders, click an order, verify the wide tabbed drawer opens.

- [ ] **Step 4: Add "Open Full Profile →" link in CustomerTab**

In `OrderDetailDrawer.tsx`, import `Link` from react-router-dom and add a link in the `CustomerTab` component after the stats section:

```tsx
import { Link } from "react-router-dom";

// Inside CustomerTab, after customerStats div:
<div className={s.profileLink}>
  <Link to={`/customers/${customer.id}`} className={s.openProfile}>
    Open Full Profile →
  </Link>
</div>
```

Add to `OrderDetailDrawer.module.css`:

```css
.profileLink { margin-bottom: 16px; text-align: right; }
.openProfile { color: var(--accent); font-size: 0.8rem; text-decoration: none; }
.openProfile:hover { text-decoration: underline; }
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SideDrawer.tsx frontend/src/components/SideDrawer.module.css frontend/src/screens/OrderDetailDrawer.tsx frontend/src/screens/OrderDetailDrawer.module.css
git commit -m "feat: widen SideDrawer, add Open Full Profile link in customer tab"
```
