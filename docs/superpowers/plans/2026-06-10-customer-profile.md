# Customer Profile Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dedicated `/customers/:id` screen with full customer details, order history, all addresses (editable/deletable), tags, and marketing opt-in toggle — accessible from the Customers nav item.

**Architecture:** New `customer_router.py` under the ordering module provides list, profile, and management endpoints. Frontend adds a `CustomerProfileScreen` at `/customers/:id` route and a Customers entry in the nav sidebar.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy 2, Pydantic v2. React 18 + TypeScript, Vitest, CSS Modules. Reuses `patch_customer`, `patch_address`, `record_opt_in`, `record_opt_out` from the Order Detail plan (implement that plan first).

**Prerequisite:** Order Detail plan must be complete (provides `patch_customer`, `patch_address`, `CustomerDetailOut`, `AddressDetailOut`, `CustomerPatchIn`, `AddressPatchIn`).

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/app/ordering/customer_router.py` | Customer CRUD endpoints |
| Modify | `src/app/main.py` | mount `customer_router` |
| Create | `tests/ordering/test_customer_profile.py` | API tests |
| Modify | `frontend/src/lib/types.ts` | add `CustomerProfileOut`, `OrderSummaryOut` |
| Create | `frontend/src/lib/customerApi.ts` | API client functions |
| Create | `frontend/src/screens/CustomerProfileScreen.tsx` | profile screen |
| Create | `frontend/src/screens/CustomerProfileScreen.module.css` | styles |
| Create | `frontend/src/screens/CustomerProfileScreen.test.tsx` | tests |
| Modify | `frontend/src/components/NavSidebar.tsx` | add Customers nav item |
| Modify | `frontend/src/App.tsx` | add `/customers/:id` route |

---

### Task 1: Backend — customer profile schemas and service queries

**Files:**
- Modify: `src/app/ordering/detail_schemas.py` (append `CustomerProfileOut`, `OrderSummaryOut`)

- [ ] **Step 1: Append new schemas to `src/app/ordering/detail_schemas.py`**

```python
# Append to src/app/ordering/detail_schemas.py

class OrderSummaryOut(BaseModel):
    id: int
    order_number: str
    status: str
    total: Decimal
    created_at: datetime


class CustomerProfileOut(BaseModel):
    id: int
    name: str | None
    phone: str
    total_orders: int
    total_spend: Decimal
    first_order_at: datetime | None
    last_order_at: datetime | None
    marketing_opted_in: bool
    tags: dict
    addresses: list[AddressDetailOut]
    recent_orders: list[OrderSummaryOut]
```

- [ ] **Step 2: Verify import works**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/python -c "from app.ordering.detail_schemas import CustomerProfileOut; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/app/ordering/detail_schemas.py
git commit -m "feat: add CustomerProfileOut and OrderSummaryOut schemas"
```

---

### Task 2: Backend — customer router

**Files:**
- Create: `src/app/ordering/customer_router.py`
- Modify: `src/app/main.py`
- Test: `tests/ordering/test_customer_profile.py`

- [ ] **Step 1: Write failing tests**

Create `tests/ordering/test_customer_profile.py`:

```python
# tests/ordering/test_customer_profile.py
from decimal import Decimal

import pytest

from app.ordering.models import Customer, CustomerAddress, Order, OrderItem


async def _seed_customer(db_session, restaurant_id):
    customer = Customer(
        restaurant_id=restaurant_id, phone="+971503334444",
        name="Khalid Hassan", total_orders=3, total_spend=Decimal("99.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    addr = CustomerAddress(
        customer_id=customer.id, room_apartment="Villa 5",
        building="Palm Residences", receiver_name="Khalid Hassan",
        confirmed=True,
    )
    db_session.add(addr)
    await db_session.commit()
    return customer, addr


async def test_list_customers_returns_tenant_only(client, db_session, restaurant):
    await _seed_customer(db_session, restaurant.id)

    resp = await client.get("/api/v1/ordering/customers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    assert all(c["phone"] for c in data["items"])


async def test_list_customers_search_by_phone(client, db_session, restaurant):
    await _seed_customer(db_session, restaurant.id)

    resp = await client.get("/api/v1/ordering/customers?q=503334444")
    assert resp.status_code == 200
    data = resp.json()
    assert any("Khalid" in (c.get("name") or "") for c in data["items"])


async def test_get_customer_profile(client, db_session, restaurant):
    customer, addr = await _seed_customer(db_session, restaurant.id)

    resp = await client.get(f"/api/v1/ordering/customers/{customer.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Khalid Hassan"
    assert data["phone"] == "+971503334444"
    assert len(data["addresses"]) == 1
    assert data["addresses"][0]["building"] == "Palm Residences"
    assert "recent_orders" in data
    assert "marketing_opted_in" in data


async def test_get_customer_profile_wrong_tenant_404(client, db_session, restaurant):
    resp = await client.get("/api/v1/ordering/customers/99999")
    assert resp.status_code == 404


async def test_delete_address_removes_record(client, db_session, restaurant):
    customer, addr = await _seed_customer(db_session, restaurant.id)

    resp = await client.delete(
        f"/api/v1/ordering/customers/{customer.id}/addresses/{addr.id}"
    )
    assert resp.status_code == 204

    # Address no longer returned in profile
    profile_resp = await client.get(f"/api/v1/ordering/customers/{customer.id}")
    assert len(profile_resp.json()["addresses"]) == 0


async def test_delete_address_linked_to_open_order_returns_409(client, db_session, restaurant):
    from app.menu.models import Dish, Menu

    customer, addr = await _seed_customer(db_session, restaurant.id)

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()

    dish = Dish(menu_id=menu.id, restaurant_id=restaurant.id, dish_number=110,
                name="Biryani", price_aed=Decimal("22.00"), category="Rice", is_available=True)
    db_session.add(dish)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-OPEN", status="confirmed",
        address_id=addr.id, subtotal=Decimal("22.00"),
        delivery_fee_aed=Decimal("0.00"), total=Decimal("22.00"),
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/ordering/customers/{customer.id}/addresses/{addr.id}"
    )
    assert resp.status_code == 409
```

- [ ] **Step 2: Run to verify tests fail**

```bash
.venv/bin/pytest tests/ordering/test_customer_profile.py -v 2>&1 | head -15
```

Expected: 404s (routes not registered)

- [ ] **Step 3: Create `src/app/ordering/customer_router.py`**

```python
# src/app/ordering/customer_router.py
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.marketing.optout import is_opted_out
from app.ordering.detail_schemas import (
    AddressDetailOut,
    AddressPatchIn,
    CustomerDetailOut,
    CustomerPatchIn,
    CustomerProfileOut,
    OrderSummaryOut,
)
from app.ordering.models import Customer, CustomerAddress, Order
from app.ordering.service import patch_address, patch_customer

router = APIRouter(prefix="/api/v1/ordering/customers", tags=["customers"])

_OPEN_STATUSES = frozenset(
    {"draft", "pending_confirmation", "confirmed", "preparing", "ready", "assigned", "picked_up", "arriving"}
)


@router.get("", response_model=dict)
async def list_customers(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(Customer).where(Customer.restaurant_id == restaurant.id)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                Customer.phone.ilike(pattern),
                Customer.name.ilike(pattern),
            )
        )
    total_stmt = stmt.with_only_columns(Customer.id)  # for count
    rows = list(
        (await session.scalars(stmt.order_by(Customer.id.desc()).limit(limit).offset(offset))).all()
    )
    items = [
        CustomerDetailOut(
            id=c.id,
            name=c.name,
            phone=c.phone,
            total_orders=c.total_orders,
            total_spend=c.total_spend,
            first_order_at=c.first_order_at,
            last_order_at=c.last_order_at,
            marketing_opted_in=not await is_opted_out(
                session, restaurant_id=restaurant.id, phone=c.phone
            ),
        )
        for c in rows
    ]
    return {"items": [i.model_dump() for i in items], "limit": limit, "offset": offset}


@router.get("/{customer_id}", response_model=CustomerProfileOut)
async def get_customer_profile(
    customer_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CustomerProfileOut:
    customer = await session.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant.id,
        )
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    addresses = list(
        (
            await session.scalars(
                select(CustomerAddress)
                .where(CustomerAddress.customer_id == customer.id)
                .order_by(CustomerAddress.last_used_at.desc().nullslast())
            )
        ).all()
    )

    recent_orders = list(
        (
            await session.scalars(
                select(Order)
                .where(Order.customer_id == customer.id, Order.restaurant_id == restaurant.id)
                .order_by(Order.created_at.desc())
                .limit(10)
            )
        ).all()
    )

    opted_out = await is_opted_out(session, restaurant_id=restaurant.id, phone=customer.phone)

    return CustomerProfileOut(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        total_orders=customer.total_orders,
        total_spend=customer.total_spend,
        first_order_at=customer.first_order_at,
        last_order_at=customer.last_order_at,
        marketing_opted_in=not opted_out,
        tags=customer.tags or {},
        addresses=[
            AddressDetailOut(
                id=a.id,
                room_apartment=a.room_apartment,
                building=a.building,
                receiver_name=a.receiver_name,
                additional_details=a.additional_details,
                latitude=a.latitude,
                longitude=a.longitude,
            )
            for a in addresses
        ],
        recent_orders=[
            OrderSummaryOut(
                id=o.id,
                order_number=o.order_number,
                status=o.status,
                total=o.total,
                created_at=o.created_at,
            )
            for o in recent_orders
        ],
    )


@router.patch("/{customer_id}", response_model=CustomerDetailOut)
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


@router.patch("/{customer_id}/addresses/{address_id}", response_model=AddressDetailOut)
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


@router.delete("/{customer_id}/addresses/{address_id}", status_code=204)
async def delete_address(
    customer_id: int,
    address_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> Response:
    customer = await session.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant.id,
        )
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    addr = await session.scalar(
        select(CustomerAddress).where(
            CustomerAddress.id == address_id,
            CustomerAddress.customer_id == customer_id,
        )
    )
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")

    # Block deletion if address linked to any open order
    open_order = await session.scalar(
        select(Order).where(
            Order.address_id == address_id,
            Order.status.in_(_OPEN_STATUSES),
        )
    )
    if open_order:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete address linked to an open order",
        )

    await session.delete(addr)
    await session.commit()
    return Response(status_code=204)
```

