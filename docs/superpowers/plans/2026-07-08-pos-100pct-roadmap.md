# POS 100% Feature Roadmap

**Source:** `docs/POS_100_FEATURE_AUDIT_2026-07-08.md` (128 FULL / 96 PARTIAL / 141 MISSING out of ~365 items across 14 categories).

**Execution model:** 2 workstreams run in parallel per wave (2 agents at a time, per project standing instruction). Each workstream gets its own detailed bite-sized TDD plan written **just before it starts** (not now) — writing full code-level plans 5 waves ahead means the plan is stale by the time an agent picks it up. This doc sequences the work and locks scope per workstream; `docs/superpowers/plans/<date>-<workstream>.md` holds the executable detail once a wave is about to run.

**Scoping decisions locked 2026-07-08** (see audit doc "Scoping decisions" section):
- Till-checkout `payments/` module: IN SCOPE, finish it.
- Aggregators (Talabat/Deliveroo/Careem/Uber Eats): BUILD REAL ADAPTERS.
- Multi-branch: ADD parent `Organization` entity above `Restaurant`.

---

## Workstreams

| # | Name | Categories covered | Risk | Depends on |
|---|---|---|---|---|
| WS-STAFF | Staff & cash-drawer frontend + gaps | Cat 9 (staff/perms) | Low | none |
| WS-REPORTS | Reporting frontend + missing reports | Cat 10 (reporting) | Low | none |
| WS-PAY | Till-checkout payment gaps | Cat 5 (payments/billing) | Medium | none |
| WS-DELIVERY | Delivery flow fixes + gaps | Cat 7 (delivery) | Medium | none |
| WS-ORG | Organization/multi-branch entity | Cat 11 (multi-branch) | High (schema, touches `identity/deps.py:current_restaurant`) | none, but everything using `restaurant_id` as tenant root should land after this if it wants org-awareness |
| WS-INVENTORY | Inventory/food-cost gaps | Cat 4 (inventory) | Low-Medium | none |
| WS-MENU | Menu control gaps (dynamic pricing, categories, approval) | Cat 3 (menu) | Medium (touches `Dish`, a god-node-adjacent model) | none |
| WS-CRM | Customer/CRM/loyalty gaps | Cat 6 (CRM) | Low-Medium | none |
| WS-ORDER | Order management gaps (split/merge/course/held) | Cat 1 (orders) | High (touches `ordering/models.py`, `ordering/service.py` — god-node adjacent per CLAUDE.md) | none |
| WS-KDS | Kitchen/KDS gaps | Cat 2 (kitchen) | Medium | best after WS-ORDER (course-wise ordering feeds KDS fire-course-later) |
| WS-AGGR | Real aggregator adapters (Talabat/Deliveroo/Careem/Uber Eats/Noon Food) | Cat 8 (aggregators) | Medium-High (external creds/APIs per vendor) | none |
| WS-UAE | UAE compliance gaps | Cat 13 (compliance) | Low-Medium | best after WS-PAY (credit note needs payment refund shape settled) |
| WS-RELIABILITY | Offline/backup/reliability gaps | Cat 12 (reliability) | Medium (touches desktop shell + printer driver) | none |
| WS-AI | AI-narrative features | Cat 14 (AI) | Low-Medium (additive LLM calls) | best after WS-REPORTS (AI daily summary narrates report data) |

## Wave sequencing

Ordered for: fastest visible wins first, schema-risk work done once agent/test patterns are warmed up, external-dependency work timeboxed later, narrative/polish work last.

