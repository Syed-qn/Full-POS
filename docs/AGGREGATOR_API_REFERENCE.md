# Aggregator API Reference (Talabat / Deliveroo / Careem / Uber Eats / Noon Food)

**Purpose:** Feeds `WS-AGGR` (wave 6, `docs/superpowers/plans/2026-07-08-pos-100pct-roadmap.md`) — real adapters replacing the current `MockAggregator` in `src/app/aggregators/factory.py`. Compiled 2026-07-08 via 5 parallel research agents against public docs + third-party integrator (Deliverect/Foodics) docs, since most aggregator partner APIs are gated behind manual approval.

**Confidence key:** ✅ confirmed from official docs · 🟡 confirmed via third-party integrator docs (Deliverect/Foodics), not the aggregator's own public docs · ⚠️ inferred/speculative, flagged explicitly below — do not build against these without verifying with real partner credentials.

---

## Cross-vendor summary

| | Public docs? | Direct API or middleware-only? | Accept SLA | Auth |
|---|---|---|---|---|
| **Uber Eats** | ✅ Full public portal (`developer.uber.com/docs/eats`) | Direct | 11.5 min (auto-robocall at 90s) | OAuth2 client_credentials |
| **Deliveroo** | ✅ Public reference (`api-docs.deliveroo.com`), payload examples gated | Direct | **10 min (7 min in UAE/Kuwait)** | OAuth2 client_credentials, 5-min token TTL |
| **Talabat** | 🟡 Partly public (Delivery Hero group portal), partner-gated | Direct (with manual credential approval) | ~30s ack window (inferred from Deliverect proxy) | Credential-based login → Bearer token; PGP key onboarding |
| **Careem Food** | ❌ No public docs found | **Middleware only** (Foodics/Deliverect/Restroworks/GetOrder) | Unknown | Unknown (OAuth-style inferred) |
| **Noon Food** | ❌ No public docs found | **Middleware only** (Deliverect/Foodics/GetOrder), twice-daily menu sync cycle | Unknown | Unknown |

**Build-order implication for WS-AGGR:** Uber Eats and Deliveroo are the only two with enough public detail to build a direct adapter today. Talabat needs partner approval before the exact payload schema is knowable. Careem and Noon Food realistically mean integrating through a middleware vendor (Deliverect is confirmed to bridge all 5) rather than 5 separate native adapters — worth a scoping decision before WS-AGGR starts (see "Open question" at the bottom).

---

## Uber Eats ✅ (best documented)

**1. Auth:** OAuth2 `client_credentials` grant. `POST https://auth.uber.com/oauth/v2/token` (sandbox: `sandbox-login.uber.com`) with `client_id`, `client_secret`, `grant_type=client_credentials`, `scope` (e.g. `"eats.store eats.order"`). Token valid 30 days; token-generation rate-limited to 100/hour (101st invalidates oldest). Scopes: `eats.order` (accept/deny/manage), `eats.store` (menu, POS data), `eats.store.status.write` (pause/unpause).

**2. Order webhook:** Event `orders.notification` — thin notification only:
```json
{
  "event_type": "orders.notification",
  "event_id": "c4d2261e-...",
  "event_time": 1427343990,
  "meta": { "resource_id": "153dd7f1-...", "status": "pos", "user_id": "89dd9741-..." },
  "resource_href": "https://api.uber.com/v2/eats/order/..."
}
```
Must ack with HTTP 200 empty body. Full order fetched separately via Get Order Details on `resource_id` (exact response schema not confirmed in this pass — verify against `developer.uber.com/docs/eats/references/api/order_suite` before coding).

**3. Order status:**
- Accept: `POST /v1/eats/orders/{order_id}/accept_pos_order` — body: `reason`, `pickup_time` (unix ts), `external_reference_id` (your POS order id), `fields_relayed` (object of bool flags), `order_pickup_instructions`. Returns `204`.
- Deny: `POST /v1/eats/orders/{order_id}/deny_pos_order` — exact payload fields unconfirmed, likely `reason`/`reason_code`.
- Ready-for-pickup: no confirmed dedicated endpoint — verify Order API Suite reference directly.

**4. Menu API:** `PUT /v2/eats/stores/{store_id}/menus` (scope `eats.store`) — `MenuConfiguration`: `menus[]`, `categories[]`, `items[]` (id, title, `price_info`, `tax_info`, `modifier_group_ids[]`, `suspension_info`), `modifier_groups[]`. `menu_type` enum: `MENU_TYPE_FULFILLMENT_DELIVERY/PICK_UP/DINE_IN`. Item-level toggle: `POST /v2/eats/stores/{store_id}/menus/items/{item_id}`.

**5. Store status:** `POST /v1/eats/stores/{store_id}/status` (scope `eats.store.status.write`), body sets `ONLINE`/`PAUSED`. `GET` variant to read.

