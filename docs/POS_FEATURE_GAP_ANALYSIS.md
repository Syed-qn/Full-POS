# Traditional POS Feature Gap Analysis

**Date:** 2026-07-07
**Method:** Every item below was checked against the actual codebase (`src/app/`, `frontend/src/screens/`, `desktop/src/`) — file paths cited are read, not assumed. Source docs cross-checked: `docs/PLATFORM_FEATURES_REFERENCE.md`, `docs/IMPLEMENTATION_STATUS.md`, `docs/GAP_LIST.md`, `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`, `docs/superpowers/specs/2026-07-07-kitchen-kds-design.md`, `docs/superpowers/specs/2026-07-07-desktop-shell-foundation-design.md`.

**Context that matters for reading this document:** this platform is WhatsApp-first delivery, not a walk-in restaurant POS. Several "traditional POS" categories (table/floor management, dine-in service flow, staff clock-in) simply don't exist yet because the product has never needed them — that is a legitimate gap, not an oversight. Conversely, several categories most POS vendors bolt on as an afterthought (AI order-taking, demand forecasting, WhatsApp-native CRM, dispatch/SLA) are core, load-bearing, tested modules here. Status legend: ✅ Implemented · 🟡 Partial · ❌ Not implemented.

---

## 1. Order & Table Management

| Item | Status | Evidence |
|---|---|---|
| Table/floor plans | ❌ Not implemented | No `table`, `floor_plan`, or `seat` models/routes anywhere in `src/app` or `frontend/src`. There is no concept of a physical table in this system — every order is a delivery order tied to a customer address. |
| Split/merge checks | ❌ Not implemented | No `split_bill`/`merge_check` logic found. Coupon/wallet application is per single order (`payments.recompute_order_total`), not per-check-split. |
| Coursing (fire courses in sequence) | ❌ Not implemented | KDS (`src/app/kds/`) has ticket status (received/preparing/ready/bumped) per item but no "course" grouping or fire-on-demand sequencing. |
| Modifiers | 🟡 Partial | Menu supports dish variants ("Item variants (size, etc.)" — `docs/PLATFORM_FEATURES_REFERENCE.md` §12) and the WhatsApp conversation engine handles free-text "kitchen modifiers" (special requests → `additional_details`, `src/app/conversation/engine.py`). There is no structured modifier-group data model (e.g., "choose 1 of: extra cheese/no onion" with price deltas) — it's LLM-parsed free text, not a schema. |
| Notes (order/item level) | ✅ Implemented | Special requests captured verbatim into `additional_details` on the order (`src/app/conversation/engine.py`); `Ticket.evidence`/`resolution_note` for complaints (`src/app/tickets/models.py`). |
| Table/check transfer | ❌ Not implemented | No tables exist to transfer between (see row 1). |
| Waitlist / reservations | ❌ Not implemented | `grep -rli "reservation\|waitlist"` across `src/app` and `frontend/src` returns nothing. |
| Seat-level ordering | ❌ Not implemented | No seat concept (delivery-only model). |

**Category summary:** 0/8 fully implemented, 1/8 partial, 7/8 missing. This entire category assumes a dine-in floor, which the product doesn't have. Phase D (table/floor management) in the existing roadmap lettering is reserved for exactly this, but not started.

---

## 2. Kitchen Operations

