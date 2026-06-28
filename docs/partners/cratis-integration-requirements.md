# Cratis × WhatsApp Ordering Platform — Integration Requirements

**Purpose:** This document lists everything **we need from Cratis** to embed our
WhatsApp ordering + delivery engine into the Cratis POS. Cratis does **not** use our
manager dashboard — the integration is **API-only**: Cratis drives everything from
inside its own POS using an API key we issue.

**Audience:** Cratis engineering / integration team.
**Status:** Draft for review — items marked **[DECISION]** need a joint answer.
**Last updated:** 2026-06-27

**Commercial context (from the Cratis × CatalystIQ deck):** Cratis bills the restaurant
a **monthly subscription per restaurant** and we **share the recurring revenue**; the
service lives **inside the Cratis POS under the Cratis brand**. The restaurant uses its
**own WhatsApp number** for ordering + its **own delivery**, with a monthly **marketing
layer** (promo images/short videos). Two engineering consequences fall out of this and
are captured below: we need a **subscription/active-store signal** (§5a — Cratis owns
billing, so Cratis tells us which stores are live) and a clear answer on **who owns the
menu** (§6 — POS sync vs. our "menu digitized in a day" capability).

---

## 1. How the integration works (the model)

We are the **ordering + delivery brain on WhatsApp**. Cratis is the **source of truth
for menu and the destination for orders** (kitchen, billing, accounting).

```
            MENU (items, prices, availability)
   Cratis POS  ───────────────────────────────►  Our Platform ──► WhatsApp customer (AI bot)
   (source of truth)                                   │
            ◄───────────────────────────────────────────┘
            ORDERS placed on WhatsApp  +  live status (preparing/ready/out-for-delivery/delivered)
```

So data flows **both ways**:

| Direction | What flows | Why |
|---|---|---|
| **Cratis → Us** | Menu (items, prices, modifiers, availability) | The WhatsApp bot can only sell what Cratis tells us exists |
| **Cratis → Us** | Kitchen status (accepted / preparing / ready) | "Ready" is what triggers our rider dispatch |
| **Us → Cratis** | Orders placed on WhatsApp | So they appear in the POS / kitchen / billing |
| **Us → Cratis** | Delivery status (rider assigned, picked up, delivered, late) | So the POS shows the full order lifecycle |

**What we already provide today:** API-key issuance + revocation, and a read-only
partner data API (`/api/v1/partner/...`). Everything below is what we need from Cratis
to complete the loop.

---

## 2. What we need from Cratis — summary checklist

- [ ] **2 technical contacts** + a shared Slack/Teams channel
- [ ] **Sandbox + production base URLs** for the Cratis API
- [ ] **Auth method** for us to call Cratis (API key / OAuth client credentials) **[DECISION]**
- [ ] **Store/branch identifiers** to map to our `restaurant_id`
- [ ] **Menu**: data + a sync mechanism (webhook push or pull endpoint) **[DECISION]**
- [ ] **Order intake**: an endpoint on Cratis to receive WhatsApp orders **[DECISION]**
- [ ] **Order status webhook** from Cratis → us (kitchen events)
- [ ] **Field mapping** confirmation against the tables in §6–§8
- [ ] **Currency / tax / timezone** confirmation
- [ ] **Rate limits, ret/retry, idempotency** expectations
- [ ] **Go-live plan**: test store, sample data, UAT sign-off

---

## 3. Access, environments & contacts

| We need | Detail |
|---|---|
| **Technical contacts** | 2 named engineers + escalation path |
| **Shared channel** | Slack/Teams/email DL for integration questions |
| **Environments** | Separate **sandbox** and **production** base URLs |
| **API documentation** | OpenAPI/Swagger or equivalent for the Cratis endpoints we will call |
| **Test store** | A non-live Cratis store with realistic menu we can integrate against end-to-end |

---

## 4. Authentication & security **[DECISION]**

There are **two auth directions** — please confirm both:

### 4a. Cratis → Us (you calling our API)
- We **issue you an API key** per store (you already requested this). It is shown
  **once** at creation and sent as header `X-API-Key: <key>`.
- Keys are **scoped to one restaurant/store** and can be revoked.

### 4b. Us → Cratis (us calling your API / receiving your webhooks)
We need credentials to push orders into Cratis and to verify webhooks **you** send us.
Please confirm which you support:
- **Option A — API key**: you give us a key/secret per store; we send it as a header.
- **Option B — OAuth 2.0 client credentials**: you give us `client_id`/`client_secret`
  + token URL; we fetch bearer tokens.