- [ ] **Step 4: Mount the router in `src/app/main.py`**

Check if `customers_router` is already mounted from Order Detail plan. If so, `customer_router` from this file is a separate router with overlapping prefix — consolidate by using the same router.

Actually the Order Detail plan adds `customers_router` inline in `ordering/router.py`. This plan creates a proper dedicated `customer_router.py`. To avoid conflicts:

1. Remove `customers_router` from `ordering/router.py` (the two PATCH endpoints added in Order Detail plan)
2. Move those endpoints into `customer_router.py`
3. Mount only `customer_router.py` in `main.py`

In `src/app/main.py`, add:

```python
from app.ordering.customer_router import router as customer_router
```

And in `create_app()`:

```python
app.include_router(customer_router)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/ordering/test_customer_profile.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 6: Run full suite**

```bash
.venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/app/ordering/customer_router.py src/app/main.py tests/ordering/test_customer_profile.py
git commit -m "feat: add customer profile and address management endpoints"
```

---

### Task 3: Frontend — types and API client

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/lib/customerApi.ts`

- [ ] **Step 1: Append to `frontend/src/lib/types.ts`**

```typescript
// Append to frontend/src/lib/types.ts

export interface OrderSummaryOut {
  id: number;
  order_number: string;
  status: OrderStatus;
  total: string;
  created_at: string;
}

export interface CustomerProfileOut extends CustomerDetailOut {
  tags: Record<string, unknown>;
  addresses: AddressDetailOut[];
  recent_orders: OrderSummaryOut[];
}

export interface CustomerListOut {
  items: CustomerDetailOut[];
  limit: number;
  offset: number;
}
```

- [ ] **Step 2: Create `frontend/src/lib/customerApi.ts`**