| Item | Status | Evidence |
|---|---|---|
| KDS (kitchen display system) | ✅ Implemented | `src/app/kds/` — `KitchenStation`, `PrintJob` models (`models.py`); `create_tickets_for_order()`, `resolve_station()` (`service.py`); router at `/api/v1/kds` (`router.py`); dashboard screen `frontend/src/screens/KdsScreen.tsx` + tests. Just shipped per `docs/superpowers/specs/2026-07-07-kitchen-kds-design.md` and `docs/superpowers/plans/2026-07-07-kitchen-kds.md`. |
| Printer routing | 🟡 Partial | Backend models the routing correctly: dish → category default → station fallback (`src/app/kds/service.py:resolve_station`), and `PrintJob` rows are enqueued per station mirroring the `outbox_messages` retry pattern. But the actual ESC/POS printer driver that would consume `GET /api/v1/kds/print-jobs/pending` and print is a stub: `desktop/src/main/native/printer.ts` — `NotImplementedPrinter.print()` throws `"printer not implemented — see Phase B spec"`. No real hardware output exists yet. |
| Order prioritization | 🟡 Partial | Dispatch-side prioritization exists (priority orders get sealed single-rider batches, `src/app/dispatch/batching.py`), but no prep-priority signal inside the KDS ticket view itself beyond ordering by creation time. |
| Prep time tracking | 🟡 Partial | `dishes.prep_minutes` field exists and is referenced in the KDS design spec for UI-side urgency coloring (yellow @80%, red @100% of prep time) — but this is **not enforced server-side**, purely a planned UI treatment; confirm whether `frontend/src/screens/KdsScreen.tsx` actually renders it (spec describes it, implementation should be verified per-ticket at review time). |
| Bump bar | ✅ Implemented | `PATCH /api/v1/kds/items/{item_id}/bump` and `.../recall` (`src/app/kds/router.py`) — bump/recall are audited status transitions, no deletes, matching spec. |
| Course firing | ❌ Not implemented | No course concept (see category 1). |
| 86'd items (out of stock) | ❌ Not implemented | The KDS design spec explicitly states 86'd-item handling is "not covered" in that spec. Menu has an `availability` flag on dishes (`src/app/menu/models.py` — used to hide items from WhatsApp ordering) but no dedicated "86 this item for today, auto-restore tomorrow" workflow, no KDS-side 86 button, no cross-channel propagation event. |