**6. Webhook signature:** Header `X-Uber-Signature` = lowercase hex HMAC-SHA256 of raw body, keyed with client secret:
```python
digester = hmac.new(client_secret, webhook_body, hashlib.sha256)
signature = digester.hexdigest()
```

**7. Sandbox:** Create a "Testing" app in the Uber Developer Dashboard, API suite "Eats Marketplace." Sandbox auth `sandbox-login.uber.com`, API `test-api.uber.com` (must match, no mixing). Sandbox test stores must be requested from Uber Integration Tech Support (not self-provisioned).

**8. SLA/limits:** Accept/deny within **11.5 minutes** of webhook or order auto-cancels; robocall to store at 90s if unacknowledged. Webhook retry backoff ~10s/30s/60s/120s, capped at 7 attempts. Token-gen limited to 100/hr.

---

## Deliveroo ✅ (second-best documented)

**1. Auth:** OAuth2 client-credentials. `POST {AUTH_HOST}/oauth2/token`, AUTH_HOST = `auth-sandbox.developers.deliveroo.com` or `auth.developers.deliveroo.com`. Returns JWT, scope `https://api.deliveroo.net/api_access`, **expires in 5 minutes, no refresh token** — must regenerate every call cycle.

**2. Order webhook:** `POST https://api.developers.deliveroo.com/order/v1/deliveroo/order-events` (Deliveroo calls this on your registered URL). Events: `order.new`, `order.status_update`. Status lifecycle: `placed → accepted → rider_assigned → rider_arrived → rider_in_transit → rider_nearby → delivered` (also `rejected`, `confirmed` [scheduled only], `canceled`). Known top-level fields: `event`, `location_id`, `restaurant_acknowledged_at`, `order` (Order Body — item/customer/address schema gated behind partner login), `remake_details`, `status_log`, `start_preparing_at`. Retry window on error: 6 min (ASAP orders), 30 min (scheduled).

**3. Order status:** `PATCH https://api.developers.deliveroo.com/order/v1/orders/{order_id}` — body `{"status": "accepted|rejected|confirmed", "reject_reason": "closing_early|busy|ingredient_unavailable|other", "notes": null}`. 204 on success. **Rate-limited to 5 req/min/order.** Ready/collected reported via a separate "Prep Stages" endpoint (schema not crawlable in this pass).

**4. Menu API:** Asynchronous upload — submit payload, get `MATCH_EXISTING_MENU` if unchanged else async job + completion webhook. V3 supports large menus via presigned S3 URL → job → poll → download. Structure: items, modifiers, bundles, categories, mealtimes (time-scoped variants). Availability states: `available` (default) / `unavailable` (resets each morning) / `hidden` (persists). Replace-All (PUT, tolerant) vs Update-Individual (POST, strict). `brandId` required path param throughout.

**5. Site status:** `/site/v1/brands/{brandId}/sites/{siteId}` — open/close, opening hours, "days off" (holiday closures), workload/busy mode with configurable prep-time inflation.

**6. Webhook signature:** Headers `x-deliveroo-sequence-guid` + `x-deliveroo-hmac-sha256` present — implies HMAC-SHA256, exact signing recipe/canonical string not confirmed publicly.

**7. Sandbox:** `api-sandbox.developers.deliveroo.com` / `auth-sandbox.developers.deliveroo.com`, isolated from prod. Documented "Test Webhooks" simulator page exists.

**8. SLA/limits:** PATCH capped 5 req/min/order. **ASAP orders auto-reject if not accepted within 10 minutes — except UAE and Kuwait, where it's 7 minutes.** ⚠️ Directly relevant: this platform's SLA monitor (`sla/monitor.py`) already runs a 40-min customer/30-min internal clock — a Deliveroo adapter needs its own much-tighter 7-minute UAE accept-window enforcement, independent of the delivery SLA clock.

---

## Talabat 🟡 (partly public, partner-gated)

**1. Auth:** Credential-based: username + password + secret, OR PGP-keypair partner onboarding (generate keypair → submit credential request → Talabat approval → Login API returns Bearer access token). ⚠️ A separate "OAuth2 client_credentials + `/oauth/token`" flow also surfaced in search results — may be a different product tier (possibly the newer Delivery Hero "Global Business API"); confirm which applies before building.

**2. Order webhook:** Talabat/DH **pushes** (POST) to a vendor-registered plugin endpoint. Two flows: Indirect (pushed only after acceptance in Talabat's vendor app) vs Direct (pushed immediately, restaurant handles accept/reject + post-accept cancellations). Exact field-level schema not publicly retrievable — expect (⚠️ inferred by analogy with Deliverect's canonical schema): order id, channel order id, line items (name, qty, price, PLU/dish number), modifier sub-array, subtotal/total/delivery fee, customer name/phone, delivery address (street/area/geo), free-text notes.