```typescript
// frontend/src/lib/customerApi.ts
import { apiClient } from "./apiClient";
import type {
  AddressDetailOut,
  AddressPatchIn,
  CustomerDetailOut,
  CustomerListOut,
  CustomerPatchIn,
  CustomerProfileOut,
} from "./types";

export async function listCustomers(params?: {
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<CustomerListOut> {
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const query = qs.toString() ? `?${qs}` : "";
  return apiClient.get<CustomerListOut>(`/api/v1/ordering/customers${query}`);
}

export async function getCustomerProfile(customerId: number): Promise<CustomerProfileOut> {
  return apiClient.get<CustomerProfileOut>(`/api/v1/ordering/customers/${customerId}`);
}

export async function patchCustomerProfile(
  customerId: number,
  body: CustomerPatchIn,
): Promise<CustomerDetailOut> {
  return apiClient.patch<CustomerDetailOut>(
    `/api/v1/ordering/customers/${customerId}`,
    body,
  );
}

export async function patchCustomerAddress(
  customerId: number,
  addressId: number,
  body: AddressPatchIn,
): Promise<AddressDetailOut> {
  return apiClient.patch<AddressDetailOut>(
    `/api/v1/ordering/customers/${customerId}/addresses/${addressId}`,
    body,
  );
}

export async function deleteCustomerAddress(
  customerId: number,
  addressId: number,
): Promise<void> {
  await apiClient.delete(`/api/v1/ordering/customers/${customerId}/addresses/${addressId}`);
}
```

- [ ] **Step 3: Check `apiClient` has `delete` method**

```bash
grep -n "delete\|DELETE" frontend/src/lib/apiClient.ts | head -5
```

If missing, add:

```typescript
delete(path: string): Promise<void> {
  return this.request<void>(path, { method: "DELETE" });
}
```

- [ ] **Step 4: Type-check**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npm run typecheck 2>&1 | tail -5
```

Expected: no new errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/customerApi.ts frontend/src/lib/apiClient.ts
git commit -m "feat: add CustomerProfileOut types and customerApi client"
```

---

### Task 4: Frontend — CustomerProfileScreen

**Files:**
- Create: `frontend/src/screens/CustomerProfileScreen.tsx`
- Create: `frontend/src/screens/CustomerProfileScreen.module.css`

- [ ] **Step 1: Create `frontend/src/screens/CustomerProfileScreen.tsx`**

