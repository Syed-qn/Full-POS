# Manual Order Creation (Dashboard) — Design Spec

**Goal:** Allow restaurant managers to place delivery orders on behalf of walk-in or phone customers directly from the dashboard, bypassing the WhatsApp bot flow.

**Architecture:** A dedicated "New Order" screen (single scrollable page) in the dashboard nav. Two new backend endpoints handle customer lookup and order creation. The service layer reuses existing `get_or_create_customer`, `upsert_address`, `add_item`, and `finalize_confirmation` functions. The created order enters the same FSM as bot-placed orders and triggers a WhatsApp confirmation to the customer.

**Tech Stack:** FastAPI (backend), async SQLAlchemy 2, React + TypeScript (frontend), existing OutboxMessage system for WhatsApp delivery.

---

## Use Case

A customer walks into the restaurant or calls on the phone and requests a delivery. The manager opens the dashboard, navigates to "New Order", enters the customer's phone and delivery details, picks items from the active menu, and places the order. The customer receives a WhatsApp confirmation and all subsequent status updates (rider assigned, on the way, delivered) exactly as if they had ordered via the bot.

---

## Backend

### Endpoints

**`GET /api/v1/orders/manual/customer-lookup`**

Query param: `phone` (E.164 format, e.g. `+971501234567`)

Response (200):
```json
{
  "name": "Ahmed Al Rashid",
  "last_address": {
    "apt_room": "Apt 404",
    "building": "Marina Tower",
    "receiver_name": "Ahmed Al Rashid",
    "notes": null
  }
}
```

Response (404): customer not found — frontend treats as new customer, no prefill.

Auth: manager JWT required (`current_restaurant` dependency).

---

**`POST /api/v1/orders/manual`**

Request body:
```json
{
  "customer_phone": "+971501234567",
  "customer_name": "Ahmed Al Rashid",
  "items": [
    {"dish_id": 1, "qty": 2, "notes": null},
    {"dish_id": 4, "qty": 1, "notes": "extra spicy"}
  ],
  "address": {
    "apt_room": "Apt 404",
    "building": "Marina Tower",
    "receiver_name": "Ahmed Al Rashid",
    "notes": null
  },
  "delivery_fee_aed": "0.00"
}
```

Response (200): `OrderOut` — the confirmed order with SLA clock started.

Errors:
- 422 `"No active menu for this restaurant"` — no active menu exists
- 422 `"Dish {id} not found or unavailable"` — dish missing or `is_available=False`
- 422 `"items must not be empty"` — no items in request
- 422 `"customer_phone is required"` — phone missing

Auth: manager JWT required.

---

### Service: `create_manual_order`

New function in `src/app/ordering/service.py`:

```python
async def create_manual_order(
    session,
    *,
    restaurant_id: int,
    customer_phone: str,
    customer_name: str | None,
    items: list[dict],          # [{dish_id, qty, notes}]
    apt_room: str,
    building: str,
    receiver_name: str,
    address_notes: str | None,
    delivery_fee_aed: Decimal,
) -> Order
```

Steps:
1. Verify active menu exists for restaurant — raise 422 if not
2. Validate all dish IDs exist, belong to restaurant, and are available — raise 422 on first failure
3. `get_or_create_customer(phone)` — creates customer row if new; updates `name` if provided and customer is new
4. `upsert_address(apt_room, building, receiver_name, notes, confirmed=True)`
5. `create_draft_order` → set `delivery_fee_aed` + `address_id`
6. `add_item` for each item (recalculates subtotal + total after each)
7. `finalize_confirmation(order, actor="manager")` — draft → pending_confirmation → confirmed, sets `sla_confirmed_at` + `sla_deadline` (+40 min)
8. Enqueue `OutboxMessage` to customer phone: `"Your order #{order_number} has been placed! Total: AED {total} (COD). Your food will arrive in ~40 minutes 🛵"`
9. Return order

No conversation record is created. No `Conversation` row is touched. This is a manager-only flow.

---

### Schemas

New Pydantic models in `src/app/ordering/schemas.py`:

```python
class ManualOrderItemIn(BaseModel):
    dish_id: int
    qty: int = Field(ge=1, le=50)
    notes: str | None = None

class ManualOrderAddressIn(BaseModel):
    apt_room: str = Field(min_length=1)
    building: str = Field(min_length=1)
    receiver_name: str = Field(min_length=1)
    notes: str | None = None

class ManualOrderIn(BaseModel):
    customer_phone: str = Field(min_length=7)
    customer_name: str | None = None
    items: list[ManualOrderItemIn] = Field(min_length=1)
    address: ManualOrderAddressIn
    delivery_fee_aed: Decimal = Decimal("0.00")

class AddressOut(BaseModel):
    apt_room: str
    building: str
    receiver_name: str
    notes: str | None

class CustomerLookupOut(BaseModel):
    name: str | None
    last_address: AddressOut | None
```