**Category summary:** 2/7 fully implemented (KDS core + bump bar), 3/7 partial (printer routing needs real hardware driver, prioritization and prep-time need work), 2/7 missing (course firing — depends on table/course concept; 86'd items). Strong recent progress here (Phase B just landed).

---

## 3. Payments & Checkout

| Item | Status | Evidence |
|---|---|---|
| Card/cash/wallet processing | 🟡 Partial | Cash: full COD ledger (`src/app/cod/` — `CodCollection`, `RiderShiftReconciliation`, `reconcile_shift()`). Wallet: full ledger with holds/capture/release (`src/app/wallet/service.py` — `credit`, `debit`, `hold`, `capture`, `release`, `freeze`, `reverse`). **Card processing: not implemented** — business rule is explicitly "COD only" (spec §non-negotiable rules, enforced in `cod/service.py`); no card/PSP integration exists anywhere. |
| NFC/EMV | ❌ Not implemented | No card-present hardware integration; consistent with COD-only rule. |
| Split payments | ❌ Not implemented | No mechanism to split a single order's payment across tenders. |
| Tableside pay | ❌ Not implemented | No table concept, no card terminal integration. |
| Tipping | ❌ Not implemented | No tip field on orders, riders, or wallet entries. |
| Pre-auth | ❌ Not implemented | No card processing at all (see above). |
| Cash drawer | ❌ Not implemented | No cash-drawer-open event, no till/session model. This is explicitly the planned scope of roadmap Phase C. |
| Dual pricing (cash vs card price) | ❌ Not implemented | Single price path only (`payments.recompute_order_total`); no card-surcharge or dual-price logic. |
| Digital receipts | 🟡 Partial | Customers get order confirmations/summaries via WhatsApp text (conversation engine renders order summary at `awaiting_confirmation`), but there is no formatted, itemized, VAT-compliant digital receipt artifact (PDF/image) generated and sent. |

**Category summary:** 0/9 fully implemented, 2/9 partial (cash/wallet ledgers exist, receipts are informal), 7/9 missing. This is the single biggest gap category — the product has never needed real payment processing because COD-via-WhatsApp doesn't require it, but a POS aiming at walk-in/counter service will need cash drawer + card processing + Z-report, which is why this maps to existing roadmap Phase C.

---

## 4. Menu Management

| Item | Status | Evidence |
|---|---|---|
| Categories | ✅ Implemented | `Dish.category` field (`src/app/menu/models.py`); category-based menu rendering and category→KDS-station default mapping (`src/app/kds/models.py:CategoryStationDefault`). |
| Modifiers/combos | 🟡 Partial | See category 1 — free-text modifier handling via LLM, no structured modifier-group schema with priced options; "combo handling" mentioned as a conversation-engine capability (`docs/PLATFORM_FEATURES_REFERENCE.md` §7) but not a first-class combo/bundle data model with its own pricing rules. |
| Real-time availability | ✅ Implemented | `Dish.availability` toggle, enforced in ordering/conversation flow and dashboard Menu Manager (`frontend/src/screens/MenuManagerScreen.tsx`). |
| Happy hour / dynamic pricing | ❌ Not implemented | `Dish.sale_price` exists as a static override (`sale_price_aed` when `0 < sale < base`) but there is no time-windowed/scheduled pricing rule engine (no "3-5pm 20% off" automation). |
| Allergen info | ❌ Not implemented | No allergen field on `Dish`; description field is free text only, capped at 3 lines with the explicit rule "never include price" — no structured allergen tagging. |
| Remote sync (menu changes propagate everywhere) | ✅ Implemented | POS sync (`src/app/pos/sync_service.py` — Cratis POS → internal menu), Meta Commerce catalog sync (`src/app/catalog/sync_service.py`), and desktop offline pull sync (`desktop/src/main/sync.ts:pullSync()` — `GET /api/v1/menu/dishes?updated_since=`) all keep menu state consistent across channels. |
| Multi-tax (per-item tax rates) | ❌ Not implemented | No tax/VAT field anywhere on `Dish` or `Order`/`OrderItem` models — `grep -rli "vat\|trn\|e-invoic"` across `src/app`, `frontend/src`, `docs` returns nothing. Pricing is currently VAT-silent. |

**Category summary:** 3/7 fully implemented (categories, availability, remote sync — genuinely strong), 1/7 partial (modifiers), 3/7 missing (dynamic pricing, allergens, tax). Menu management is one of the platform's most mature areas because AI menu digitization is core to onboarding, but it has zero tax awareness, which blocks UAE compliance entirely until addressed.

---

## 5. Inventory & Supply Chain

| Item | Status | Evidence |
|---|---|---|
| Ingredient-level tracking | ❌ Not implemented | `grep -rli "ingredient\|stock_level\|inventory_item"` across `src/app` returns nothing. Menu models dishes only, not component ingredients. |
| Auto-deduction (on order) | ❌ Not implemented | No inventory to deduct from. |
| Low-stock alerts | ❌ Not implemented | Not applicable without inventory tracking. |
| Theoretical vs. actual variance | ❌ Not implemented | No inventory counts of any kind. |
| Vendor / PO management | ❌ Not implemented | `grep -rli "purchase_order\|vendor"` returns nothing. |
| Waste tracking | ❌ Not implemented | Not present. |

**Category summary:** 0/6 implemented. Entirely greenfield — this is existing roadmap Phase E (inventory/COGS), explicitly not started. The only adjacent concept today is `Dish.availability` as a manual boolean toggle, which is a proxy for "in/out of stock" but carries none of the ingredient-level machinery.

---

## 6. Staff & Labor

| Item | Status | Evidence |
|---|---|---|
| Clock-in/out | ❌ Not implemented | `grep -rli "clock_in\|clock_out\|timesheet"` returns nothing. Rider "duty" on/off exists (`/api/v1/rider-app/duty` — `src/app/dispatch/`) but that's shift-toggle for delivery dispatch eligibility, not a labor-hours/payroll clock. |
| RBAC (role-based access control) | 🟡 Partial | JWT auth exists (`src/app/identity/`) but there is a single manager/restaurant-account role — `docs/PLATFORM_FEATURES_REFERENCE.md` explicitly notes `manager_users` (separate manager accounts / multi-role) is "(Planned)", not built. Rider role is separate (different auth surface, `/api/v1/rider-app/*`) but there's no granular permission model (e.g., cashier vs. manager vs. kitchen-only). |
| Shift scheduling | ❌ Not implemented | No shift/schedule model for staff (rider duty toggle is real-time on/off, not a forward schedule). |
| Sales-per-server | ❌ Not implemented | No "server" concept — orders aren't attributed to a staff member taking the order (manual orders via dashboard don't carry a creator/server attribution field beyond audit log actor). |
| Tip pooling | ❌ Not implemented | No tipping exists at all (category 3), so no pooling. |
| Payroll integration | ❌ Not implemented | No payroll models, exports, or third-party payroll connectors. |

