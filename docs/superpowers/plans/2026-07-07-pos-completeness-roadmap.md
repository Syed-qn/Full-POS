# POS Completeness Roadmap — Phased Plan

**Date:** 2026-07-07
**Type:** Phase-sequencing roadmap (NOT a task-by-task TDD plan — each phase gets its own bite-sized implementation plan via the `writing-plans` skill when it's picked up).
**Source:** `docs/POS_FEATURE_GAP_ANALYSIS.md` (full item-by-item evidence). This document only sequences what that analysis found missing or partial.
**Existing lettering to continue from:** A = partner API (done), B = KDS (done, `docs/superpowers/plans/2026-07-07-kitchen-kds.md`), C = payments/cash drawer/Z-report (not started), D = table/floor management (not started), E = inventory/COGS (not started), F = hardware SDK (boundary stubs only, `desktop/src/main/native/`).

This plan continues the letter sequence: **C, D, E, F** (already reserved, now scoped below) then **G, H, I, J, K** for everything the gap analysis found that doesn't yet have a letter (UAE compliance, staff/labor, CRM/gift cards/upsell, aggregator/omnichannel, offline-mode hardening, reporting).

Sizes are rough: S = ~1 week, M = ~2-4 weeks, L = ~1-2 months, XL = ~2-3+ months, all assuming the existing solo/small-team pace evidenced by prior phases in `docs/IMPLEMENTATION_STATUS.md`.

---

## Phase C — Payments, Cash Drawer & Z-Report
**Scope:** Add a till/session model (open/close shift with starting float), cash drawer open events, card/PSP processing as a second tender alongside COD, split payments across tenders, tipping, and the end-of-day Z-report (cash reconciliation: expected vs. counted, by tender type). This is the single highest-leverage phase — it unblocks UAE compliance (Phase H) and dual pricing.
**Covers checklist items:** Card/cash/wallet processing (the card half), split payments, tableside pay, tipping, pre-auth, cash drawer, dual pricing, digital receipts (formal itemized version), Z-report, PCI-DSS scoping.
**Size:** XL (card/PSP integration + PCI scoping alone is a multi-week effort; till/session + Z-report is a clean, independent M-sized sub-slice that could ship first).
**Dependencies:** None on other new phases — builds on existing `cod/`, `wallet/`, `coupons/`, `ordering/` modules. Should land before Phase H (UAE e-invoicing) since invoices need real tax-inclusive line totals and a session to reconcile against.
**Suggested internal sequencing:** (1) till/session + cash drawer + Z-report on top of existing COD ledger (no new payment rails, pure reconciliation) → (2) card/PSP integration + split payments + tipping + pre-auth (the genuinely new, PCI-scoped work) → (3) dual pricing + formal digital receipts once tender types exist.

---

## Phase D — Table & Floor Management
**Scope:** Table/floor plan model, seat-level ordering, dine-in order type distinct from delivery, split/merge checks, table/check transfer, coursing (fire-on-demand sequencing feeding into KDS), waitlist/reservations. Independent of payments and inventory — this is purely an order-taking/service-flow addition.
**Covers checklist items:** Table/floor plans, split/merge checks, coursing, table/check transfer, waitlist/reservations, seat-level ordering, QR/kiosk ordering (natural fit once tables exist — a QR code just deep-links to a table-scoped ordering session).
**Size:** L (new bounded context `src/app/tables/`, new FSM for dine-in order lifecycle distinct from the delivery FSM, new dashboard screens, KDS coursing hooks).
**Dependencies:** Loosely depends on Phase C only for "tableside pay" (paying at the table needs a tender) — everything else (floor plan, seating, course firing, waitlist) can be built and tested independently of payments. KDS coursing hooks depend on the already-shipped Phase B (`src/app/kds/`).

---

## Phase E — Inventory & Supply Chain (COGS)
**Scope:** Ingredient-level stock tracking, recipe/BOM linking dishes to ingredients, auto-deduction on order confirmation, low-stock alerts, theoretical-vs-actual variance reporting, vendor/PO management, waste tracking. This is the largest net-new data model in the roadmap.
**Covers checklist items:** Ingredient-level tracking, auto-deduction, low-stock alerts, theoretical-vs-actual, vendor/PO mgmt, waste tracking, inventory usage reporting (feeds Phase I).
**Size:** XL (new bounded context `src/app/inventory/`, recipe/BOM data model, deduction hooks into the order confirmation pipeline, vendor/PO workflow, plus a genuinely new "waste" concept).
**Dependencies:** Independent of C and D. Interacts with `menu/` (dishes need a recipe/BOM link) but doesn't require payments or tables to exist first. Auto-deduction hooks into the existing order-confirmation transaction in `ordering/service.py`.

---

## Phase F — Hardware SDK
**Scope:** Real drivers behind the already-scaffolded stub interfaces in `desktop/src/main/native/printer.ts` (`NotImplementedPrinter`) and `usb.ts` (`NotImplementedUsb`) — ESC/POS thermal printer output (consuming `GET /api/v1/kds/print-jobs/pending`), barcode scanner input, cash drawer trigger (kick via printer or USB-HID), scale integration if needed for weighted items. Printer failover (secondary station/printer if primary is offline) and KDS failover (fallback to a paper ticket or backup station) also live here.
**Covers checklist items:** Printer routing (completing the loop started in Phase B), printer/KDS failover, hardware integrations (scanners, scales, cash drawers), offline/reliability hardware-adjacent concerns.
**Size:** M (the module boundary and job-polling contract already exist from Phase B/desktop-shell work — this phase is "fill in the real driver," not "design the architecture").
**Dependencies:** Hard dependency on Phase B (KDS print-job model, done) and the desktop shell foundation (done, `desktop/src/main/`). Cash-drawer-kick-via-printer depends on Phase C's cash drawer concept existing first (soft dependency — the physical kick can be built standalone, but it's only useful once there's a till session to open).

---

## Phase G — Staff & Labor
**Scope:** Clock-in/out, granular RBAC (cashier/kitchen/manager roles beyond today's single manager-account model), shift scheduling, sales-per-server attribution, tip pooling, payroll export/integration.
**Covers checklist items:** Clock-in/out, RBAC, shift scheduling, sales-per-server, tip pooling, payroll integration, labor cost reporting (feeds Phase I).
**Size:** L (RBAC is a meaningful identity-layer change touching every existing router's auth dependency; clock-in/scheduling/payroll are each independently smaller).
**Dependencies:** Tip pooling depends on Phase C (tipping must exist before it can be pooled). Sales-per-server depends on Phase D or a lighter "who took this order" attribution that could be added standalone. RBAC is otherwise independent and could be pulled forward if multi-branch (Phase J) work needs it sooner.

---

## Phase H — UAE Compliance & E-Invoicing
**Scope:** VAT calculation on order/dish line items (multi-tax support), TRN field on restaurant profile, VAT-compliant invoice generation, UAE Ministry of Finance structured e-invoice format (UBL/PINT-AE) integration with an Accredited Service Provider, tax-specific audit chain (invoice sequence numbering) layered on the existing general-purpose `audit/` module.
**Covers checklist items:** VAT invoice, TRN, e-invoicing (UAE MoF structured-data requirement), Z-report (tax-relevant version), audit trail (tax-specific).
**Size:** L (the tax math and invoice document generation are moderate; the ASP integration and MoF certification/compliance process is the long pole and may involve external vendor onboarding, not just code).
**Dependencies:** **Hard dependency on Phase C** (need real tender/payment records and a till/session to attach a Z-report to) **and on multi-tax support being added to the menu model** (a Menu Management sub-item, small enough to fold into this phase's first milestone rather than its own letter — add `tax_rate` to `Dish`/`Order` line items here). Should not start before Phase C's till/session milestone lands.

---

## Phase I — Reporting & Analytics Expansion
**Scope:** Item performance (best/worst sellers, margin per item), labor cost reports, inventory usage reports, table-turn analytics, custom/configurable report builder — expanding beyond today's fixed `AnalyticsScreen.tsx` panels.
**Covers checklist items:** Item performance, labor cost, inventory usage, peak-hour/table-turn analytics, custom reports.
**Size:** M (mostly aggregation/query work and new dashboard panels; the report-builder UI is the one genuinely new UI investment).
**Dependencies:** Labor cost reporting depends on Phase G (needs labor data to exist). Inventory usage depends on Phase E. Table-turn depends on Phase D. Item performance and a basic custom-report framework can start independently and early, then backfill labor/inventory/table panels as those phases land.

---

## Phase J — Multi-Branch & Franchise
**Scope:** True multi-branch support distinct from today's multi-tenant model — one owner account with a centralized dashboard across several physical branches, branch-level reporting roll-up, franchise-level permission model (builds on Phase G's RBAC).
**Covers checklist items:** Franchise/multi-branch centralized dashboard, mobile POS (as a natural extension once branch-scoped auth exists), multi-location security/reliability.
**Size:** L (this is a data-model change — `manager_users` already flagged as "(Planned)" in `docs/PLATFORM_FEATURES_REFERENCE.md` — touching identity, every tenant-scoped query, and the dashboard's navigation/branch-switcher UX).
**Dependencies:** Builds on Phase G's RBAC work (a branch manager is a role variant of the same permission system). Should follow G, not precede it, to avoid building two overlapping permission models.

---

## Phase K — Omnichannel, CRM & AI Polish
**Scope:** Third-party delivery aggregator integration (Talabat/Deliveroo/Careem order ingestion + reconciliation), gift cards (as a purchasable product distinct from general wallet credit), caller ID / phone-order channel (building on the existing `docs/voice-phone-ordering-reference.md` research and `src/app/speech/`), AI upsell prompts in the conversation engine, AI daily owner summary, AI review reply, AI voice ordering, branded receipts, multi-currency support.
**Covers checklist items:** Third-party delivery integration, aggregator reconciliation, gift cards, caller ID, AI upsell, AI daily owner summary, AI review reply, AI voice ordering, branded receipts, multi-currency, digital signage, accounting/payroll third-party integrations, QR/kiosk (if not pulled into Phase D).
**Size:** XL if taken as one phase — strongly recommend splitting into sub-phases (K1 aggregator integration, K2 gift cards + CRM polish, K3 AI upsell/voice/summary, K4 multi-currency + branded receipts) since these items have little dependency on each other and can be prioritized independently by business value once C-J land.
**Dependencies:** Gift cards can reuse the existing `wallet/` ledger machinery (soft dependency, not blocking). Driver-assignment-for-aggregator-orders depends on Phase A's partner pattern (done) for the integration shape, but is a new inbound-order direction, not an extension of the existing outbound partner webhook system. Everything else in this phase is independent and can be cherry-picked opportunistically.

---

## Sequencing Summary

```
A (done) ─ B (done, KDS)
              │
              ├─→ F (Hardware SDK — fills in B's print-job consumer)
              │
C (Payments/Till/Z-report) ──────────────┬─→ H (UAE Compliance — needs C's till + tax fields)
              │                          │
              ├─→ G (Staff/Labor: tip pooling needs C's tipping)
              │
D (Table/Floor — independent)  E (Inventory/COGS — independent)
              │                          │
              └───────────┬──────────────┴─→ I (Reporting expansion — pulls from D, E, G)
                           │
                           G ──→ J (Multi-Branch — builds on G's RBAC)

K (Omnichannel/CRM/AI polish) — mostly independent, sequence by business value after C/D/E land
```

**Recommended near-term order given current state (A, B done; desktop shell + offline sync in progress):** finish hardening the in-progress desktop offline sync (not a new lettered phase — it's the tail of the existing desktop-shell-foundation work), then **C** (payments/cash drawer unlocks the most downstream value — Z-report, dual pricing, and is the hard blocker for H), then **D** and **E** in parallel (fully independent of each other and of C), then **F** (cheap, mechanical, unblocks real hardware demos), then **H** once C's till model exists, then **G**, **I**, **J**, **K** roughly in that order as business priority dictates.