**3. Order status:** POST endpoints on the Integration Middleware (not the plugin) — confirmed: `order_accepted`, `order_rejected` (requires enumerated reason code, `notes` optional). Separate documented POST endpoints for Accept / Reject / **Ready for pickup**. No confirmed "preparing"/"picked_up" partner-facing states.

**4. Menu API:** **Catalog Import API** — `PUT` "Submit Catalog", async (immediate validation ack, then platform-side propagation, optional completion webhook). Legacy "Menu Import API" is deprecated, closed to new integrations.

**5. Commission/settlement:** No API found — manager-portal/dashboard only, not partner-API surface (consistent across all 5 vendors researched).

**6. Webhook signature:** Not documented on Talabat/DH's own pages. 🟡 Deliverect (proxy layer) documents HMAC-SHA256 of raw payload, secret issued at onboarding (staging uses `channelLinkId` as secret) — this is Deliverect's scheme, not necessarily Talabat's native one.

**7. Sandbox:** Confirmed — `integration-middleware.stg.restaurant-partners.com`, documented IP whitelist (34.246.34.27, 18.202.142.208, 54.72.10.41). Test vendor credentials issued manually by a local Talabat rep, not self-service.

**8. SLA/limits:** Not explicitly published. 🟡 Deliverect states the receiving webhook must return HTTP 200/201 within **30 seconds** of the order POST — treat as the working assumption until partner docs confirm Talabat's own number.

---

## Careem Food ❌ (no public API — middleware-only path)

No self-serve developer portal found (`docs.careemnow.com` dead-ends; `developer.careem.com` unreachable and appears ride-hailing focused, not food). Integration is entirely manual-partner-onboarding or via a certified middleware vendor (Foodics, Deliverect, Restroworks, GetOrder).

- **Menu linking:** Foodics flow — create a POS menu group named "Careem," populate it, OAuth-style "Authorize Careem" button, then **manually** contact Careem to map POS branches to Careem branches (not self-service).
- **Order/status:** Deliverect confirms it pushes order webhooks and "sends automatic order status updates to Careem" but doesn't expose Careem's native schema or status enum.
- ⚠️ No evidence Careem Food currently runs on Uber's stack post-acquisition (Uber completed the Careem acquisition in 2020, but Careem operates as an independent brand/stack regionally per Uber's own newsroom statement) — do not assume Uber Eats' API applies to Careem.
- **Practical path:** apply via `careem.com/en-AE/restaurant-partner-signup/` for direct manual onboarding, or integrate via Deliverect/Foodics (whose own APIs are well-documented) and let them normalize the Careem feed.

---

## Noon Food ❌ (no public API — middleware-only path)

No public developer documentation found. `food-partners.noon.com` / `restaurant.noon.partners` / `welcome.noon.partners` are partner-facing marketing/login pages, unreachable for schema inspection (bot-protected or auth-gated).

- **Confirmed integrators:** Deliverect (two-way: order sync to POS + status callbacks + menu sync) and Foodics (native marketplace app).
- **Menu sync is NOT real-time** — Foodics documents a **fixed twice-daily sync window: 5:45 AM and 11:45 AM Arabian Standard Time** (2:45/8:45 UTC). Foodics' Noon integration is explicitly limited: no combo meals, price tags, discounts, or free/default modifiers; delivery order type only.
- ⚠️ Everything else (auth, webhook payload, status enum, SLA) is unconfirmed/inferred from generic marketplace-API shape — do not build against it without real Noon partner credentials.
- **Practical path:** same as Careem — integrate via Deliverect or Foodics rather than a native adapter.

---

## Recommendation for WS-AGGR implementation

1. **Build Uber Eats and Deliveroo first** — only two with enough public schema detail for a direct adapter (`src/app/aggregators/uber_eats.py`, `deliveroo.py` behind the existing `factory.py` port pattern). Deliveroo needs a **UAE-specific 7-minute accept SLA**, distinct from the platform's existing 40-min delivery SLA — do not conflate the two clocks.
2. **Talabat**: start partner onboarding (PGP key / credential request) in parallel — build the adapter skeleton now using the inferred payload shape, but gate it behind a feature flag until real partner docs/sandbox access confirm exact field names.
3. **Careem + Noon Food**: reconsider "real adapter per vendor" — realistic path is one middleware integration (Deliverect, which is confirmed to bridge all 5 vendors including Talabat/Deliveroo/Uber Eats too) rather than hand-building 2 more native adapters against undocumented APIs. This is a scoping question worth raising before WS-AGGR starts: build 5 native adapters, or build 3 native (Uber Eats/Deliveroo/Talabat) + 1 Deliverect-mediated adapter covering Careem+Noon (and optionally replacing the other 3 too, trading control for a single well-documented integration surface).
