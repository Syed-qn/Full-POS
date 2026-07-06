# Restaurant WhatsApp Platform — API Reference

Complete request/response documentation for the platform HTTP API, webhooks, and authentication.

**Base URL (local dev):** `http://localhost:8000`  
**OpenAPI (auto-generated):** `http://localhost:8000/docs`  
**Spec (business rules):** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`

---

## Table of contents

1. [Authentication](#authentication)
2. [Common conventions](#common-conventions)
3. [System](#system)
4. [Identity & onboarding](#identity--onboarding)
5. [Orders](#orders)
6. [Customers](#customers)
7. [Inbound webhooks (Meta → platform)](#inbound-webhooks-meta--platform)
8. [Outbound webhooks (platform → POS)](#outbound-webhooks-platform--pos)
9. [Partner API (POS integration)](#partner-api-pos-integration)
10. [Menu](#menu)
11. [Catalog](#catalog)
12. [Conversations](#conversations)
13. [Dispatch & tracking](#dispatch--tracking)
14. [Rider app](#rider-app)
15. [Wallet, coupons, tickets, COD](#wallet-coupons-tickets-cod)
16. [Marketing](#marketing)
17. [Predictions & POS sync](#predictions--pos-sync)
18. [Order status reference](#order-status-reference)

---

## Authentication

The API uses **two authentication modes**, depending on the surface:

| Surface | Header | Who uses it |
|---------|--------|-------------|
| Manager dashboard API | `Authorization: Bearer <jwt>` | React dashboard, manager tools |
| Partner / POS API | `X-API-Key: <api_key>` | External POS (e.g. Cratis) |
| Cron ticks | `X-Tick-Secret: <secret>` | External cron (cart/marketing sweeps) |
| Public tracking | None (token in URL path) | Customer tracking links |

### Obtain a JWT (manager)

```http
POST /api/v1/auth/login
Content-Type: application/json
```

**Request body**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `email` | string | yes | Valid email, normalized to lowercase |
| `password` | string | yes | min 1 char |

**Sample request**

```json
{
  "email": "manager@restaurant.ae",
  "password": "hunter2!"
}
```

**Sample response** `200 OK`

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors**

| Status | Meaning |
|--------|---------|
| `401` | Invalid credentials |
| `429` | Rate limited (`rate_limit_auth`) |

Use the token on all `/api/v1/*` manager endpoints:

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Obtain an API key (partner)

Keys are minted by the manager (JWT) and shown **once** at creation:

```http
POST /api/v1/api-keys
Authorization: Bearer <jwt>
Content-Type: application/json

{ "label": "Cratis POS — DXB store" }
```

**Sample response** `201 Created`

```json
{
  "id": 3,
  "label": "Cratis POS — DXB store",
  "key_prefix": "rwsk_a1b2",
  "created_at": "2026-07-07T10:00:00+00:00",
  "last_used_at": null,
  "revoked_at": null,
  "api_key": "rwsk_a1b2c3d4e5f6...full-secret-shown-once"
}
```

Partner endpoints require:

```http
X-API-Key: rwsk_a1b2c3d4e5f6...
```

---

## Common conventions

### Content type

- JSON bodies: `Content-Type: application/json`
- File uploads: `multipart/form-data`

### Money

- Stored as `Decimal` in the database.
- Serialized as **strings** in order list/detail responses (`total_aed`, `price_aed`) for JavaScript safety.
- Partner API uses **floats** for monetary fields.

### Timestamps

- ISO 8601 UTC strings in most responses (e.g. `"2026-07-07T10:15:00+00:00"`).
- Unix epoch integers for conversation message `ts`.

### Multi-tenancy

Every tenant-scoped row carries `restaurant_id`. Manager and partner auth resolves the tenant automatically — you never pass `restaurant_id` in the body for those surfaces.

### Standard error shape

FastAPI returns:

```json
{
  "detail": "Human-readable error message"
}
```

Or for validation errors:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "customer_phone"],
      "msg": "String should have at least 7 characters",
      "input": "123"
    }
  ]
}
```

### Pagination query params

| Param | Type | Default | Max |
|-------|------|---------|-----|
| `limit` | integer | varies | 50–500 per endpoint |
| `offset` | integer | 0 | — |

---

## System

### Health check

```http
GET /health
```

**Response** `200 OK`

```json
{ "status": "ok" }
```

### Version / deploy commit

```http
GET /version
```

**Response** `200 OK`

```json
{
  "commit": "abc123def456...",
  "short": "abc123d"
}
```

### Prometheus metrics

```http
GET /metrics
```

Returns Prometheus text format (`text/plain`).

---

## Identity & onboarding

Prefix: `/api/v1` — all endpoints require **JWT** unless noted.

### Sign up

```http
POST /api/v1/auth/signup
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | yes | 1–255 chars |
| `email` | string | yes | Valid email |
| `password` | string | yes | min 8 chars |
| `phone` | string | no | For tests/seeding only; real WhatsApp number set on Meta connect |
| `lat` | float | no | Default `0.0`, -90..90 |
| `lng` | float | no | Default `0.0`, -180..180 |

**Sample response** `201 Created` — `RestaurantOut`

```json
{
  "id": 1,
  "name": "Biryani House",
  "email": "manager@biryani.ae",
  "phone": null,
  "lat": 25.2048,
  "lng": 55.2708,
  "settings": { }
}
```

### Current restaurant profile

```http
GET /api/v1/me
PATCH /api/v1/me
```

**PATCH body** (`ProfilePatch`)

| Field | Type | Required |
|-------|------|----------|
| `name` | string | yes |
| `lat` | float | no |
| `lng` | float | no |

### Onboarding status

```http
GET /api/v1/onboarding/status
```

**Response** — `OnboardingStatusOut`

```json
{
  "complete": false,
  "has_location": true,
  "has_menu": true,
  "has_catalog_id": false,
  "catalog_synced": false,
  "has_meta": false
}
```

### Meta / WhatsApp connection

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/onboarding/meta-config` | Read connection (token never returned) |
| `PATCH` | `/api/v1/onboarding/meta-config` | Manual paste of Meta credentials |
| `POST` | `/api/v1/onboarding/meta-connect` | Embedded Signup result |
| `POST` | `/api/v1/onboarding/meta-disconnect` | Clear credentials |
| `POST` | `/api/v1/onboarding/meta-resubscribe` | Re-subscribe WABA webhooks |
| `GET` | `/api/v1/onboarding/meta-embed-config` | Frontend ES popup config |
| `POST` | `/api/v1/onboarding/complete` | Mark onboarding done |

**MetaConnectIn** (Embedded Signup)

```json
{
  "code": "<oauth-code-from-facebook-popup>",
  "phone_number_id": "123456789012345",
  "waba_id": "987654321098765",
  "partner": "cratis"
}
```

**MetaConfigOut** (read — no secrets)

```json
{
  "wa_phone_number_id": "123456789012345",
  "wa_business_account_id": "987654321098765",
  "wa_access_token_set": true,
  "catalog_id": "112233445566778",
  "connected": true,
  "api_key": null
}
```

`api_key` is returned **once** on `meta-connect` when partner auto-provisioning runs.

### Restaurant settings

```http
PATCH /api/v1/settings
```

Partial update — only send fields you want to change. See `SettingsPatch` in `src/app/identity/schemas.py` for the full list (delivery fee tiers, batching, open hours, loyalty, resale, cart recovery, etc.).

**Sample: delivery fee tiers**

```json
{
  "delivery_fee_tiers": [
    { "max_km": 3, "fee_aed": 0 },
    { "max_km": 5, "fee_aed": 5 },
    { "max_km": 10, "fee_aed": 10 }
  ]
}
```

### Riders

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/riders` | Create rider (auto-sends app invite via WhatsApp) |
| `GET` | `/api/v1/riders` | List riders with delivery tallies + last location |
| `GET` | `/api/v1/riders/{rider_id}/location` | Latest GPS ping |
| `PATCH` | `/api/v1/riders/{rider_id}` | Update status, on_duty, name, or phone |
| `POST` | `/api/v1/riders/{rider_id}/app-invite` | Re-send pairing code |
| `DELETE` | `/api/v1/riders/{rider_id}` | Delete (409 if rider has delivery history) |

**RiderIn**

```json
{
  "name": "Ahmed Ali",
  "phone": "+971501234567"
}
```

**RiderOut**

```json
{
  "id": 3,
  "name": "Ahmed Ali",
  "phone": "+971501234567",
  "status": "available",
  "on_duty": true,
  "delivered_24h": 4,
  "delivered_lifetime": 128,
  "last_lat": 25.112,
  "last_lng": 55.221,
  "last_location_at": "2026-07-07T09:30:00+00:00"
}
```

**RiderPatch** — send one of: `status`, `on_duty`, `name`, `phone`

```json
{ "on_duty": false }
```

`status` values: `available` | `on_delivery` | `off_shift` | `deactivated`

---

## Orders

Prefix: `/api/v1/orders` — **JWT** required.

Orders are created in three ways:

1. **WhatsApp conversation** — customer confirms via chat (no REST create endpoint; flows through inbound webhook).
2. **WhatsApp catalog cart** — `type: "order"` message on inbound webhook.
3. **Manual order** — manager creates from dashboard (`POST /manual`).

### List orders

```http
GET /api/v1/orders?status=confirmed&limit=50&offset=0&preview_batch=true
```

| Query param | Type | Default | Description |
|-------------|------|---------|-------------|
| `status` | string | — | Filter by order status |
| `limit` | integer | 50 | Page size |
| `offset` | integer | 0 | Skip |
| `from_date` | string | — | ISO date filter |
| `to_date` | string | — | ISO date filter |
| `q` | string | — | Search order number, phone, name |
| `preview_batch` | boolean | true | Include batch preview labels |

**Response** `200 OK` — `OrderOut[]`

```json
[
  {
    "id": 42,
    "order_number": "R1-0042",
    "status": "confirmed",
    "customer_name": "Fatima",
    "customer_phone": "+971501234567",
    "items": [
      {
        "dish_number": 110,
        "name": "Chicken Biryani",
        "qty": 2,
        "price_aed": "22.00",
        "variant_name": "4 serve",
        "notes": "extra spicy"
      }
    ],
    "total_aed": "54.00",
    "rider_id": null,
    "rider_name": null,
    "sla_started_at": "2026-07-07T10:00:00+00:00",
    "prep_deadline": "2026-07-07T10:25:00+00:00",
    "cook_estimate_minutes": 20,
    "created_at": "2026-07-07T10:00:00+00:00",
    "address": "Apt 1204, Marina Tower",
    "lat": 25.081,
    "lng": 55.139,
    "batch_id": null,
    "batch_size": null,
    "batch_order_numbers": [],
    "batch_preview": "A",
    "resale_of_order_id": null
  }
]
```

### Get single order

```http
GET /api/v1/orders/{order_id}
```

Returns one `OrderOut` (same shape as list item).

### Order detail (rich)

```http
GET /api/v1/orders/{order_id}/detail?include=overview,timeline,chat,route
```

| Query `include` | Sections loaded |
|-----------------|-----------------|
| `overview` | Default — items, customer, address, SLA |
| `timeline` | Audit timeline events |
| `chat` | WhatsApp messages for this order |
| `route` | Rider GPS pings |
| `dispatch` | Dispatch explainability |

**Response** — `OrderDetailOut` (excerpt)

```json
{
  "id": 42,
  "order_number": "R1-0042",
  "status": "preparing",
  "items": [
    {
      "dish_number": 110,
      "dish_name": "Chicken Biryani",
      "variant_name": null,
      "qty": 2,
      "price_aed": "22.00",
      "notes": null,
      "line_total": "44.00"
    }
  ],
  "address": {
    "id": 7,
    "room_apartment": "1204",
    "building": "Marina Tower",
    "receiver_name": "Fatima",
    "additional_details": "Call on arrival",
    "latitude": 25.081,
    "longitude": 55.139
  },
  "customer": {
    "id": 15,
    "name": "Fatima",
    "phone": "+971501234567",
    "total_orders": 12,
    "total_spend": "840.00",
    "first_order_at": "2026-01-15T12:00:00+00:00",
    "last_order_at": "2026-07-01T18:30:00+00:00",
    "marketing_opted_in": true
  },
  "rider": null,
  "subtotal": "44.00",
  "delivery_fee_aed": "10.00",
  "total": "54.00",
  "created_at": "2026-07-07T10:00:00+00:00",
  "delivered_at": null,
  "sla_deadline": "2026-07-07T10:40:00+00:00",
  "sla_started_at": "2026-07-07T10:00:00+00:00",
  "prep_deadline": "2026-07-07T10:25:00+00:00",
  "cook_estimate_minutes": 20,
  "timeline": [],
  "chat": [],
  "convo_summary": "2× Chicken Biryani",
  "route": [],
  "batch_preview_label": null,
  "dispatch_explain": null
}
```

### Create manual order

```http
POST /api/v1/orders/manual
```

**Request** — `ManualOrderIn`

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `customer_phone` | string | yes | min 7 chars |
| `customer_name` | string | no | |
| `items` | array | yes | min 1 item |
| `items[].dish_id` | integer | yes | Active menu dish ID |
| `items[].qty` | integer | yes | 1–50 |
| `items[].notes` | string | no | Kitchen notes |
| `address` | object | yes | See below |
| `delivery_fee_aed` | decimal | no | Default `0.00` |

**Address** — `ManualOrderAddressIn`

| Field | Type | Required |
|-------|------|----------|
| `apt_room` | string | yes |
| `building` | string | yes |
| `receiver_name` | string | yes |
| `notes` | string | no |
| `latitude` | float | no | -90..90 |
| `longitude` | float | no | -180..180 |

**Sample request**

```json
{
  "customer_phone": "+971501234567",
  "customer_name": "Fatima Hassan",
  "items": [
    { "dish_id": 88, "qty": 2, "notes": "less oil" },
    { "dish_id": 91, "qty": 1 }
  ],
  "address": {
    "apt_room": "1204",
    "building": "Marina Tower",
    "receiver_name": "Fatima",
    "notes": "Gate 2",
    "latitude": 25.081,
    "longitude": 55.139
  },
  "delivery_fee_aed": "10.00"
}
```

**Response** `200 OK` — `OrderOut` (confirmed order, same shape as list)

**Errors**

| Status | Cause |
|--------|-------|
| `422` | Invalid dish, out of delivery radius (>10 km), missing price, etc. |
| `401` | Missing/invalid JWT |

Side effects: triggers partner `order.created` webhook if integration is enabled.

### Customer lookup (manual order form)

```http
GET /api/v1/orders/manual/customer-lookup?phone=%2B971501234567
```

**Response** `200 OK`

```json
{
  "name": "Fatima Hassan",
  "last_address": {
    "apt_room": "1204",
    "building": "Marina Tower",
    "receiver_name": "Fatima",
    "notes": "Gate 2"
  }
}
```

`404` if customer not found for this restaurant.

### Advance kitchen status

```http
POST /api/v1/orders/{order_id}/advance
```

Moves order one step: `confirmed → preparing → ready`. Delivers customer WhatsApp status ping immediately.

**Response** `200 OK` — `OrderOut`

**Errors:** `404` not found, `422` illegal transition

### Cancel order

```http
POST /api/v1/orders/{order_id}/cancel
```

**Request** (optional) — `CancelOrderIn`

```json
{ "reason": "Customer requested cancel" }
```

Manager cancel is legal through `arriving`. Does **not** resell food (unlike customer cancel during cooking).

**Response** `200 OK` — `OrderOut`

### Reassign rider

```http
POST /api/v1/orders/{order_id}/reassign
```

**Request** — `ReassignOrderIn`

```json
{ "rider_id": 3 }
```

Only for `assigned` orders. `404` if order/rider not found; `422` if not assignable.

### Delete order (admin cleanup)

```http
DELETE /api/v1/orders/{order_id}
```

Hard delete — for test data only. Use `/cancel` for operational cancellation. Returns `204 No Content`.

---

## Customers

Prefix: `/api/v1/ordering/customers` — **JWT** required.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `` | List customers (`?q=`, `limit`, `offset`) |
| `GET` | `/{customer_id}` | Full profile + addresses + recent orders |
| `PATCH` | `/{customer_id}` | Update name, phone, marketing opt-in |
| `POST` | `/{customer_id}/loyalty-tier` | Set/unlock loyalty tier |
| `PATCH` | `/{customer_id}/addresses/{address_id}` | Edit address |
| `DELETE` | `/{customer_id}/addresses/{address_id}` | Delete address (409 if linked to open order) |
| `DELETE` | `/{customer_id}` | Delete customer (409 if has orders) |

**CustomerListOut**

```json
{
  "items": [
    {
      "id": 15,
      "name": "Fatima",
      "phone": "+971501234567",
      "total_orders": 12,
      "total_spend": "840.00",
      "first_order_at": "2026-01-15T12:00:00+00:00",
      "last_order_at": "2026-07-01T18:30:00+00:00",
      "marketing_opted_in": true
    }
  ],
  "limit": 50,
  "offset": 0
}
```

**Loyalty tier override**

```json
{ "tier": "gold" }
```

or

```json
{ "unlock": true }
```

---

## Inbound webhooks (Meta → platform)

These endpoints receive WhatsApp Cloud API events. Meta (or the local simulator) calls them — not the manager dashboard.

### Verification handshake (GET)

```http
GET /webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<challenge>
```

| Query param | Description |
|-------------|-------------|
| `hub.mode` | Must be `subscribe` |
| `hub.verify_token` | Must match `APP_WA_VERIFY_TOKEN` |
| `hub.challenge` | Echoed back on success |

**Response** `200 OK` — plain text challenge string

**Response** `403` — invalid verify token

### Receive events (POST)

```http
POST /webhooks/whatsapp
Content-Type: application/json
X-Hub-Signature-256: sha256=<hmac>   (required in cloud mode)
```

**Response** (always, after processing)

```json
{ "status": "ok" }
```

#### Signature verification (cloud mode only)

When `APP_WHATSAPP_PROVIDER=cloud`, the platform verifies:

```
HMAC-SHA256(raw_body_bytes, APP_WA_APP_SECRET) == X-Hub-Signature-256 header
```

Mock/simulator mode skips signature checks.

#### Inbound payload envelope (Meta format)

```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "WABA_ID",
      "changes": [
        {
          "field": "messages",
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "97141234567",
              "phone_number_id": "123456789012345"
            },
            "contacts": [
              { "profile": { "name": "Fatima" }, "wa_id": "971501234567" }
            ],
            "messages": [ ]
          }
        }
      ]
    }
  ]
}
```

#### Message types handled

| `type` | Routed to | Normalized payload |
|--------|-----------|-------------------|
| `text` | Conversation engine | `{ "text": "..." }` |
| `interactive` (button/list reply) | Conversation engine | `{ "id": "...", "title": "..." }` |
| `button` (template quick-reply) | Conversation engine | `{ "id": "...", "title": "..." }` |
| `location` | Conversation engine | `{ "latitude", "longitude", "is_live"? }` |
| `image` / `document` / `video` / `audio` | Conversation engine | Media IDs + mime |
| `order` (catalog cart) | Catalog order handler | Product line items |
| `reaction` | Dropped (no processing) | — |

**Sample: inbound text message**

```json
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "changes": [
        {
          "field": "messages",
          "value": {
            "metadata": {
              "display_phone_number": "97141234567",
              "phone_number_id": "123456789012345"
            },
            "messages": [
              {
                "id": "wamid.HBgLM...",
                "from": "971501234567",
                "timestamp": "1717660800",
                "type": "text",
                "text": { "body": "I want 2 chicken biryani" }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

**Sample: inbound button reply**

```json
{
  "messages": [
    {
      "id": "wamid.btn001",
      "from": "971509876543",
      "timestamp": "1717660900",
      "type": "interactive",
      "interactive": {
        "type": "button_reply",
        "button_reply": {
          "id": "confirm_order",
          "title": "Confirm"
        }
      }
    }
  ]
}
```

**Sample: delivery status event** (processed separately; does not create orders)

```json
{
  "entry": [
    {
      "changes": [
        {
          "value": {
            "metadata": { "phone_number_id": "123456789012345" },
            "statuses": [
              {
                "id": "wamid.outbound123",
                "status": "failed",
                "timestamp": "1717661000",
                "recipient_id": "971501234567",
                "errors": [{ "code": 131047, "title": "Re-engagement message" }]
              }
            ]
          }
        }
      ]
    }
  ]
}
```

Failed outbound messages mark the corresponding outbox row as `dead`.

#### Idempotency

Each inbound message `id` (`wamid.*`) is inserted into `webhook_events` before processing. Duplicate deliveries are skipped silently.

#### Rate limiting

Webhook POST is rate-limited per `rate_limit_webhook` settings.

---

## Outbound webhooks (platform → POS)

When partner integration is enabled, the platform **POSTs** JSON to `partner_webhook_url`.

Full event catalog: `docs/partners/webhook-events.md`

### Delivery headers

| Header | Value |
|--------|-------|
| `Content-Type` | `application/json` |
| `X-Partner-Event` | e.g. `order.created` |
| `X-Partner-Idempotency-Key` | Same as body `idempotency_key` |
| `X-Partner-Signature` | `sha256=<hmac_hex>` of raw body |

POS must verify HMAC, return **2xx within 5 seconds**, and deduplicate on `idempotency_key`.

### Envelope (all events)

```json
{
  "event": "order.created",
  "idempotency_key": "pos-order-created-42",
  "timestamp": "2026-07-07T10:00:00+00:00",
  "data": { }
}
```

### Event types

| Event | When fired |
|-------|------------|
| `integration.ping` | Manager test button |
| `order.created` | Customer confirms order |
| `order.rider_assigned` | Dispatch assigns rider |
| `order.picked_up` | Rider taps pickup |
| `order.delivered` | Rider marks delivered |
| `order.late` | SLA breach (40 min customer promise) |

### `order.created` data shape

```json
{
  "order_id": 42,
  "order_number": "R1-0042",
  "pos_store_id": "CRT-DXB-014",
  "status": "confirmed",
  "customer": {
    "id": 15,
    "name": "Fatima",
    "phone": "+971501234567"
  },
  "items": [
    {
      "dish_number": 110,
      "name": "Chicken Biryani",
      "variant_name": null,
      "qty": 2,
      "price": 22.0,
      "notes": "extra spicy"
    }
  ],
  "additional_details": null,
  "address": {
    "room_apartment": "1204",
    "building": "Marina Tower",
    "receiver_name": "Fatima",
    "additional_details": "Gate 2",
    "latitude": 25.081,
    "longitude": 55.139
  },
  "subtotal": 44.0,
  "delivery_fee": 10.0,
  "wallet_applied": 0.0,
  "total": 54.0,
  "cod_due": 54.0,
  "payment": "COD",
  "distance_km": 4.2,
  "promised_eta": "2026-07-07T10:40:00+00:00",
  "sla_deadline": "2026-07-07T10:40:00+00:00",
  "created_at": "2026-07-07T10:00:00+00:00"
}
```

### Signature verification (POS receiver)

```python
import hashlib, hmac

def verify(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

---

## Partner API (POS integration)

Prefix: `/api/v1/partner` — **`X-API-Key`** required.

### Customers (incremental sync)

```http
GET /api/v1/partner/customers?updated_since=2026-07-01T00:00:00Z&limit=100&offset=0
```

**Response**

```json
{
  "items": [
    {
      "id": 15,
      "name": "Fatima",
      "phone": "+971501234567",
      "total_orders": 12,
      "total_spend": "840.00",
      "first_order_at": "2026-01-15T12:00:00+00:00",
      "last_order_at": "2026-07-01T18:30:00+00:00",
      "created_at": "2026-01-15T12:00:00+00:00",
      "updated_at": "2026-07-07T09:00:00+00:00"
    }
  ],
  "limit": 100,
  "offset": 0,
  "next_updated_since": "2026-07-07T09:00:00+00:00"
}
```

### Orders

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/orders` | Poll new orders (backup when webhooks fail) |
| `GET` | `/orders/{order_id}` | Single order |
| `POST` | `/orders/{order_id}/ack` | POS stores its order ID |
| `POST` | `/orders/{order_id}/status` | Kitchen status update |
| `GET` | `/orders/{order_id}/delivery` | Rider, ETA, COD status |

**List query params**

| Param | Default | Description |
|-------|---------|-------------|
| `status` | `confirmed` | Filter status |
| `since` | — | ISO datetime |
| `unacked_only` | `true` | Only orders POS hasn't acked |
| `limit` | 50 | max 500 |
| `offset` | 0 | |

**Ack request**

```json
{ "pos_order_id": "POS-2026-78901" }
```

**Kitchen status update**

```json
{
  "status": "preparing",
  "reason": null
}
```

Allowed POS statuses: `accepted` | `preparing` | `ready` | `cancelled`

**Status response**

```json
{
  "order_id": 42,
  "order_number": "R1-0042",
  "status": "preparing",
  "rider_assigned": false
}
```

**Delivery poll response**

```json
{
  "order_id": 42,
  "order_number": "R1-0042",
  "pos_store_id": "CRT-DXB-014",
  "pos_order_id": "POS-2026-78901",
  "status": "picked_up",
  "rider": {
    "id": 3,
    "name": "Ahmed",
    "phone": "+971509876543"
  },
  "batch_id": 8,
  "eta_minutes": 12,
  "promised_eta": "2026-07-07T10:40:00+00:00",
  "delivered_at": null,
  "late": false,
  "cod_due": 54.0,
  "cod_collected": null
}
```

### Menu sync (POS → platform)

| Method | Path | Description |
|--------|------|-------------|
| `PUT` | `/menu/items` | Bulk upsert by `pos_id` |
| `PATCH` | `/menu/items/{pos_id}` | Fast sold-out / price patch |
| `POST` | `/events/menu-changed` | Queue full POS pull |
| `GET` | `/menu/sync-status` | Last sync metadata |

**Bulk upsert**

```json
{
  "items": [
    {
      "pos_id": "CRT-110",
      "dish_number": 110,
      "name": "Chicken Biryani",
      "price": 22.0,
      "category": "Rice",
      "description": "Fragrant basmati",
      "is_available": true
    }
  ]
}
```

Query: `?publish=true` (default) pushes to Meta catalogue after upsert.

### Riders & chat

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/riders` | Full rider roster |
| `GET` | `/riders/{rider_id}/location` | Latest GPS (rate-limited: 1/10s) |
| `GET` | `/conversations` | WhatsApp threads |
| `GET` | `/conversations/{id}/messages` | Message history |
| `POST` | `/conversations/{id}/messages` | POS agent reply |
| `POST` | `/conversations/{id}/takeover` | Bot takeover toggle |
| `GET` | `/store` | Store identity + integration flags |

**Send message from POS**

```json
{
  "text": "Your order is almost ready!",
  "take_over": true
}
```

### Partner integration config (manager JWT)

Prefix: `/api/v1/partner-integration`

| Method | Path | Auth |
|--------|------|------|
| `GET` | `/config` | JWT |
| `PATCH` | `/config` | JWT |
| `GET` | `/health` | JWT |
| `POST` | `/webhooks/test` | JWT |

**Config patch**

```json
{
  "partner_enabled": true,
  "partner_webhook_url": "https://pos.example.com/hooks/whatsapp",
  "partner_webhook_secret": "whsec_...",
  "pos_store_id": "CRT-DXB-014",
  "pos_order_push_mode": "webhook"
}
```

### API key management (manager JWT)

Prefix: `/api/v1/api-keys`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `` | Create key (secret shown once) |
| `GET` | `` | List keys (prefix only) |
| `DELETE` | `/{key_id}` | Revoke |

---

## Menu

Prefix: `/api/v1` — **JWT** required.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/menus/blank` | Ensure empty active menu exists |
| `POST` | `/menus` | Upload menu files (multipart) → AI extraction |
| `GET` | `/menus/active` | Current active menu + dishes |
| `GET` | `/menus/{menu_id}` | Specific menu version |
| `POST` | `/menus/{menu_id}/activate` | Activate draft menu |
| `POST` | `/menus/{menu_id}/reextract` | Re-run AI extraction |
| `GET` | `/menu/unified` | Dishes + catalogue link status |
| `POST` | `/dishes/image` | Upload dish photo |
| `POST` | `/menus/{menu_id}/dishes` | Add dish |
| `PATCH` | `/menus/{menu_id}/dishes/{dish_id}` | Edit dish |
| `DELETE` | `/menus/{menu_id}/dishes/{dish_id}` | Remove/archive dish |
| `PATCH` | `/dishes/{dish_id}/availability` | Sold-out toggle |
| `PATCH` | `/dishes/{dish_id}/whatsapp` | Catalogue presence on/off |

**DishIn** (create)

```json
{
  "dish_number": 110,
  "name": "Chicken Biryani",
  "price_aed": "22.00",
  "category": "Rice",
  "description": "Fragrant basmati with tender chicken",
  "is_available": true,
  "whatsapp_enabled": true,
  "variants": [
    { "name": "2 serve", "price_aed": "18.00" },
    { "name": "4 serve", "price_aed": "32.00" }
  ]
}
```

**DishOut** (response)

```json
{
  "id": 88,
  "dish_number": 110,
  "name": "Chicken Biryani",
  "price_aed": "22.00",
  "category": "Rice",
  "description": "Fragrant basmati with tender chicken",
  "is_available": true,
  "catalog_retailer_id": "dish-88-110",
  "pos_product_id": null,
  "image_url": "/media/dishes/1/abc.jpg",
  "sale_price_aed": null,
  "fb_product_category": null,
  "condition": "new",
  "meta_status": "active",
  "brand": null,
  "whatsapp_enabled": true,
  "variants": []
}
```

**Menu upload** — `multipart/form-data`, field `files` (max 5 MB each). Returns `MenuWithDiffOut` with optional `diff_vs_active`.

---

## Catalog

Prefix: `/api/v1/catalog` — **JWT** required.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/send` | Send catalogue cards to a phone (testing) |
| `GET` | `/products` | Synced Meta catalogue mirror |
| `POST` | `/sync` | Pull from Meta → local |
| `POST` | `/push` | Push local dishes → Meta |
| `POST` | `/sync-full` | Bidirectional sync |

**Send catalogue**

```json
{ "phone": "+971501234567" }
```

**Response**

```json
{ "status": "sent", "phone": "+971501234567" }
```

**CatalogProductOut**

```json
{
  "id": 201,
  "retailer_id": "dish-88-110",
  "name": "Chicken Biryani",
  "price_aed": 22.0,
  "currency": "AED",
  "availability": "in stock",
  "image_url": "https://...",
  "category": "Rice",
  "is_active": true,
  "synced_at": "2026-07-07T08:00:00+00:00"
}
```

---

## Conversations

Prefix: `/api/v1/conversations` — **JWT** required (except `/cart-tick`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `` | List WhatsApp threads |
| `GET` | `/{id}/messages` | Message history |
| `GET` | `/{id}/context` | Customer wallet + recent orders |
| `POST` | `/{id}/messages` | Manager sends reply |
| `POST` | `/{id}/takeover` | Toggle manual takeover |
| `POST` | `/{id}/reset` | Reset conversation state |
| `GET` | `/{id}/messages/{msg_id}/media` | Stream attachment |
| `GET` | `/delivery-failures` | Dead outbound messages |

**Send message**

```json
{ "text": "We'll add extra raita for you." }
```

**DashboardMessageOut**

```json
{
  "id": 501,
  "direction": "outbound",
  "type": "text",
  "payload": { "body": "We'll add extra raita for you." },
  "ts": 1720339200
}
```

**Cart tick** (cron only)

```http
POST /api/v1/conversations/cart-tick
X-Tick-Secret: <APP_MARKETING_TICK_SECRET>
```

---

## Dispatch & tracking

### Dispatch (manager JWT)

Prefix: `/api/v1/dispatch`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/trigger` | Run dispatch engine manually |
| `GET` | `/kpis` | Batch rate, avg stops, fallback % |
| `GET` | `/live-map` | Active batches + SLA rings |
| `GET` | `/assignments` | Assignment explainability rows |

**Trigger response**

```json
{
  "assigned": 2,
  "unassigned": 0,
  "needs_retry": false
}
```

### Live tracking (mixed auth)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/orders/{id}/tracking/start` | JWT | Start live location session |
| `POST` | `/api/v1/orders/{id}/location` | Rider token | Report GPS ping |
| `GET` | `/api/v1/orders/{id}/location` | JWT | Latest location |
| `POST` | `/api/v1/orders/{id}/tracking/stop` | JWT | End session |
| `GET` | `/api/v1/track/{tracking_token}` | Public | Customer tracking page data |
| `GET` | `/api/v1/track/{tracking_token}/location` | Public | Customer map pin |
| `GET` | `/api/v1/rider-track/{rider_token}` | Public | Rider share link |

---

## Rider app

Prefix: `/api/v1/rider-app` — rider session token (from pairing).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/info` | App config + APK link |
| `POST` | `/pair` | Exchange pairing code for session |
| `GET` | `/me` | Rider profile |
| `POST` | `/duty` | On/off duty toggle |
| `POST` | `/push-token` | Register FCM token |
| `GET` | `/orders` | Current delivery run |
| `POST` | `/orders/pickup` | Mark batch picked up |
| `POST` | `/orders/{id}/delivered` | Mark delivered + COD |
| `POST` | `/location` | Report GPS |

**Pair request**

```json
{
  "code": "482913",
  "device_id": "uuid-device-123"
}
```

---

## Wallet, coupons, tickets, COD

All require **JWT**.

### Wallet — `/api/v1/wallet`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/{customer_id}` | Balance |
| `GET` | `/{customer_id}/entries` | Ledger history |
| `POST` | `/{customer_id}/credit` | Manual credit |
| `POST` | `/{customer_id}/debit` | Manual debit |

**Credit/debit body**

```json
{
  "amount_aed": "25.00",
  "reason": "Goodwill gesture — late delivery"
}
```

**WalletBalanceOut**

```json
{
  "customer_id": 15,
  "balance_aed": "25.00",
  "available_aed": "25.00",
  "status": "active"
}
```

### Coupons — `/api/v1/coupons`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `` | Create campaign coupon |
| `POST` | `/issue` | Issue to specific customer |
| `GET` | `` | List (`?phone=` for customer coupons) |
| `POST` | `/{code}/pause` | Kill-switch |

**Create coupon**

```json
{
  "discount_type": "fixed",
  "discount_value": "10.00",
  "kind": "multi_use",
  "min_order_aed": "50.00",
  "code": "RAMADAN10",
  "expires_at": "2026-04-15T23:59:59+00:00"
}
```

### Tickets — `/api/v1/tickets`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `` | List (`?status=`, `?phone=`) |
| `GET` | `/{ticket_id}` | Detail |
| `POST` | `/{ticket_id}/resolve` | Resolve with action |

**Resolve**

```json
{
  "action": "wallet_refund",
  "note": "Wrong items delivered",
  "amount": "30.00"
}
```

Actions: `wallet_refund` | `replacement` | `create_replacement` | `resolved_no_action`

### COD — `/api/v1/cod`

```http
GET /api/v1/cod/shift/{rider_id}
```

```json
{
  "rider_id": 3,
  "collections": [
    {
      "order_id": 42,
      "amount_aed": "54.00",
      "collected_at": "2026-07-07T10:35:00+00:00"
    }
  ]
}
```

---

## Marketing

Prefix: `/api/v1/marketing` — **JWT** required.

Key endpoint groups:

| Group | Paths |
|-------|-------|
| Segments | `POST /segments`, `GET /segments`, `POST /segments/compile`, `POST /segments/preview`, `DELETE /segments/{id}` |
| Templates | `POST /templates`, `GET /templates`, `POST /templates/draft`, `POST /templates/{id}/submit`, `POST /templates/{id}/refresh`, `POST /templates/{id}/fix`, `DELETE /templates/{id}` |
| Campaigns | `POST /campaigns`, `GET /campaigns`, `DELETE /campaigns/{id}`, `PATCH /campaigns/{id}/schedule`, `GET /campaigns/{id}/stats` |
| Broadcast | `POST /campaigns/broadcast` |
| Automations | `GET /automations`, `PATCH /automations/{preset_key}` |
| Cron | `POST /tick` (requires `X-Tick-Secret`) |
| Media | `GET /media/{path}` (public image serve for Meta) |

**Broadcast request** (excerpt)

```json
{
  "template_id": 5,
  "segment_id": 2,
  "send_at": null
}
```

---

## Predictions & POS sync

### Predictions — `/api/v1/predictions` (JWT)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/latest` | Latest demand forecast |
| `GET` | `/runs` | Historical run list |
| `GET` | `/prep-ahead` | Prep-ahead dish suggestions |
| `POST` | `/overrides` | Manager override |

### POS menu pull — `/api/v1/pos` (JWT)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/config` | POS connector config |
| `PATCH` | `/config` | Update config |
| `POST` | `/sync` | Queue async menu pull (`202`) |
| `POST` | `/sync/inline` | Synchronous pull |
| `GET` | `/sync/status` | Job status |

---

## Order status reference

| Status | Meaning |
|--------|---------|
| `draft` | Cart in progress (WhatsApp) |
| `pending_confirmation` | Awaiting customer confirm |
| `confirmed` | Placed — kitchen queue |
| `preparing` | Kitchen started |
| `ready` | Ready for rider pickup |
| `assigned` | Rider assigned |
| `picked_up` | Rider has food |
| `arriving` | Rider near customer |
| `delivered` | Complete |
| `cancelled` | Cancelled (terminal) |
| `undeliverable` | Could not deliver |
| `on_resale` | Cancelled after cooking — offered to next customer |
| `resold` | Resale copy sold |
| `written_off` | Resale expired |

### Business rules (quick reference)

- **Payment:** COD only
- **Delivery radius:** max 10 km
- **Fee tiers:** ≤3 km free / 3–5 km AED 5 / >5 km AED 10 (configurable per restaurant)
- **Customer SLA:** 40 minutes promised; internal target 30 min
- **Modification:** allowed only before `ready`; restarts SLA on confirm
- **Late delivery:** automatic coupon (except weather delays disclosed at order time)

---

## Quick start examples

### 1. Manager creates a manual order

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"manager@restaurant.ae","password":"hunter2!"}' \
  | jq -r .access_token)

# Create order
curl -s -X POST http://localhost:8000/api/v1/orders/manual \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_phone": "+971501234567",
    "customer_name": "Fatima",
    "items": [{"dish_id": 88, "qty": 2}],
    "address": {
      "apt_room": "1204",
      "building": "Marina Tower",
      "receiver_name": "Fatima"
    },
    "delivery_fee_aed": "10.00"
  }' | jq .
```

### 2. POS polls new orders

```bash
curl -s "http://localhost:8000/api/v1/partner/orders?unacked_only=true" \
  -H "X-API-Key: rwsk_your_key_here" | jq .
```

### 3. POS acknowledges order

```bash
curl -s -X POST http://localhost:8000/api/v1/partner/orders/42/ack \
  -H "X-API-Key: rwsk_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"pos_order_id": "POS-78901"}' | jq .
```

### 4. Simulate inbound WhatsApp message (mock mode)

```bash
curl -s -X POST http://localhost:8000/webhooks/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "changes": [{
        "field": "messages",
        "value": {
          "metadata": {
            "display_phone_number": "97141234567",
            "phone_number_id": "111"
          },
          "messages": [{
            "id": "wamid.test001",
            "from": "971501234567",
            "timestamp": "1717660800",
            "type": "text",
            "text": {"body": "menu"}
          }]
        }
      }]
    }]
  }'
```

---

*Generated from live route and schema definitions in `src/app/`. For partner webhook details see `docs/partners/webhook-events.md`. For interactive exploration use `/docs` (Swagger UI).*