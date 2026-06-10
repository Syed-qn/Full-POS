# Order Detail, Customer Profile & AI Marketing Opt-out — Design Spec

**Date:** 2026-06-10
**Status:** Approved

---

## Sub-project A: Order Detail Enhancement

### Goal

When a dashboard manager clicks any order in the Orders list, a wide tabbed drawer slides in showing all order context: items, address, timeline, chat history, delivery route, and an editable customer profile — without leaving the Orders list.

### Layout

Wide side drawer — 60% viewport width, slides in from the right. Four tabs:

| Tab | Content |
|-----|---------|
| Overview | Items, address, receiver, rider, subtotal, delivery fee, total, payment method (always COD) |
| Timeline | Vertical audit log + Leaflet map with rider GPS route polyline |
| Chat | WhatsApp conversation bubbles (inbound left, outbound right) |
| Customer | Inline editable form: name, phone, address, marketing opt-in toggle |

Clicking a different order in the list replaces the drawer content without closing it.

### Architecture

**New files:**
- `src/app/ordering/detail_schemas.py` — `OrderDetailOut` and all nested sub-schemas
- `tests/ordering/test_order_detail.py` — service + API tests
- `tests/ordering/test_customer_patch.py` — customer/address patch tests
- `frontend/src/components/OrderDetailDrawer/` — drawer + four tab components
- `frontend/src/components/OrderDetailDrawer/OrderDetailDrawer.tsx`
- `frontend/src/components/OrderDetailDrawer/OrderDetailDrawer.module.css`
- `frontend/src/components/OrderDetailDrawer/OverviewTab.tsx`
- `frontend/src/components/OrderDetailDrawer/TimelineTab.tsx`
- `frontend/src/components/OrderDetailDrawer/ChatTab.tsx`
- `frontend/src/components/OrderDetailDrawer/CustomerTab.tsx`
- `frontend/src/lib/orderDetailApi.ts`

**Modified files:**
- `src/app/ordering/service.py` — add `get_order_detail()`, `patch_customer()`, `patch_address()`, `toggle_marketing_opt()`
- `src/app/ordering/router.py` — add 3 endpoints
- `src/app/marketing/optout.py` — add `record_opt_in()`
- `frontend/src/screens/OrdersScreen.tsx` — add selectedOrderId state + mount drawer

### API Endpoints

```
GET  /api/v1/orders/{order_id}/detail        → OrderDetailOut
PATCH /api/v1/ordering/customers/{customer_id}              → CustomerDetailOut
PATCH /api/v1/ordering/customers/{customer_id}/addresses/{address_id}  → AddressDetailOut
```

The drawer calls only `GET /orders/{id}/detail`. The Customer tab's Save button calls the two PATCH endpoints. Marketing toggle calls PATCH customers with `marketing_opted_in` field.

### Schema