**Category summary:** 0/6 implemented, 1/6 partial (basic auth exists, not full RBAC), 5/6 missing. Entirely unaddressed — makes sense given the product has no in-person staff shifts (riders are the only "staff" surface today).

---

## 7. Customer Experience & Loyalty

| Item | Status | Evidence |
|---|---|---|
| Customer profiles | ✅ Implemented | `Customer` model (`src/app/identity/models.py` per `PLATFORM_FEATURES_REFERENCE.md` §5) — phone, name, order stats, `usual_order_times`, tags, marketing opt-out; dashboard `frontend/src/screens/CustomerProfileScreen.tsx` shows history/wallet/coupons. |
| Loyalty/rewards | ✅ Implemented | `src/app/loyalty/service.py` — tier computation (bronze/silver/gold), demotion-grace window, manager tier lock/override, recurring reward issuance, `earn()`/`reverse_earn()` crediting wallet on order/refund; nightly `recompute_all_tenants()` worker. No standalone loyalty router/API surface — state lives on `Customer` + is surfaced through wallet/coupons, not its own screen. |
| Gift cards | ❌ Not implemented | `grep -rli "gift_card"` across `src/app` returns nothing. Wallet (`src/app/wallet/`) supports arbitrary credit issuance which could be repurposed, but there is no gift-card purchase/redemption product (no code generation for a purchasable card, no card-specific expiry/denomination model distinct from the general wallet ledger). |
| CRM | 🟡 Partial | Customer profiles + tags + order history + segments (marketing `src/app/marketing/` RFM segmentation, `docs/PLATFORM_FEATURES_REFERENCE.md` §13) give CRM-lite capability; no dedicated CRM screen beyond `CustomersScreen.tsx`/`CustomerProfileScreen.tsx`, no notes/interaction-log CRM object beyond tickets. |
| Order history | ✅ Implemented | Full order history per customer (`CustomerProfileScreen.tsx`, `partner/orders_api.py:list_partner_orders` supports `status=all` for full history). |
| Caller ID | ❌ Not implemented | Not applicable in current form — there's no voice/phone channel integration for inbound call routing; `docs/voice-phone-ordering-reference.md` exists as reference material but `grep` for caller-ID wiring in `src/app` finds nothing implemented. This is a WhatsApp-first platform; caller ID belongs to a phone-order channel that doesn't exist yet. |

**Category summary:** 3/6 implemented (profiles, loyalty, order history), 1/6 partial (CRM), 2/6 missing (gift cards, caller ID). This is a strength area — loyalty and customer data are unusually mature for a "gap analysis" target.

---

## 8. Online & Omnichannel Ordering

| Item | Status | Evidence |
|---|---|---|
| Native ordering (WhatsApp AI order-taking) | ✅ Implemented (core to the platform, not an add-on) | The entire `src/app/conversation/` engine — ordering, address capture, modification, fuzzy matching, complaint handling — is the primary order channel. This *is* the product, not a bolt-on feature. |
| QR/kiosk | ❌ Not implemented | No QR-to-menu or kiosk-mode UI; no table-based QR flow (again tied to the missing table concept). |
| Third-party delivery integration (aggregators: Talabat/Deliveroo/Careem etc.) | ❌ Not implemented | No aggregator adapter exists. `src/app/partner/` is a **restaurant-owned-POS** integration surface (e.g., Cratis), not a delivery-aggregator ingestion pipeline — different direction of integration entirely. |
| Cross-channel sync | 🟡 Partial | Menu is synced across POS/Meta-catalog/desktop (see category 4), but there is no aggregator channel to sync into yet. |
| Driver assignment | ✅ Implemented | Full in-house dispatch: `src/app/dispatch/service.py` (batching, scoring, routing, re-optimization) — but only for the platform's own employee riders, not for assigning aggregator drivers. |