```tsx
// frontend/src/screens/CustomerProfileScreen.tsx
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "../components/Button";
import { StatusPill } from "../components/StatusPill";
import { Spinner } from "../components/Spinner";
import {
  deleteCustomerAddress,
  getCustomerProfile,
  patchCustomerAddress,
  patchCustomerProfile,
} from "../lib/customerApi";
import type { AddressDetailOut, AddressPatchIn, CustomerProfileOut } from "../lib/types";
import s from "./CustomerProfileScreen.module.css";

export function CustomerProfileScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<CustomerProfileOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Edit state
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [optIn, setOptIn] = useState(false);

  useEffect(() => {
    if (!id) return;
    getCustomerProfile(Number(id))
      .then((p) => {
        setProfile(p);
        setName(p.name ?? "");
        setPhone(p.phone);
        setOptIn(p.marketing_opted_in);
      })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <Spinner />;
  if (!profile) return <p className={s.error}>Customer not found</p>;

  const identityDirty =
    name !== (profile.name ?? "") ||
    phone !== profile.phone ||
    optIn !== profile.marketing_opted_in;

  async function saveIdentity() {
    if (!profile) return;
    setSaving(true);
    try {
      const updated = await patchCustomerProfile(profile.id, {
        name: name || null,
        phone: phone || null,
        marketing_opted_in: optIn,
      });
      setProfile({ ...profile, ...updated });
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteAddress(addr: AddressDetailOut) {
    if (!profile) return;
    if (!window.confirm(`Delete address "${addr.building}"?`)) return;
    await deleteCustomerAddress(profile.id, addr.id);
    setProfile({
      ...profile,
      addresses: profile.addresses.filter((a) => a.id !== addr.id),
    });
  }

  async function handleSaveAddress(addr: AddressDetailOut, patch: AddressPatchIn) {
    if (!profile) return;
    const updated = await patchCustomerAddress(profile.id, addr.id, patch);
    setProfile({
      ...profile,
      addresses: profile.addresses.map((a) => (a.id === updated.id ? updated : a)),
    });
  }

  return (
    <div className={s.screen}>
      <div className={s.header}>
        <button className={s.back} onClick={() => navigate(-1)}>← Back</button>
        <h2 className={s.title}>{profile.name ?? profile.phone}</h2>
      </div>

      <div className={s.grid}>
        {/* Left column — identity + stats */}
        <div className={s.left}>
          <section className={s.card}>
            <h3 className={s.cardTitle}>Identity</h3>
            <label className={s.label}>Name</label>
            <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} />
            <label className={s.label}>Phone</label>
            <input className={s.input} value={phone} onChange={(e) => setPhone(e.target.value)} />
            <div className={s.toggleRow}>
              <label className={s.label}>WhatsApp Marketing</label>
              <button
                className={`${s.toggle} ${optIn ? s.toggleOn : s.toggleOff}`}
                onClick={() => setOptIn(!optIn)}
              >
                {optIn ? "OPT-IN" : "OPT-OUT"}
              </button>
            </div>
            <div className={s.saveRow}>
              <Button onClick={saveIdentity} disabled={!identityDirty || saving}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
          </section>

          <section className={s.card}>
            <h3 className={s.cardTitle}>Stats</h3>
            <div className={s.stats}>
              <Stat label="Total Orders" value={String(profile.total_orders)} />
              <Stat label="Total Spend" value={`AED ${profile.total_spend}`} />
              <Stat
                label="First Order"
                value={profile.first_order_at
                  ? new Date(profile.first_order_at).toLocaleDateString()
                  : "—"}
              />
              <Stat
                label="Last Order"
                value={profile.last_order_at
                  ? new Date(profile.last_order_at).toLocaleDateString()
                  : "—"}
              />
            </div>
          </section>
        </div>

        {/* Right column — addresses + order history */}
        <div className={s.right}>
          <section className={s.card}>
            <h3 className={s.cardTitle}>Addresses ({profile.addresses.length})</h3>
            {profile.addresses.length === 0 ? (
              <p className={s.empty}>No saved addresses</p>
            ) : (
              profile.addresses.map((addr) => (
                <AddressCard
                  key={addr.id}
                  addr={addr}
                  onDelete={() => handleDeleteAddress(addr)}
                  onSave={(patch) => handleSaveAddress(addr, patch)}
                />
              ))
            )}
          </section>

          <section className={s.card}>
            <h3 className={s.cardTitle}>Recent Orders</h3>
            {profile.recent_orders.length === 0 ? (
              <p className={s.empty}>No orders yet</p>
            ) : (
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Status</th>
                    <th>Total</th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.recent_orders.map((o) => (
                    <tr key={o.id} className={s.orderRow} onClick={() => navigate(`/orders?open=${o.id}`)}>
                      <td className={s.mono}>{o.order_number}</td>
                      <td><StatusPill status={o.status} /></td>
                      <td className={s.mono}>AED {o.total}</td>
                      <td>{new Date(o.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function AddressCard({
  addr,
  onDelete,
  onSave,
}: {
  addr: AddressDetailOut;
  onDelete: () => void;
  onSave: (patch: AddressPatchIn) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [aptRoom, setAptRoom] = useState(addr.room_apartment ?? "");
  const [building, setBuilding] = useState(addr.building ?? "");
  const [receiverName, setReceiverName] = useState(addr.receiver_name ?? "");
  const [notes, setNotes] = useState(addr.additional_details ?? "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await onSave({
        room_apartment: aptRoom || null,
        building: building || null,
        receiver_name: receiverName || null,
        additional_details: notes || null,
      });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={s.addressCard}>
      {editing ? (
        <>
          <input className={s.input} value={aptRoom} onChange={(e) => setAptRoom(e.target.value)} placeholder="Apt / Room" />
          <input className={s.input} value={building} onChange={(e) => setBuilding(e.target.value)} placeholder="Building" />
          <input className={s.input} value={receiverName} onChange={(e) => setReceiverName(e.target.value)} placeholder="Receiver name" />
          <input className={s.input} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" />
          <div className={s.addrActions}>
            <Button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
            <button className={s.cancel} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </>
      ) : (
        <>
          <p className={s.addrLine}>{[addr.room_apartment, addr.building].filter(Boolean).join(", ") || "—"}</p>
          {addr.receiver_name && <p className={s.addrMeta}>Receiver: {addr.receiver_name}</p>}
          {addr.additional_details && <p className={s.addrMeta}>{addr.additional_details}</p>}
          <div className={s.addrActions}>
            <button className={s.editBtn} onClick={() => setEditing(true)}>Edit</button>
            <button className={s.deleteBtn} onClick={onDelete}>Delete</button>
          </div>
        </>
      )}
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

- [ ] **Step 2: Create `frontend/src/screens/CustomerProfileScreen.module.css`**

```css
/* CustomerProfileScreen.module.css */
.screen { padding: 24px; max-width: 1100px; }