```python
# ordering/detail_schemas.py

class OrderItemDetailOut(BaseModel):
    dish_number: int
    dish_name: str
    qty: int
    price_aed: Decimal
    line_total: Decimal           # price_aed * qty

class AddressDetailOut(BaseModel):
    id: int
    room_apartment: str | None
    building: str | None
    receiver_name: str | None
    additional_details: str | None
    latitude: float | None
    longitude: float | None

class CustomerDetailOut(BaseModel):
    id: int
    name: str | None
    phone: str
    total_orders: int
    total_spend: Decimal
    first_order_at: datetime | None
    last_order_at: datetime | None
    marketing_opted_in: bool

class RiderDetailOut(BaseModel):
    id: int
    name: str
    phone: str

class TimelineEventOut(BaseModel):
    ts: datetime
    action: str
    actor: str
    after: dict | None

class ChatMessageOut(BaseModel):
    direction: str                # "inbound" | "outbound"
    text: str | None              # None for location/image — show placeholder
    ts: int                       # unix epoch

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
    route: list[GpsPingOut]       # empty list = no pings / no rider

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

### Service Logic

`get_order_detail(session, *, restaurant_id, order_id)`:
1. Load `Order` — 404 if not found or `restaurant_id` mismatch
2. Load `OrderItem` list
3. Load `Customer`
4. Load `CustomerAddress` via `order.address_id` (may be None)
5. Load `Rider` via `order.rider_id` (may be None)
6. Load `AuditLog` where `entity="order"` AND `entity_id=str(order_id)` ORDER BY `created_at`
7. Find `Conversation` by `phone=customer.phone` AND `restaurant_id` → load `Message` list ORDER BY `ts`
8. If `rider_id`: load `RiderLocation` where `rider_id=order.rider_id` AND `ts` BETWEEN `Assignment.assigned_at` AND (`order.delivered_at` OR NOW()) ORDER BY `ts`
9. Call `is_opted_out(session, restaurant_id, customer.phone)` → invert for `marketing_opted_in`

`patch_customer(session, *, restaurant_id, customer_id, data: CustomerPatchIn)`:
- 404 if customer not in tenant
- Apply non-None fields
- If `marketing_opted_in` is False → `record_opt_out()`; if True → `record_opt_in()`

`patch_address(session, *, restaurant_id, customer_id, address_id, data: AddressPatchIn)`:
- 404 if address not owned by customer or customer not in tenant
- Apply non-None fields

`record_opt_in(session, *, restaurant_id, phone)` in `marketing/optout.py`:
- DELETE FROM `marketing_optouts` WHERE `restaurant_id=X AND phone=Y` (idempotent)

### Error Handling

| Scenario | Response |
|----------|----------|
| Order not found or wrong tenant | 404 |
| No conversation (manual order) | `chat: []` — no error |
| No rider assigned | `rider: null`, `route: []` |
| Order in-progress (no `delivered_at`) | Route window uses `NOW()` as upper bound |
| Phone conflict on customer patch | 409 Conflict |
| Address not owned by customer | 404 |

### Frontend

`OrdersScreen` gains `selectedOrderId: number | null` state. Clicking a row sets it; pressing Escape or clicking the overlay clears it.

`OrderDetailDrawer` is a fixed right panel. On `selectedOrderId` change it calls `fetchOrderDetail(id)` and shows a skeleton loader while pending.

`TimelineTab`: renders Leaflet map in a `useEffect` after mount (Leaflet requires DOM). Map only rendered when `route.length > 0`. Polyline in `#0ea5e9`. Amber circle at route start (restaurant), green circle at end (delivery point).

`ChatTab`: `useEffect` scrolls `chatContainerRef.current` to `scrollHeight` on open. Non-text messages render as `[📍 location]` or `[🖼 image]`.

`CustomerTab`: local `useState` mirrors server values. Dirty-check: Save button enabled only when form differs from loaded values. On save: calls customer PATCH then address PATCH (parallel), then updates drawer cache.

### Testing

**Backend — `tests/ordering/test_order_detail.py`:**
- Full order returns correct `OrderDetailOut` shape
- Missing rider → `rider: null`, `route: []`
- Timeline events sourced from audit log
- Chat messages sourced from conversation messages
- GPS pings filtered to assignment time window
- No conversation → `chat: []` (no crash)
- Opt-out flag inverted correctly
- 404 on wrong tenant
- 404 on unknown order id

**Backend — `tests/ordering/test_customer_patch.py`:**
- Patch name updates Customer row
- Patch phone updates Customer row
- Toggle opt-in calls `record_opt_in()`
- Toggle opt-out calls `record_opt_out()`
- Address patch updates CustomerAddress row
- 404 on wrong tenant customer
- 404 on address not owned by customer

**Frontend — `OrderDetailDrawer.test.tsx`:**
- Renders overview items with dish numbers
- Tab switching shows correct panel
- Customer Save calls PATCH with changed fields only
- Empty route: map not rendered
- Chat auto-scrolls to bottom on open
- Non-text message renders placeholder

---

## Sub-project B: Customer Profile Screen

### Goal

A dedicated `/customers/:id` screen accessible from the top-level Customers nav item and from a secondary "Open Full Profile →" link in the Order Detail Customer tab. Shows full order history, all addresses, and complete editing. The Customer tab in the drawer covers quick edits; this screen is for deep-dive customer management.

### Layout

Full-screen page. Two-column:
- Left: customer identity card (name, phone, stats, opt-in toggle, tags)
- Right: order history list (read-only, links back to order detail drawer), address book

### Architecture

**New files:**
- `src/app/ordering/customer_router.py` — customer CRUD endpoints
- `frontend/src/screens/CustomerProfileScreen.tsx`
- `frontend/src/screens/CustomerProfileScreen.module.css`
- `frontend/src/lib/customerApi.ts`