---

## Frontend

### Files

| File | Purpose |
|---|---|
| `frontend/src/screens/NewOrderScreen.tsx` | Main screen component |
| `frontend/src/screens/NewOrderScreen.module.css` | Styles |
| `frontend/src/screens/NewOrderScreen.test.tsx` | Vitest tests |
| `frontend/src/lib/manualOrderApi.ts` | `lookupCustomer` + `createManualOrder` API calls |

`App.tsx` gets a new nav entry: `➕ New Order` → `/new-order`.

### Layout

Single scrollable page, two-column grid:

**Left column:**
- CUSTOMER section: phone input + "Look up" button; name field (prefilled if found, editable); found/new status indicator
- DELIVERY ADDRESS section: apt/room, building, receiver name, notes (all text inputs); delivery fee tier selector (3 buttons: Free ≤3km / AED 5 / AED 10)

**Right column:**
- ITEMS section: search bar + dishes grouped by category, each row has dish number + name + price + −/qty/+ controls; highlighted (border + background) when qty > 0
- ORDER SUMMARY panel (sticky at bottom of right column): line items, subtotal, delivery fee, total in AED

**Bottom bar (full width):**
- Left: "📱 WhatsApp confirmation will be sent to {phone}"
- Right: Cancel button + "Place Order — AED {total}" button (disabled when required fields empty or no items)

### State

```typescript
interface NewOrderState {
  phone: string
  name: string
  lookupStatus: 'idle' | 'found' | 'new' | 'error'
  quantities: Record<number, number>   // dish_id → qty
  apt_room: string
  building: string
  receiver_name: string
  address_notes: string
  delivery_fee_aed: '0.00' | '5.00' | '10.00'
  submitting: boolean
  error: string | null
}
```

### API Functions (`manualOrderApi.ts`)

```typescript
export async function lookupCustomer(phone: string): Promise<CustomerLookupOut | null>
// Returns null on 404, throws on other errors

export async function createManualOrder(body: ManualOrderIn): Promise<OrderOut>
// Throws ApiError on 4xx/5xx
```

---

## Error Handling

| Condition | Behaviour |
|---|---|
| Phone field empty | Submit button disabled |
| No items selected | Submit button disabled; "Add at least 1 item" hint near summary |
| Apt / building / receiver missing | Submit button disabled |
| Dish unavailable (422 from API) | Inline error banner: "Dish X is no longer available. Remove it and try again." |
| No active menu (422 from API) | Error banner: "No active menu. Activate a menu before placing orders." |
| Network error | Error banner with retry |

---

## Testing

### Backend (`tests/ordering/test_manual_order.py`)

- `test_create_manual_order_new_customer` — new phone → customer created, order `confirmed`, items correct, SLA deadline set ~40 min ahead
- `test_create_manual_order_existing_customer` — known phone → reuses customer row, new address stored
- `test_customer_lookup_found` — GET returns name + last confirmed address
- `test_customer_lookup_not_found` — GET returns 404
- `test_create_manual_order_unavailable_dish` — 422 with dish name in message
- `test_create_manual_order_no_active_menu` — 422 with clear message
- `test_outbox_message_enqueued_after_manual_order` — OutboxMessage row exists with correct phone + order number

### Frontend (`NewOrderScreen.test.tsx`)

- Renders customer, items, address, delivery fee, and summary sections
- Phone lookup on blur: found → prefills name + address; 404 → clears fields, shows "New customer"
- `+` button increments qty, `−` decrements to minimum 0; summary total updates live
- Submit disabled when phone empty, no items selected, or required address fields empty
- Successful submit calls `createManualOrder` and navigates to `/orders`
- API error shows inline error banner

---

## Business Rules

- Manual orders skip WhatsApp chat flow entirely — no `Conversation` row created or modified
- Order enters FSM at `confirmed` (same as bot-confirmed orders) — all downstream flows (kitchen, dispatch, SLA monitor, late-delivery coupon) apply unchanged
- Delivery fee is manager-selected (3 tiers) — no GPS distance check required
- Customer receives exactly one WhatsApp confirmation on order creation; subsequent status updates (rider assigned, arriving, etc.) are sent by existing dispatch/tracking systems
- Unavailable dishes are rejected at API level — manager must remove them before placing
- No limit on simultaneous active orders per customer phone for manual orders