- **Webhook signing**: how do you sign webhooks to us (HMAC shared secret in a header)?
  We will sign ours to you the same way — tell us your preference.

**Security questions:**
- IP allow-listing required on either side?
- TLS version / certificate requirements?
- Data-retention / PII constraints on customer name + phone + address?

---

## 5. Store / branch provisioning (identity mapping)

Every record in our system is scoped to a `restaurant_id`. We need to map that to your
store identity.

| We need from Cratis | Example |
|---|---|
| **Cratis store/branch ID** (stable, per location) | `cartis_store_id: "CRT-DXB-014"` |
| **Store display name** | "Biryani House — Al Barsha" |
| **Store timezone** | `Asia/Dubai` |
| **Store currency** | `AED` (see §9) |
| **Store contact phone** (the WhatsApp number routing, if known) | `+9714…` |
| One mapping row **per store** being onboarded | — |

We will return our `restaurant_id` for each, so both sides can cross-reference.

---

## 6. MENU — what we need (Cratis → Us) **[DECISION on sync method]**

The WhatsApp bot sells **only** what Cratis sends. Our menu model is **dish-number +
price driven** and enforces a few hard rules (see notes).

### 6a. Sync mechanism — pick one
- **Option A — Cratis pushes** to our menu-ingest endpoint on every menu change (preferred; real-time).
- **Option B — We pull** a Cratis "get menu" endpoint on a schedule + on demand.
- Either way we need **incremental change signals** (an `updated_at` per item) so we
  don't re-sync the whole menu each time.

### 6b. Required fields per menu item

| Field | Required? | Our field | Notes |
|---|---|---|---|
| Cratis item ID (stable) | ✅ | external ref | So updates map to the same dish |
| **Dish number** | ✅ | `dish_number` | **Mandatory** — menu can't go live if any item lacks a number |
| **Name** | ✅ | `name` | |
| **Price** | ✅ | `price_aed` | **Mandatory** — decimal, 2 dp. No item activates without a price |
| Category | ⬜ | `category` | "Biryani", "Drinks"… for grouping |
| Description | ⬜ | `description` | Customer-facing. **Max 3 lines, must NOT contain price** (our rule) |
| **Availability** (in/out of stock) | ✅ | `is_available` | Drives "sold out" in the bot in real time |
| Variants / sizes | ⬜ | `variants[]` | e.g. Small/Large with per-variant price — see 6c |
| Prep time (minutes) | ⬜ | `prep_minutes` | Improves our SLA/kitchen countdown accuracy |

### 6c. Variants / modifiers **[DECISION]**
Our model supports **named variants with their own price** (`variants: [{name, price}]`).
We need to know how Cratis represents:
- **Sizes** (Small/Medium/Large)
- **Add-ons / modifiers** (extra cheese, no onion) — are these priced? required/optional? grouped?
- **Combos / meals**

Please share a **sample menu payload** (1–2 real items incl. a variant and a modifier)
so we can lock the mapping.

**Our hard rules (so Cratis data must support them):** every sellable item needs a
**number** and a **price**; customer-facing descriptions carry **no price**; COD only.

---

## 7. ORDERS — what we need (Us → Cratis) **[DECISION on intake]**

When a customer completes an order on WhatsApp, it must land in Cratis.

### 7a. Intake mechanism — pick one
- **Option A — We POST the order** to a Cratis "create order" endpoint (preferred).
- **Option B — Cratis polls** our partner order API for new orders.

### 7b. Fields we will send per order

| Field | Our source | Notes |
|---|---|---|
| Our order ID + **order number** | `order_number` e.g. `R1-0042` | Stable reference |
| Cratis store ID | mapping (§5) | Which branch |
| Customer name | `Customer.name` | |
| Customer phone | `Customer.phone` | |
| **Line items** | `OrderItem[]` | `dish_number`, `dish_name`, `variant_name`, `qty`, `price`, `notes` |
| Item notes / special requests | `OrderItem.notes` | Verbatim ("no onion") |
| Subtotal | `subtotal` | |
| Delivery fee | `delivery_fee_aed` | Tiered: ≤3 km free / 3–5 km 5 / >5 km 10 (AED) |
| **Total** | `total` | |
| Payment method | — | **COD only** (today) |
| Delivery address | `CustomerAddress` | building, room/apt, receiver name, lat/lng, extra details |
| Promised ETA / SLA deadline | `promised_eta`, `sla_deadline` | Customer told 40 min |
| Order placed time | `created_at` | UTC |