**Modified files:**
- `src/app/ordering/router.py` or `app/main.py` — mount customer router
- `frontend/src/App.tsx` — add `/customers/:id` route
- `frontend/src/components/NavSidebar.tsx` — add Customers nav item

### API Endpoints

```
GET    /api/v1/ordering/customers                                       → paginated list (search by name/phone)
GET    /api/v1/ordering/customers/{id}                                  → CustomerProfileOut
PATCH  /api/v1/ordering/customers/{id}                                  → CustomerDetailOut (same as Sub-project A)
PATCH  /api/v1/ordering/customers/{id}/addresses/{addr_id}              → AddressDetailOut
DELETE /api/v1/ordering/customers/{id}/addresses/{addr_id}              → 204
```

`CustomerProfileOut` extends `CustomerDetailOut` with:
- `addresses: list[AddressDetailOut]`
- `recent_orders: list[OrderSummaryOut]` (last 10: order_number, status, total, created_at)
- `tags: dict`

### Error Handling

- 404 if customer not in tenant
- Phone uniqueness: 409 on conflict
- Cannot delete address currently referenced by an open order (status not delivered/cancelled): 409

### Testing

- List returns only tenant's customers
- Search by partial phone works
- Profile returns addresses + recent orders
- Cannot delete address linked to open order

---

## Sub-project C: AI Marketing Opt-out

### Goal

When a customer sends a natural-language message like "stop sending me marketing", "don't message me promotions", "unsubscribe", the AI conversation agent detects intent and calls `record_opt_out()` — same effect as sending "STOP".

### Architecture

**Modified files:**
- `src/app/conversation/engine.py` — add opt-out intent detection before routing to AI
- `src/app/marketing/optout.py` — add `OPTOUT_PHRASES` list + `is_optout_intent(text)` function
- `tests/marketing/test_optout_intent.py` — unit tests for intent detection
- `tests/conversation/test_engine.py` — engine integration test

### Detection Strategy

`is_optout_intent(text: str) -> bool` — two-tier check:

**Tier 1 (exact keywords, already exists):** `is_stop_keyword()` handles STOP/UNSUBSCRIBE/CANCEL/END/QUIT.

**Tier 2 (phrase matching):** Check lowercased text against a curated list of patterns:
```python
OPTOUT_PHRASES = [
    "stop sending",
    "stop messaging",
    "don't send",
    "dont send",
    "no more messages",
    "no more marketing",
    "unsubscribe",
    "opt out",
    "opt-out",
    "remove me",
    "don't message",
    "dont message",
    "stop marketing",
    "no promotions",
    "stop promotions",
]
```

Simple substring match — no regex, no AI call for this check. Fast and deterministic.

### Engine Integration

In `engine.py`, before routing TEXT messages to the AI agent, add:

```python
from app.marketing.optout import is_stop_keyword, is_optout_intent, record_opt_out

if inbound.type == MessageType.TEXT:
    text = inbound.payload.get("text", "")
    if is_stop_keyword(text) or is_optout_intent(text):
        await record_opt_out(session, restaurant_id=restaurant_id, phone=inbound.from_phone)
        await enqueue_message(session, to_phone=inbound.from_phone,
                              restaurant_id=restaurant_id,
                              body="You've been unsubscribed from marketing messages. "
                                   "Reply START to opt back in.")
        return
```

`is_stop_keyword()` check stays where it is for backward compatibility; `is_optout_intent()` is the new path.

### Error Handling

- `record_opt_out()` is already idempotent — safe to call multiple times
- Opt-out confirmation message always sent regardless of prior opt-out status

### Testing

**`tests/marketing/test_optout_intent.py`:**
- `is_optout_intent("stop sending me marketing messages")` → True
- `is_optout_intent("don't message me anymore")` → True
- `is_optout_intent("I want to order biryani")` → False
- `is_optout_intent("STOP")` → False (handled by `is_stop_keyword`, not this function)
- Case-insensitive: `"STOP SENDING ME"` → True

**`tests/conversation/test_engine.py`:**
- Natural language opt-out records opt-out in DB
- Natural language opt-out sends confirmation message to outbox
- Normal ordering message not misclassified as opt-out

---

## Implementation Order

1. **Sub-project C** (AI Opt-out) — smallest, fully self-contained, no frontend
2. **Sub-project A** (Order Detail) — backend + frontend, highest manager value
3. **Sub-project B** (Customer Profile) — depends on patterns established in A