.header { align-items: center; display: flex; gap: 16px; margin-bottom: 24px; }
.back { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 0.85rem; }
.title { color: var(--text-primary); font-size: 1.2rem; font-weight: 700; margin: 0; }

.grid { display: grid; gap: 20px; grid-template-columns: 340px 1fr; }
.left { display: flex; flex-direction: column; gap: 16px; }
.right { display: flex; flex-direction: column; gap: 16px; }

.card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}
.cardTitle {
  color: var(--accent);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  margin-bottom: 12px;
  text-transform: uppercase;
}

.label {
  color: var(--text-secondary);
  display: block;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  margin-bottom: 2px;
  text-transform: uppercase;
}
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
.toggle { border: none; border-radius: 4px; cursor: pointer; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em; padding: 4px 10px; }
.toggleOn { background: #22c55e; color: #000; }
.toggleOff { background: var(--bg-tertiary); color: var(--text-secondary); }

.saveRow { margin-top: 4px; }

.stats { display: grid; gap: 12px; grid-template-columns: 1fr 1fr; }
.stat { text-align: center; }
.statValue { color: var(--text-primary); display: block; font-size: 1.1rem; font-weight: 700; }
.statLabel { color: var(--text-secondary); font-size: 0.7rem; text-transform: uppercase; }

.addressCard {
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 10px;
  padding: 10px 12px;
}
.addrLine { color: var(--text-primary); font-size: 0.9rem; margin: 0 0 2px; }
.addrMeta { color: var(--text-secondary); font-size: 0.8rem; margin: 0; }
.addrActions { display: flex; gap: 8px; margin-top: 8px; }
.editBtn { background: none; border: 1px solid var(--border); border-radius: 4px; color: var(--accent); cursor: pointer; font-size: 0.75rem; padding: 2px 8px; }
.deleteBtn { background: none; border: 1px solid var(--error); border-radius: 4px; color: var(--error); cursor: pointer; font-size: 0.75rem; padding: 2px 8px; }
.cancel { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 0.8rem; }

.table { border-collapse: collapse; width: 100%; }
.table th { color: var(--text-secondary); font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em; padding: 4px 8px; text-align: left; text-transform: uppercase; }
.table td { border-top: 1px solid var(--border); font-size: 0.85rem; padding: 8px; }
.orderRow { cursor: pointer; }
.orderRow:hover td { background: var(--bg-tertiary); }
.mono { font-family: monospace; }

.empty { color: var(--text-secondary); font-size: 0.85rem; font-style: italic; }
.error { color: var(--error); padding: 24px; }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/screens/CustomerProfileScreen.tsx frontend/src/screens/CustomerProfileScreen.module.css
git commit -m "feat: add CustomerProfileScreen with identity edit, address management, order history"
```

---

### Task 5: Wire up routing and nav

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavSidebar.tsx`

- [ ] **Step 1: Add route to `frontend/src/App.tsx`**

Find the existing route definitions in `App.tsx`. Add:

```tsx
import { CustomerProfileScreen } from "./screens/CustomerProfileScreen";
```

And add the route (after existing routes):

```tsx
<Route path="/customers/:id" element={<Guarded><CustomerProfileScreen /></Guarded>} />
```

- [ ] **Step 2: Add Customers nav item to `frontend/src/components/NavSidebar.tsx`**

Find the nav items array in `NavSidebar.tsx`. Add a Customers entry — place it after Orders:

```tsx
{ to: "/customers", label: "Customers", icon: "👥" }
```

Note: `/customers` with no `:id` will need a `CustomersListScreen` or redirect. For now, add a basic list screen.

- [ ] **Step 3: Create `frontend/src/screens/CustomersScreen.tsx`** (list page that links to profiles)

```tsx
// frontend/src/screens/CustomersScreen.tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CompactTable, type Column } from "../components/CompactTable";
import { listCustomers } from "../lib/customerApi";
import type { CustomerDetailOut } from "../lib/types";
import s from "./OrdersScreen.module.css"; // reuse same filter bar styles

export function CustomersScreen() {
  const [customers, setCustomers] = useState<CustomerDetailOut[]>([]);
  const [search, setSearch] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    listCustomers().then((r) => setCustomers(r.items));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return customers;
    return customers.filter(
      (c) =>
        (c.name ?? "").toLowerCase().includes(q) ||
        c.phone.includes(q),
    );
  }, [customers, search]);

  const columns: Column<CustomerDetailOut>[] = [
    { key: "name", header: "Name", render: (c) => c.name ?? "—" },
    { key: "phone", header: "Phone", render: (c) => c.phone },
    { key: "orders", header: "Orders", render: (c) => String(c.total_orders) },
    { key: "spend", header: "Spend", render: (c) => `AED ${c.total_spend}` },
    { key: "opt", header: "Marketing", render: (c) => c.marketing_opted_in ? "Opted In" : "Opted Out" },
  ];

  return (
    <div className={s.screen}>
      <div className={s.filterBar}>
        <input
          className={s.search}
          placeholder="Search name / phone"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <CompactTable<CustomerDetailOut>
        columns={columns}
        rows={filtered}
        rowKey={(c) => c.id}
        onRowClick={(c) => navigate(`/customers/${c.id}`)}
        emptyText="No customers found"
      />
    </div>
  );
}
```

- [ ] **Step 4: Add `/customers` route in `App.tsx`**

```tsx
import { CustomersScreen } from "./screens/CustomersScreen";
```

```tsx
<Route path="/customers" element={<Guarded><CustomersScreen /></Guarded>} />
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/NavSidebar.tsx frontend/src/screens/CustomersScreen.tsx
git commit -m "feat: add Customers nav, CustomersScreen list, and /customers/:id route"
```

---

### Task 6: Frontend tests

**Files:**
- Create: `frontend/src/screens/CustomerProfileScreen.test.tsx`

- [ ] **Step 1: Create `frontend/src/screens/CustomerProfileScreen.test.tsx`**

```tsx
// frontend/src/screens/CustomerProfileScreen.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CustomerProfileScreen } from "./CustomerProfileScreen";
import type { CustomerProfileOut } from "../lib/types";

const mockProfile: CustomerProfileOut = {
  id: 1,
  name: "Khalid Hassan",
  phone: "+971503334444",
  total_orders: 3,
  total_spend: "99.00",
  first_order_at: "2026-01-01T10:00:00Z",
  last_order_at: "2026-06-10T10:00:00Z",
  marketing_opted_in: true,
  tags: {},
  addresses: [
    {
      id: 1,
      room_apartment: "Villa 5",
      building: "Palm Residences",
      receiver_name: "Khalid Hassan",
      additional_details: null,
      latitude: null,
      longitude: null,
    },
  ],
  recent_orders: [
    {
      id: 10,
      order_number: "R1-0010",
      status: "delivered",
      total: "33.00",
      created_at: "2026-06-01T10:00:00Z",
    },
  ],
};

function renderProfile() {
  return render(
    <MemoryRouter initialEntries={["/customers/1"]}>
      <Routes>
        <Route path="/customers/:id" element={<CustomerProfileScreen />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(mockProfile), { status: 200 })),
  );
});

it("renders customer name and phone", async () => {
  renderProfile();
  await waitFor(() => screen.getByText("Khalid Hassan"));
  expect(screen.getByDisplayValue("+971503334444")).toBeTruthy();
});

it("shows addresses", async () => {
  renderProfile();
  await waitFor(() => screen.getByText(/Palm Residences/));
});

it("shows recent orders", async () => {
  renderProfile();
  await waitFor(() => screen.getByText("R1-0010"));
  expect(screen.getByText(/delivered/i)).toBeTruthy();
});

it("shows opt-in toggle", async () => {
  renderProfile();
  await waitFor(() => screen.getByText(/OPT-IN/i));
});

it("save button disabled until changes made", async () => {
  renderProfile();
  await waitFor(() => screen.getByRole("button", { name: /^Save$/i }));
  const saveBtn = screen.getByRole("button", { name: /^Save$/i });
  expect(saveBtn).toBeDisabled();
});
```

- [ ] **Step 2: Run frontend tests**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service/frontend"
npm test -- --run 2>&1 | tail -20
```

Expected: all tests pass including 5 new CustomerProfileScreen tests

- [ ] **Step 3: Run full backend test suite**

```bash
cd "/Users/syed/Files/untitled folder 2/Work/Catalystiq/Restaurant Whatsapp Service"
.venv/bin/pytest tests/ -q 2>&1 | tail -10
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/CustomerProfileScreen.test.tsx
git commit -m "test: add CustomerProfileScreen render and interaction tests"
```