| Wave | Workstreams | Why paired |
|---|---|---|
| 1 | WS-STAFF + WS-REPORTS | Both are pure frontend-for-existing-tested-backend, zero schema change, completely disjoint files (`frontend/src/screens/Staff*` vs `Reports*`). Fastest ROI, de-risks the "2-agent parallel" workflow itself. |
| 2 | WS-PAY + WS-DELIVERY | Both are backend-gap-filling in already-well-tested modules (`payments/`, `dispatch/`/`cod/`), disjoint files, medium risk. |
| 3 | WS-ORG + WS-INVENTORY | WS-ORG is the one foundational schema change — do it once the team/agents have 2 successful waves behind them. Paired with WS-INVENTORY because inventory work barely touches `identity/deps.py` (low interaction risk with the ORG migration). |
| 4 | WS-MENU + WS-CRM | Customer- and menu-facing features; both benefit from WS-ORG existing (branch-scoped pricing/menus, shared loyalty) but aren't blocked by it — org-awareness can be layered in as a follow-up if ORG lands late. |
| 5 | WS-ORDER + WS-KDS | Highest blast-radius category (order FSM, `ordering/service.py` is a god node). Saved for when patterns are mature. Paired together since KDS fire-course-later depends on WS-ORDER's course-wise ordering field. |
| 6 | WS-AGGR + WS-UAE | External API integration (needs real Talabat/Deliveroo/Careem/UberEats credentials — likely blocked on business/legal, timebox separately) + compliance polish (credit note depends on WS-PAY's refund shape). |
| 7 | WS-RELIABILITY + WS-AI | Reliability hardening (printer driver, offline payment, backup) + AI-narrative polish (daily summary, anomaly detection, review replies) — lowest urgency, done last. |

## Per-workstream scope notes (what "done" means)

**WS-STAFF** — Staff list/create UI, PIN-based clock in/out UI, shift schedule UI, tip-pool report UI (wires existing backend). Plus close gaps: break tracking (`ClockEvent.type` add `break_start`/`break_end`), overtime threshold in `compute_hours`, `record_audit` calls in `staff/`+`cashdrawer/` service functions, cash-drawer-assignment FK to `StaffMember` instead of free-text.

**WS-REPORTS** — New Reports hub screen wiring all 9 existing `reports/` endpoints (sales-rollup, item-performance+csv, z-report, retention, labor-hours, prep-time×2, invoice-sequence). Plus close gaps: sales-by-category/channel/waiter/payment-method, void report, refund report, wastage report, AOV, peak-hour report, inventory valuation, WhatsApp daily owner report (Celery beat task), xlsx export.

**WS-PAY** — Tap-to-pay flag, service charge field + calc, packaging/minimum-order charge fields, credit note model, deposit/advance payment tender types, Z-report/cash-closing UI (shares backend with WS-REPORTS z-report — coordinate), PSP↔`PaymentTransaction` reconciliation job, duplicate-payment idempotency-key wiring confirmed on `/payments/charge`.

**WS-DELIVERY** — `floor` field on address, fix `reconcile_shift` stub (`expected = collected` bug), delivery-proof-photo rider-app upload UI, driver performance report + average-delivery-time metric.

**WS-ORG** — New `Organization` table; `Restaurant.organization_id` FK (nullable initially, backfilled to org-of-one per existing restaurant); `organizations/` rollup queries migrate to real joins; centralized menu template, shared loyalty, centralized customer db, region reports become buildable on top (tracked as WS-ORG follow-ups, not all in this workstream — this workstream is the schema + rollup migration only).

**WS-INVENTORY** — Vendor price comparison, food-cost %, gross-margin-by-item report, over-portioning/theft alerts, wire `list_low_stock` to WhatsApp outbox, daily stock-closing report, stock-adjustment approval gate, recipe yield tracking.

**WS-MENU** — Dedicated `Category` model (replace free-text), happy-hour/time/channel/branch pricing rules, delivery-only/dine-in-only/QR-only menu flags, auto-hide on zero stock, allergen tags, menu approval workflow (`pending_approval` status), bulk CSV import, bulk price update.

**WS-CRM** — Customer notes/allergy/birthday/anniversary fields, stamp card model, CLV calc, AOV-by-customer report, review-request automation, birthday-offer campaign preset, NPS-detractor→complaint-escalation link.

**WS-ORDER** — `Order.order_type` enum (dine_in/takeaway/delivery/qr/drive_thru), held-order status, course-wise ordering (`OrderItem.course` + fire-course endpoint), rush/priority buttons, split-by-item, split-by-seat, merge-orders, staff-to-staff order transfer.

**WS-KDS** — Station presets (grill/fry/beverage/dessert/pizza), estimated-ready-time field, auto-prioritize-by-age sort, allergen warning + modifier display on ticket payload, packaging checklist, ready-for-pickup customer/rider-facing status.

**WS-AGGR** — Real Talabat/Deliveroo/Careem/Uber Eats/Noon Food adapters (credentials, webhook signature verification, menu/price/stock push), commission-rate model, channel-profitability report. API request/response reference: `docs/AGGREGATOR_API_REFERENCE.md`.

**WS-UAE** — Simplified/B2C invoice variant, tax-inclusive pricing mode, credit note (shares model with WS-PAY), data-retention policy, accountant export format, structured e-invoice JSON (UBL/PINT AE shape — not ASP transmission, that's explicitly out of scope per code comment).

**WS-RELIABILITY** — Real printer driver (replace `NotImplementedPrinter`), offline payment queue, automated conflict-resolution rules, cloud backup wiring, printer/device failover, admin-activity-log viewer screen, scheduled daily backup Celery task.

**WS-AI** — AI daily sales summary (LLM narrates `sales_rollup`), AI low-stock prediction (link `predictions` module to inventory), AI staff performance summary, review system + AI reply suggestion (new feature — no review entity exists yet), AI "why sales dropped", AI festival campaign generator, AI menu translation.

---

## Next step

Wave 1 (WS-STAFF + WS-REPORTS) detailed plan: `docs/superpowers/plans/2026-07-08-wave1-staff-reports-frontend.md`.