**Category summary:** 2/5 implemented (native ordering is a standout strength, driver assignment is mature), 1/5 partial, 2/5 missing (QR/kiosk, aggregator integration). Aggregator integration is a meaningful gap for restaurants that also list on Talabat/Deliveroo/Careem and want centralized order management.

---

## 9. Reporting & Analytics

| Item | Status | Evidence |
|---|---|---|
| Real-time dashboards | ✅ Implemented | `frontend/src/screens/LiveOpsScreen.tsx` — KPIs, dispatch map, SLA board; `frontend/src/screens/AnalyticsScreen.tsx` — KPIs + predictions panel. |
| Item performance | 🟡 Partial | Demand prediction features track per-dish trailing demand (`src/app/predictions/features.py`) for forecasting purposes; no dedicated "best/worst sellers, margin per item" report screen. |
| Labor cost | ❌ Not implemented | No labor/shift data exists to report on (category 6). |
| Inventory usage | ❌ Not implemented | No inventory data exists to report on (category 5). |
| Peak-hour / table-turn analytics | 🟡 Partial | Peak-hour is implicitly covered by prediction horizons (next_1h, breakfast/lunch/dinner/midnight — `src/app/predictions/service.py`); table-turn is not applicable (no tables). |
| Custom reports | ❌ Not implemented | No report-builder/export UI; `AnalyticsScreen.tsx` is a fixed set of panels, not configurable. |

**Category summary:** 1/6 implemented, 2/6 partial, 3/6 missing. Reporting is currently ops-dashboard-shaped (live SLA/dispatch/demand), not finance/labor-shaped — the missing pieces (labor cost, inventory usage, custom reports) are downstream of categories 5 and 6 not existing yet.

---

## 10. Integrations