**What we need Cratis to tell us back on intake:** the **Cratis order ID** (so we can
correlate status updates), and accept/reject + reason.

### 7c. Order modifications & cancellations **[DECISION]**
- Customers can modify an order **only before it's `ready`**. How should we send a
  **modification** to Cratis — replace the whole order, or send a delta?
- How does Cratis represent **cancellation** and **auto-resale** of cancelled-after-cooking orders?

---

## 8. ORDER STATUS — what we need (Cratis → Us, webhook)

Our delivery engine is driven by kitchen status. We need a **webhook from Cratis** on
every status change, OR a pollable status endpoint **[DECISION]**.

### 8a. The status events we need from Cratis
| Cratis event | Triggers on our side |
|---|---|
| Order **accepted** by store | Confirm to customer on WhatsApp |
| **Preparing** / in kitchen | Start prep countdown |
| **Ready** | **Triggers rider dispatch + batching** (critical) |
| Rejected / cancelled by store | Notify customer, release |

We map Cratis statuses onto our order FSM. We need the **exact list of Cratis status
values** and their meaning to build that mapping (no guessing — we never invent statuses).

### 8b. Status we will send back to Cratis
`rider_assigned → picked_up → en_route → delivered`, plus `late` flag and
auto-coupon issuance on late delivery (except disclosed weather delays).

---

## 9. Money, tax, time, locale

| Topic | Our assumption | Need Cratis to confirm |
|---|---|---|
| Currency | **AED** | Multi-currency? Per-store currency code? |
| Decimal precision | 2 dp | Match? |
| **Tax / VAT** | Not currently modelled per-line | Does Cratis send tax-inclusive or tax-exclusive prices? VAT line needed? **[DECISION]** |
| Delivery fee | We compute (distance tiers) | Should Cratis own the fee instead, or accept ours? **[DECISION]** |
| Timezone | `Asia/Dubai` (display), UTC (storage) | Confirm per store |
| Payment | **COD only** | Online payment via Cratis later? **[DECISION]** |

---

## 10. Reliability & operational contract

Please confirm Cratis's expectations / capabilities on:

| Topic | Question |
|---|---|
| **Idempotency** | Will Cratis honor an idempotency key on order create so retries don't duplicate? We will send one. |
| **Retries** | Your retry policy on webhooks to us? We retry with backoff + dead-letter. |
| **Rate limits** | Requests/sec limit on the Cratis API? |
| **Pagination** | For menu/order pulls — cursor or offset? (Ours uses `updated_since` + `limit/offset`.) |
| **Latency SLA** | Expected response time for order-create (affects how fast we can confirm to the customer). |
| **Error format** | Standard error body shape + status codes. |

---

## 11. Open decisions (consolidated)

1. **Menu sync** — Cratis pushes to us, or we pull? (§6a)
2. **Order intake** — we push to Cratis, or Cratis polls us? (§7a)
3. **Status updates** — Cratis webhook to us, or we poll? (§8)
4. **Auth direction Us→Cratis** — API key or OAuth? Webhook signing scheme? (§4b)
5. **Variants/modifiers/combos** representation. (§6c)
6. **Tax/VAT** handling + who owns the **delivery fee**. (§9)
7. **Modifications & cancellation** semantics. (§7c)
8. **Multi-currency / multi-store** scope for phase 1.

---

## 12. What we need to receive to start building

1. Cratis **API docs** (sandbox) + **base URLs**.
2. **Credentials** for us to call Cratis (§4b).
3. A **sample menu payload** (incl. a variant + a modifier).
4. A **sample order payload** Cratis expects (if we push) — or the spec of your
   order-create endpoint.
5. The **list of Cratis order status values**.
6. A **test store** with realistic data + 2 technical contacts.

Once we have 1–6 we can map fields, stand up the sandbox integration, and schedule a
joint UAT.

---

### Appendix A — Our partner API already live (for reference)
- `POST /api/v1/api-keys` · `GET /api/v1/api-keys` · `DELETE /api/v1/api-keys/{id}` — key management (manager-authed).
- `GET /api/v1/partner/customers?updated_since=…&limit=…&offset=…` — read-only customer pull (X-API-Key), incremental sync via `next_updated_since`.

New endpoints (menu ingest, order push/pull, status webhook) will be added to this
`/api/v1/partner` surface once §11 decisions are made.