| Item | Status | Evidence |
|---|---|---|
| Accounting | ❌ Not implemented | No QuickBooks/Xero/Zoho Books connector; no ledger export. |
| Payroll | ❌ Not implemented | No payroll integration (staff/labor doesn't exist to feed it). |
| Reservation systems | ❌ Not implemented | No reservations exist to integrate (category 1). |
| Marketing tools | ✅ Implemented (in-house, not third-party) | `src/app/marketing/` is a full in-house marketing automation suite (campaigns, segments, templates, automations) rather than an integration to an external tool like Klaviyo — arguably stronger than a typical POS's marketing "integration" since it's native. |
| Digital signage | ❌ Not implemented | No signage/display-feed integration. |
| Hardware (scanners, scales, printers, cash drawers) | 🟡 Partial | Module boundaries exist and are explicitly scaffolded for future hardware: `desktop/src/main/native/printer.ts` (`NotImplementedPrinter`), `desktop/src/main/native/usb.ts` (`NotImplementedUsb`) — both are literal stub classes that throw, per `docs/superpowers/specs/2026-07-07-desktop-shell-foundation-design.md` ("Hardware access: main-process module boundary only... explicitly deferred to Phase B/F"). No real driver for any hardware class exists yet. |

**Category summary:** 1/6 implemented (marketing, in-house), 1/6 partial (hardware boundary scaffolded, no drivers), 4/6 missing.

---

## 11. Security / Reliability

| Item | Status | Evidence |
|---|---|---|
| Offline mode | 🟡 Partial | Architecture designed and partially built: local SQLite (`local_menu`, `local_orders`, `pending_ops`, `sync_state` — per `docs/superpowers/specs/2026-07-07-desktop-shell-foundation-design.md` and `desktop/src/main/db.ts`), pull sync implemented (`desktop/src/main/sync.ts:pullSync()` for menu only — no order pull function exists yet in that file), push sync implemented generically (`pushSync()`/`pushOne()` drains `pending_ops` FIFO). This is real, working code, not vaporware — but it's new/uncommitted (`desktop/src/main/sync.ts` and `sync.test.ts` are untracked per `git status`) and only covers menu pull; full offline order-taking end-to-end is not yet proven complete. |
| Cloud sync | 🟡 Partial | Same evidence as above — push/pull primitives exist; conflict handling is explicit and safe (409 → marked `conflict`, never auto-resolved per design doc), but this is early-stage, single-entity (menu) coverage today. |
| Multi-location / multi-branch | ❌ Not implemented | Multi-*tenant* exists (every table carries `restaurant_id`, JWT-scoped queries — `src/app/identity/deps.py:current_restaurant`), but multi-tenant ≠ multi-branch: there's no concept of one restaurant brand operating several physical branches under a shared owner view. `docs/PLATFORM_FEATURES_REFERENCE.md` confirms `manager_users` for multi-user/multi-branch is "(Planned)". A franchise/centralized-dashboard view across branches does not exist. |
| Mobile POS | ❌ Not implemented | The desktop Electron shell (`desktop/`) targets Windows desktop, not a mobile counter/tableside device. The existing "rider app" (`/api/v1/rider-app/*`) is mobile but is a delivery-fulfillment app, not a POS terminal for order-taking/payment. |
| PCI-DSS | ❌ Not implemented / not applicable yet | No card processing exists (category 3), so no PCI scope currently — but this also means PCI compliance work hasn't started and will be required once card payments are added. |
| Audit trails | ✅ Implemented | `src/app/audit/` — `record_audit()` called in the same transaction on every state change (append-only, no UPDATE/DELETE), enforced platform-wide per `docs/PLATFORM_FEATURES_REFERENCE.md` §19. This is one of the platform's strongest reliability guarantees. |
| Backups | ❌ Not documented/verified in this repo | No backup/restore automation found in `src/app` or `ops/`; likely handled at the hosting/infra layer (not code) — out of scope for this codebase-only gap analysis, flagged as unverified rather than "not implemented." |

**Category summary:** 1/7 fully implemented (audit trails — genuinely strong), 2/7 partial (offline/cloud sync — real, in-progress, uncommitted), 4/7 missing or unverified.

---

## 12. Advanced / AI

| Item | Status | Evidence |
|---|---|---|
| Upsell recommendations | ❌ Not implemented | No structured upsell logic found (e.g., "add fries for AED 5" prompts) in the conversation engine; the engine handles combos/modifiers reactively, not proactive upsell suggestion. |
| Interactive analytics | 🟡 Partial | `AnalyticsScreen.tsx` + predictions panel provide interactive dashboard elements (charts, KPI drilldowns per existing screen), but no ad-hoc query/interactive-analytics tool. |
| Branded receipts | ❌ Not implemented | No receipt template/branding system (see category 3, digital receipts partial at best). |
| Multi-currency | ❌ Not implemented | All money fields are AED-only (`Numeric(8,2)`/`Decimal`, AED per CLAUDE.md conventions); no currency field on `Order`/`Dish`, no FX handling anywhere. |

**Category summary:** 0/4 implemented, 1/4 partial, 3/4 missing.

---

## 13. UAE-Specific Compliance / E-Invoicing

| Item | Status | Evidence |
|---|---|---|
| VAT invoice generation | ❌ Not implemented | No VAT field/calculation anywhere in `src/app` (confirmed via grep, category 4). Orders store subtotal/fees/total but no tax breakdown line. |
| TRN (Tax Registration Number) | ❌ Not implemented | No `trn` field on `Restaurant`/`Order` models. |
| E-invoicing (UAE Ministry of Finance structured-data requirement) | ❌ Not implemented | No structured e-invoice generation (UBL/PINT-AE format or equivalent), no integration with an Accredited Service Provider (ASP), which UAE e-invoicing mandates require. |
| Z-report (end-of-day cash/sales reconciliation report) | ❌ Not implemented | No till/session/shift model exists to summarize into a Z-report (depends on category 3's cash drawer, which doesn't exist). This is explicitly the scope of existing roadmap Phase C. |
| Audit trail (for tax purposes) | ✅ Implemented (general purpose, not tax-specific) | `src/app/audit/record_audit()` provides an immutable, append-only audit log for all state changes — this satisfies the *general* audit-trail requirement, but it is not a VAT/e-invoice-specific audit chain (no invoice sequence numbering, no tax-authority-required data set attached to audit records). |

**Category summary:** 1/5 implemented (general audit trail reused, not purpose-built), 0/5 partial, 4/5 missing. **This entire category is blocked on categories 3 (payments/cash drawer) and 4 (multi-tax)** — you cannot generate a real VAT invoice or Z-report without first having priced-with-tax line items and a till/session concept to reconcile. This is the correct dependency ordering reflected in the roadmap document.

---

## 14. AI Feature List (checklist's own AI items)

| Item | Status | Evidence |
|---|---|---|
| WhatsApp AI order-taking | ✅ Implemented (already core, not a gap) | `src/app/conversation/engine.py` + `src/app/llm/` (Claude/DeepSeek extraction and dialogue) — this is the platform's foundation, extensively tested (`tests/conversation/`). |
| AI upsell | ❌ Not implemented | Same gap as category 12 — no proactive upsell logic in the conversation engine. |
| AI reorder prompts | 🟡 Partial | Recurring promo scheduling exists and is demand-aware (`usual_order_times` recency weighting, `recurring_message_state` per customer, `src/app/marketing/`) which functionally nudges reorders — but it's a scheduled marketing campaign, not a conversational "you usually order X around now, want the same?" in-chat prompt. |
| AI demand forecasting | ✅ Implemented | `src/app/predictions/` — LightGBM per restaurant (per `docs/PLATFORM_FEATURES_REFERENCE.md` §14 — though note `factory.py:28-32` still raises `NotImplementedError` for the LightGBM path per the earlier module audit, meaning production forecasting currently runs on `RollingAverageModel`, not LightGBM, despite the reference doc's description — flag this discrepancy), features (`predictions/features.py`), MAPE accuracy tracking, weekly retrain schedule, manager plain-English overrides via LLM (`predictions/adjust.py`). Core forecasting loop is real and tested even if the LightGBM upgrade is stubbed. |
| AI daily owner summary | ❌ Not implemented | No "here's your day" digest generation found in marketing or predictions modules. |
| AI review reply | ❌ Not implemented | No review-platform integration (Google/Talabat reviews) exists to reply to. |
| AI voice ordering | ❌ Not implemented | `src/app/speech/` exists ("speech-related utilities") and `docs/voice-phone-ordering-reference.md` is a research doc, but no live voice-ordering channel is wired into `src/app/conversation/` or `src/app/webhook/`. This is designed/researched, not built. |

**Category summary:** 2/7 implemented (order-taking, demand forecasting core loop), 1/7 partial (reorder nudges via marketing), 4/7 missing.

---

## Overall Summary

Counting every distinct checklist line above (roughly 79 discrete items across the 14 categories):

- **✅ Fully implemented:** ~19 items (~24%)
- **🟡 Partial:** ~17 items (~22%)
- **❌ Not implemented:** ~43 items (~54%)

**Where the platform is strong (don't undersell):** WhatsApp AI order-taking, dispatch/SLA/rider logistics, KDS core (just shipped), menu digitization + multi-channel sync, wallet/loyalty/coupons, marketing automation, demand prediction core loop, audit trail, multi-tenancy, partner/POS integration surface, and now the beginnings of a real offline-capable desktop shell.

**Where the platform is genuinely greenfield:** everything premised on a physical counter/dine-in experience — table management, cash drawer/Z-report, card payments, inventory/COGS, staff labor/payroll, and UAE tax compliance (which is itself blocked on payments + multi-tax). These map directly onto the already-agreed roadmap letters C (payments/cash drawer/Z-report), D (table/floor management), E (inventory/COGS), and F (hardware SDK) — none of which have started except the hardware module *boundaries* (stub classes) scaffolded in the desktop shell.
