# Full POS — Frontend UI/UX Redesign Phases (Complete Inventory)

**Status:** Multi-agent redesign integrated (Phases 0–5 code present; residual hardening gaps listed in §13)  
**Date:** 2026-07-09  
**Product:** Full POS by CatalystIQ  
**Source of truth (UI contract):**

- `~/Downloads/POS_Frontend_UI_UX_Spec_for_Coding_Agent.md` (preferred for agents)
- `~/Downloads/POS_Frontend_UI_UX_Spec_for_Coding_Agent.docx`
- `~/Downloads/POS_Frontend_UI_UX_Spec_for_Coding_Agent.pdf`

**Backend / product rules still governed by:**

- `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`
- Feature catalog / advanced POS status docs

**Delivery model chosen:** Phased shell-first (do not rewrite the app; redesign in place under `frontend/`).

---

## 0. Why this document exists

The UI/UX spec targets **36 screens/surfaces**, a **touch-first design system**, **19 nav items**, **shared components**, **14 catalog feature categories** (~381 capabilities), and a **coding-agent build checklist**.

This document breaks that into **ordered phases** so:

1. Daily staff screens become fast before admin polish.
2. No screen, shell piece, shared component, or feature-placement group is orphaned.
3. Each phase has explicit **scope**, **deliverables**, **acceptance criteria**, **tests**, and a **definition of done**.
4. Later phases never re-open Phase 0 foundations without a written exception.

**Blunt product rule (from spec):** Do not expose 381 features as 381 pages. Group by restaurant tasks: take order, cook, pay, dispatch, manage, report.

---

## 1. Phase map (at a glance)

| Phase | Name | Goal | Primary outputs |
| --- | --- | --- | --- |
| **0** | Design system + AppShell + shared primitives | Touch POS chrome and reusable building blocks | Tokens, shell, nav IA, shared components, route skeleton, role-gate stubs |
| **1** | Auth + existing core ops redesign | Make rush-hour staff screens feel like a real POS | Login, Onboarding, Live Ops, Orders, New Order, KDS, Riders, Chats |
| **2** | Missing core ops surfaces | Close the core operations gap vs 36-screen inventory | Floor Plan, Order Detail route, Checkout/Pay, Expo KDS view |
| **3** | Manager & admin redesign | Tables + drawers + bulk actions for owners | Menu, Item Editor, Modifiers, Inventory+Purchasing, Branches, Customers, Staff, Tickets, Coupons, Marketing, AI, Analytics, Reports, Payments BO, Compliance, Reliability, Settings |
| **4** | Mobile & public surfaces | Customer/rider experiences | Public storefront, QR table ordering, tracking, rider mobile app |
| **5** | Cross-cutting hardening | Offline, a11y, roles, QA load, nothing missed | Global offline states, PIN approvals wired, a11y, rush-hour fixtures, full regression matrix |

**Recommended execution order:** 0 → 1 → 2 → 3 → 4 → 5.  
**Hard rule:** Phase N is not “done” until its exit checklist is checked, even if Phase N+1 has started spikes.

```
Phase 0 (foundation)
   │
   ├─► Phase 1 (existing core ops UX)
   │      │
   │      └─► Phase 2 (new core ops screens)
   │             │
   │             └─► Phase 3 (manager/admin)
   │                    │
   │                    └─► Phase 4 (public/mobile)
   │
   └─► Phase 5 (cross-cutting; starts after Phase 1 for offline badges,
                finishes after Phase 4 for full matrix)
```

---

## 2. Non-negotiable design rules (apply to every phase)

Copy these into every PR description for this redesign:

| Rule | Implementation requirement |
| --- | --- |
| Touch targets | Min **56×56 px**; primary actions **≥64 px** height |
| Typography | Body **≥16 px**; POS/KDS item names **18–22 px**; payment totals **≥28 px** |
| Daily staff UX | Cards, large buttons, sticky bottom actions, drawers — **no dense SaaS tables** |
| Manager UX | Tables allowed; row actions open **drawers** or large menus |
| Danger actions | Void, refund, discount override, stock adjustment, channel pause, settings changes → **confirm or manager PIN** |
| Always visible | Order status, SLA timer, amount due, cart, offline state, printer/channel errors during active work |
| Modals | Short decisions only; long editing → **drawer or full page** |
| Offline | Top-bar badge + Reliability page; core screens show sync limits |
| KDS | Full-screen capable, large tickets, urgency colors, allergy warnings |
| Rider app | One primary action per delivery state; mobile-first |
| Feature placement | Capabilities live as **tabs, drawers, panels, modals** inside the 36 screens — not new top-level pages |

**Layout chrome (global):**

| Element | Spec |
| --- | --- |
| Top status bar | Fixed, **56–64 px**; branch, online/offline, shift, alerts, staff switch, clock |
| Sidebar | **88 px** collapsed / **240 px** expanded; daily screens first; hide by role/license |
| Primary content | Center; 3-pane for operational screens when needed |
| Right drawer | **420–720 px** |
| Bottom action bar | Sticky **72–88 px** for primary task actions |
| Alert center | Top-right: late, low stock, failed sync/payment, channel/printer errors |
| Manager PIN modal | Centered; shows action reason + affected record |
| Toasts | Confirmations only; critical errors = banners |

---

## 3. Master inventory (nothing-missed baselines)

### 3.1 All 36 screens/surfaces

| # | Group | Screen | Route | Exists today? | Phase owner |
| --- | --- | --- | --- | --- | --- |
| 1 | Auth | Login | `/login` | Yes | **1** |
| 2 | Auth | Onboarding | `/onboarding` | Yes | **1** |
| 3 | Core | Live Ops Dashboard | `/` | Yes | **1** |
| 4 | Core | Floor Plan / Table Map | `/floor` | **Yes** (`FloorPlanScreen`) | **2** |
| 5 | Core | Orders List | `/orders` | Yes | **1** |
| 6 | Core | Order Detail | `/orders/:id` | **Yes** (`OrderDetailScreen` + drawer) | **2** |
| 7 | Core | New Order POS | `/new-order` | Yes | **1** |
| 8 | Core | Checkout / Payment | `/orders/:id/pay` | **Yes** (`CheckoutScreen`) | **2** |
| 9 | Core | Kitchen KDS | `/kds`, `/kds/:stationId` | Yes | **1** |
| 10 | Core | Expo / Ready Pickup | `/kds?view=expo` | Partial | **2** |
| 11 | Core | Rider Dispatch | `/riders` | Yes | **1** |
| 12 | Mobile | Rider Mobile App | `/rider-app` | **Yes** (`RiderAppScreen`; track still `/rider-track`) | **4** |
| 13 | Core | WhatsApp Inbox / Chats | `/conversations` | Yes | **1** |
| 14 | Manager | Channels | `/channels` | Yes | **3** |
| 15 | Mobile | Public Storefront | `/order/:slug` | Yes | **4** |
| 16 | Mobile | QR Table Ordering | `/order/:slug?table=` | Partial | **4** |
| 17 | Mobile | Customer Tracking | `/track/:trackingToken` | Yes | **4** |
| 18 | Manager | Menu Management | `/menu` | Yes | **3** |
| 19 | Manager | Item Editor | `/menu/:itemId` or drawer | Partial drawer | **3** |
| 20 | Manager | Modifier Builder | `/menu/modifiers` or drawer tab | Partial | **3** |
| 21 | Manager | Inventory | `/inventory` | Yes | **3** |
| 22 | Manager | Purchasing / GRN / Vendors | `/inventory?tab=purchasing` | Partial | **3** |
| 23 | Manager | Branches HQ | `/branches` | Yes | **3** |
| 24 | Manager | Customers | `/customers` | Yes | **3** |
| 25 | Manager | Customer Profile | `/customers/:id` | Yes | **3** |
| 26 | Manager | Staff | `/staff` | Yes | **3** |
| 27 | Manager | Complaints | `/tickets` | Yes | **3** |
| 28 | Manager | Coupons | `/coupons` | Yes | **3** |
| 29 | Manager | Marketing | `/marketing` | Yes | **3** |
| 30 | Manager | AI Insights | `/ai` | Yes | **3** |
| 31 | Manager | Analytics / Forecast | `/analytics`, `/predictions` | Yes | **3** |
| 32 | Manager | Reports | `/reports` | Yes | **3** |
| 33 | Manager | Payments Back Office | `/payments` | Yes | **3** |
| 34 | Manager | Compliance | `/compliance` | Yes | **3** |
| 35 | Manager | Reliability | `/reliability` | Yes | **3** (+ **5** for global offline) |
| 36 | Manager | Settings | `/settings` | Yes | **3** |

### 3.2 Spec main navigation (order)

| # | Nav item | Route | Phase when nav is correct |
| --- | --- | --- | --- |
| 1 | Live Ops | `/` | **0** (nav structure), **1** (screen) |
| 2 | Floor Plan | `/floor` | **0** (nav link stub), **2** (screen) |
| 3 | Orders | `/orders` | **0/1** |
| 4 | New Order | `/new-order` | **0/1** |
| 5 | Kitchen | `/kds` | **0/1** |
| 6 | Payments | `/payments` | **0/3** |
| 7 | Riders | `/riders` | **0/1** |
| 8 | Chats | `/conversations` | **0/1** |
| 9 | Menu | `/menu` | **0/3** |
| 10 | Inventory | `/inventory` | **0/3** |
| 11 | Customers | `/customers` | **0/3** |
| 12 | Staff | `/staff` | **0/3** |
| 13 | Marketing | `/marketing` | **0/3** |
| 14 | Reports | `/reports` | **0/3** |
| 15 | AI Insights | `/ai` | **0/3** |
| 16 | Branches | `/branches` | **0/3** |
| 17 | Channels | `/channels` | **0/3** |
| 18 | Reliability | `/reliability` | **0/3** |
| 19 | Settings | `/settings` | **0/3** |

**Nested / role-secondary (must still appear somewhere):**

| Item | Preferred placement | Phase |
| --- | --- | --- |
| Compliance | Sidebar for accountant/owner **or** Settings/Reports nested | **0** nav gate, **3** UI |
| Coupons | Sidebar marketing **or** Marketing tab | **0/3** |
| Analytics / Predictions | Sidebar **or** Reports/AI nested | **0/3** |
| Complaints (Tickets) | Sidebar **or** Customers nested | **0/3** |
| Expo view | Kitchen → Expo | **2** |
| Purchasing | Inventory tab | **3** |
| Modifiers | Menu → drawer/tab | **3** |

### 3.3 Catalog feature categories → phase ownership

| Cat | Feature group | Count (approx) | Primary screens | UI placement phase |
| --- | --- | --- | --- | --- |
| 1 | Order management | 32 | Floor, New Order, Orders, Order Detail, Checkout, Payments | **1–2** |
| 2 | Kitchen and preparation | 30 | KDS, Expo, Reports, Reliability | **1–2**, Reports **3** |
| 3 | Menu and item control | 35 | Menu, Item Editor, Modifiers | **3** |
| 4 | Inventory and food-cost | 29 | Inventory, Purchasing, Branches, Reports | **3** |
| 5 | Payment and billing | 34 | Checkout, Payments BO, Settings, Compliance | **2–3** |
| 6 | Customer, CRM, loyalty | 31 | Customers, Profile, Tickets, Marketing, Reports | **3** |
| 7 | Delivery management | 29 | Live Ops, Riders, Rider App, New Order | **1, 4** |
| 8 | Aggregator and channels | 22 | Channels, Public Storefront, Reports | **3–4** |
| 9 | Staff and permissions | 22 | Staff, PIN modal, Payments drawer | **0** (PIN shell), **3** |
| 10 | Reporting and owner dashboard | 34 | Reports, Analytics | **3** |
| 11 | Multi-branch and franchise | 19 | Branches + cross-links | **3** |
| 12 | Offline, backup, reliability | 19 | Reliability + top bar + core banners | **0** badge, **3** page, **5** global |
| 13 | Compliance and UAE | 20 | Compliance, Reliability audit | **3** |
| 14 | AI features | 25 | AI Insights + Chats/Menu/Marketing/Inventory hooks | **1** (chats AI state), **3** (insights) |

### 3.4 Spec shared components (build once)

| Component | Phase 0 required? | Used heavily by |
| --- | --- | --- |
| TouchButton (extends Button) | **Yes** | All ops screens |
| StatusChip / StatusPill | **Yes** | Orders, Live Ops, KDS |
| OrderCard | **Yes** | Live Ops, Orders |
| KdsTicketCard | **Yes** | KDS, Expo |
| MoneySummary | **Yes** | Checkout, Order Detail, Payments |
| Drawer (SideDrawer) | **Yes** | Most manager + ops detail |
| Modal / ConfirmDialog | **Yes** | Short decisions |
| ApprovalPinModal | **Yes** | Danger actions |
| DataTable / CompactTable | **Yes** | Manager screens |
| EmptyState | **Yes** | All lists |
| ErrorState | **Yes** | All lists |
| AlertCenter | **Yes** | Shell |
| BottomActionBar | **Yes** | Ops screens |
| SlaLaneBoard / LiveOrderCard | Phase **1** | Live Ops |
| TenderGrid / NumericKeypad | Phase **2** | Checkout |
| FloorZoneTabs / TouchTableCard | Phase **2** | Floor Plan |
| ChannelCardGrid | Phase **3** | Channels |
| AiInsightCardGrid | Phase **3** | AI Insights |
| Rider task cards | Phase **4** | Rider App |

### 3.5 Coding-agent build checklist → phase map

| Spec checklist item | Phase |
| --- | --- |
| Design tokens (spacing, type, color, touch, shadow, radius) | **0** |
| AppShell: top bar, sidebar, alert center, branch, staff PIN switch, offline badge | **0** |
| Shared components before pages | **0** |
| Routing + role gates for all 36 surfaces | **0** skeleton; **2/4** fill missing routes; **5** enforce roles |
| Core ops first | **1–2** |
| Manager screens second | **3** |
| Public/mobile third | **4** |
| Offline states across core screens | **5** (badge in **0**, full in **5**) |
| Accessibility | **5** (focus rings baseline in **0**) |
| Rush-hour QA data (100 orders, 20 riders, 8 channels, 6 stations, 5 branches) | **5** |

---

## 4. Phase 0 — Design system, AppShell, shared primitives

### 4.1 Goal

Establish the touch-first POS foundation so every later screen inherits correct chrome, tokens, and components. **No full screen redesign yet** beyond shell wiring and smoke routes.

### 4.2 In scope

#### Design tokens (`frontend/src/styles/tokens.css`, `base.css`, `fonts.css`)

- [ ] Canvas/surface/border/text tokens (keep light POS professional theme)
- [ ] SLA + status color tokens
- [ ] Accent tokens (primary, dispatch, rider, revenue, AI)
- [ ] Spacing scale; radius; shadows
- [ ] **Touch size tokens:** `--touch-min: 56px`, `--touch-primary: 64px`
- [ ] **Type scale:** body 16, UI 14–16, item 18–22, total ≥28, mono for money/IDs
- [ ] Layout tokens: topbar 56–64, nav 88/240, bottom bar 72–88, drawer 420–720
- [ ] Focus ring token for a11y baseline
- [ ] Unit tests for token contracts (`tokens.test.ts`)

#### AppShell

- [ ] Top status bar: branch selector (or stub), online/offline, shift indicator (or stub), clock, staff switch entry, alert center trigger
- [ ] Sidebar: collapsible 88/240; **spec nav order**; daily group first; manager below
- [ ] Hide/disable modules by role/license hooks (stub OK if auth lacks fine roles yet — document stubs)
- [ ] Floor Plan nav entry present (route may 404 or “coming soon” until Phase 2)
- [ ] Primary content region with optional right-drawer host
- [ ] Bottom action bar **slot** (screens opt in)
- [ ] Desktop status bar retained (local/online/pending)
- [ ] Offline badge always visible when offline/pending sync
- [ ] Sync conflict banner retained

#### Shared components (minimum set)

- [ ] `TouchButton` (primary / ghost / danger / size variants meeting 56–64)
- [ ] `StatusChip`
- [ ] `OrderCard` (status, channel, time, customer, amount)
- [ ] `KdsTicketCard` skeleton
- [ ] `MoneySummary`
- [ ] `Drawer` polish (420–720)
- [ ] `Modal` + `ConfirmDialog`
- [ ] `ApprovalPinModal` (UI + callback contract; wiring in later phases)
- [ ] `DataTable` touch-safe row actions
- [ ] `EmptyState`, `ErrorState`
- [ ] `AlertCenter` (panel UI; data sources can be stubbed)

#### Routing skeleton

- [ ] Register routes for all 36 surfaces (missing ones can render `ComingSoon` or redirect with flag)
- [ ] Public routes remain unguarded: `/login`, `/order/:slug`, `/track/:token`, `/rider-app`, rider-track if still needed
- [ ] Document route map in this plan (Section 3.1)

### 4.3 Out of scope

- Visual redesign of Live Ops / New Order content layout (Phase 1)
- Full Floor Plan / Checkout logic (Phase 2)
- Manager table deep redesign (Phase 3)
- Backend API changes unless required for branch/staff switch stubs

### 4.4 Tests

- [ ] Token unit tests
- [ ] NavSidebar tests (order, collapse, active state)
- [ ] AppShell smoke (renders children, offline badge, alert button)
- [ ] ApprovalPinModal unit tests
- [ ] Existing e2e smoke still passes (update selectors if chrome changed)

### 4.5 Exit criteria (Definition of Done)

- [ ] Body font ≥16 px on authenticated app shell
- [ ] Primary buttons ≥64 px height in shared TouchButton
- [ ] Sidebar matches spec order; collapse works
- [ ] All 36 routes resolve without blank crash
- [ ] No regression in login → Live Ops happy path
- [ ] `understanding.txt` updated

---

## 5. Phase 1 — Auth + existing core operations redesign

### 5.1 Goal

Redesign the **existing** daily screens staff use under rush hour. These must be faster and clearer than a normal SaaS dashboard.

### 5.2 Screens (detailed)

#### 1) Login `/login`

| Spec zone | Deliverable |
| --- | --- |
| Layout | Centered card max 440 px; logo; device name |
| Modes | Email/password + **PIN pad** for staff |
| Actions | Sign in, switch PIN, create account link, reset password, support |
| Offline | Cloud login blocked offline; cached staff PIN if configured (desktop) |
| Components | AuthForm, PinLoginPad, DeviceNameField, RememberDeviceToggle, ErrorBanner |

Checklist:

- [ ] Touch-friendly number pad
- [ ] Exact error messages (no stack traces)
- [ ] Offline PIN path documented/tested where desktop env exists

#### 2) Onboarding `/onboarding`

| Spec zone | Deliverable |
| --- | --- |
| Layout | Wizard left / panel center / validation right |
| Steps | Profile, branch location, tax, hours, WhatsApp, menu import, payment, device |
| Sticky | Back, Save draft, Continue |

Checklist:

- [ ] Not one long form
- [ ] Blockers before finish
- [ ] Draft save without losing progress

#### 3) Live Ops `/`

| Spec zone | Deliverable |
| --- | --- |
| Left | SLA lanes by status/channel |
| Center | Order board: New / Preparing / Ready / Out for Delivery / **Late** |
| Right | Dispatch map, rider strip, urgent alerts |
| Bottom | New Order, Open Orders, Send Owner Report, Pause Channel |

Components: SlaLaneBoard, LiveOrderCard, ChannelBadge, DispatchMap, RiderStatusStrip, AlertCenter, QuickActionBar  

Checklist:

- [ ] No spreadsheet layout
- [ ] Late orders visually unavoidable
- [ ] Bottom actions reachable

#### 4) Orders List `/orders`

| Spec zone | Deliverable |
| --- | --- |
| Top | Status tabs, channel chips, date, search |
| Left | Saved views: Today, Late, Refunds, Scheduled, Aggregator, WhatsApp |
| Center | **Card default**; optional manager table mode |
| Right | Preview drawer |

Checklist:

- [ ] Phone + order number search
- [ ] Status, channel, time, customer, amount always visible on card
- [ ] Bulk print/assign bar (wired or clearly disabled with reason)

#### 5) New Order POS `/new-order`

| Spec zone | Deliverable |
| --- | --- |
| Top | Order type: Dine-in, Takeaway, Delivery, QR, Call Center, Aggregator manual |
| Left | Category rail large icons |
| Center | Item grid, search, favorites |
| Right | Cart + customer/table/address + notes |
| Bottom | Hold, Clear, Send to Kitchen, Pay, Print KOT |

Checklist:

- [ ] Large item buttons
- [ ] Cart always visible
- [ ] Modifier popup does not cover payment actions after selection
- [ ] Delivery address: building, floor, apartment, pin

#### 6) Kitchen KDS `/kds`, `/kds/:stationId`

| Spec zone | Deliverable |
| --- | --- |
| Shell | Full-screen mode; sidebar hideable |
| Top | Station tabs, time, printer/KDS status, order-type filter |
| Center | Ticket columns; large text; modifiers; allergen banner; timer |
| Actions | Start, Ready/Bump, Recall, Missing, QC, packaging checklist |

Checklist:

- [ ] Gloves/wet-hand sized controls
- [ ] Readable at distance
- [ ] Allergy warnings impossible to miss
- [ ] Printer/fallback status visible

#### 7) Rider Dispatch `/riders`

| Spec zone | Deliverable |
| --- | --- |
| Top | Availability, active deliveries, COD total, late risk |
| Left | Unassigned queue + SLA |
| Center | Map: riders, pins, batch routes |
| Right | Selected rider/order detail |
| Bottom | Auto Assign, Manual Assign, Priority, Settle COD |

Checklist:

- [ ] Map + queue (not table-only)
- [ ] Late risk before late
- [ ] COD per rider visible

#### 8) WhatsApp Inbox `/conversations`

| Spec zone | Deliverable |
| --- | --- |
| Left | Filters: Active, AI Handling, Needs Staff, Complaints, Stopped Marketing |
| Center | Transcript, media, voice notes |
| Right | Customer context, cart, last orders, wallet, allergies, complaints |
| Bottom | Reply, quick replies, takeover, reset AI |

Checklist:

- [ ] Human takeover obvious
- [ ] AI state on every conversation
- [ ] Allergy + VIP in side panel
- [ ] STOP marketing displayed and respected

### 5.3 Feature categories touched

- Cat 1 (order create/list paths), Cat 2 (KDS), Cat 7 (dispatch), Cat 14 (chat AI control surface)

### 5.4 Tests

- [ ] Unit/Vitest updates per screen
- [ ] e2e: smoke, orders flow, tickets drawer if impacted
- [ ] Manual rush-hour checklist (10+ open orders, late SLA visible)

### 5.5 Exit criteria

- [ ] Spec design checklists for screens 1–3, 5, 7, 9, 11, 13 marked done in implementation notes
- [ ] Bottom action bars present on Live Ops, New Order, Riders (and KDS ticket actions large)
- [ ] No dense table as default on Live Ops / New Order / KDS
- [ ] Existing API contracts unchanged unless unavoidable
- [ ] `understanding.txt` updated

---

## 6. Phase 2 — Missing core operations surfaces

### 6.1 Goal

Complete the **core operations** set from the 36-screen inventory so staff can take order → cook → pay → handoff without leaving the POS task model.

### 6.2 Screens

#### 4) Floor Plan `/floor`

| Spec zone | Deliverable |
| --- | --- |
| Top | Zone tabs (Main Hall, Patio, Family, Private Room) |
| Center | Drag-friendly table map, status colors, legend |
| Right | Selected table drawer: orders, guests, waiter, bill |
| Bottom | New Table Order, Transfer, Merge, Split Bill, Print Bill |

Features to place: dine-in, tableside, transfer, merge, split by seat/item  

Checklist:

- [ ] Large touch table cards
- [ ] Status without opening table
- [ ] Transfer/merge confirmation
- [ ] Split bill from table + checkout path

**Backend note:** If table/floor APIs are incomplete, implement UI against existing design docs (`2026-07-07-table-floor-management-design.md`) with clear mock/feature flags — do not invent permanent fake FSMs.

#### 6) Order Detail `/orders/:id`

| Spec zone | Deliverable |
| --- | --- |
| Top | Number, status, channel, SLA, payment state |
| Left | Customer/table/delivery + notes |
| Center | Items, modifiers, notes, allergy, course status |
| Right | Timeline, kitchen state, rider state, payment summary |
| Bottom | State-dependent: Edit, Send Kitchen, Pay, Refund, Assign Rider, Print, More |

Danger actions behind **More + ApprovalPinModal**  

Features: edit after kitchen, partial cancel, void, rush/priority, duplicate, transfer staff, item/kitchen/allergy notes, courses  

Checklist:

- [ ] Item actions separate from order actions
- [ ] Timeline who/what/when
- [ ] Invalid post-ready changes blocked in UI

#### 8) Checkout / Payment `/orders/:id/pay`

| Spec zone | Deliverable |
| --- | --- |
| Left | Bill items, split, charges, discounts |
| Center | Tender grid: Cash, Card, Tap, Apple Pay, Google Pay, Online, Link, Gift Card, Wallet |
| Right | Amount due, keypad, loyalty, change due |
| Bottom | Confirm, Print, Email/WhatsApp receipt, Open drawer |

Components: BillSummary, SplitPaymentPanel, TenderGrid, NumericKeypad, DiscountModal, TipSelector, LoyaltyRedeemCard, ReceiptPreviewDrawer  

Checklist:

- [ ] Amount due always visible
- [ ] Split mode obvious/reversible
- [ ] Discounts/refunds role-checked
- [ ] Large tender buttons

#### 10) Expo / Ready Pickup `/kds?view=expo`

| Spec zone | Deliverable |
| --- | --- |
| Top | Ready count, delayed count, pickup filter |
| Center | Ready tickets by dine-in / takeaway / delivery / aggregator |
| Right | Packaging checklist + missing item confirmation |
| Bottom | Hand to Rider, Customer Picked Up, Reopen |

Checklist:

- [ ] Ready separated from prep
- [ ] Packaging required when setting enabled
- [ ] Handoff updates timeline / WhatsApp where API allows

### 6.3 Feature categories closed here

- Remaining Cat 1 order-management placements (void, split, merge, transfer)
- Remaining Cat 2 expo/packaging/QC
- Cat 5 checkout tenders (back-office still Phase 3)

### 6.4 Tests

- [ ] Route tests for `/floor`, `/orders/:id`, `/orders/:id/pay`, expo query
- [ ] PIN modal on void/refund path
- [ ] e2e critical path: create order → open detail → pay (happy path)

### 6.5 Exit criteria

- [ ] All **core operations** rows (screens 3–11, 13) in Section 3.1 are Implemented (not stub)
- [ ] Spec checklists for Floor, Order Detail, Checkout, Expo done
- [ ] Nav Floor Plan no longer “coming soon”
- [ ] `understanding.txt` updated

---

## 7. Phase 3 — Manager & admin redesign

### 7.1 Goal

Redesign owner/manager surfaces: tables + filters + exports + drawers. Do not pollute cashier flows with compliance/settings density.

### 7.2 Screens and required layout zones

For each screen below, implementation must cover **Layout zones**, **Main components**, **Primary actions**, and **Design checklist** from the UI/UX MD spec. Summaries:

| # | Screen | Route | Must include |
| --- | --- | --- | --- |
| 14 | Channels | `/channels` | Health summary, channel cards, credential drawer, sync, pause (no delete for pause) |
| 18 | Menu | `/menu` | Category tree, item grid/table, bulk actions, approval banner, item drawer |
| 19 | Item Editor | drawer / `/menu/:itemId` | Tabs: Basics, Pricing, Variants, Modifiers, Recipe, Availability, Media, Languages, Compliance; sticky Save |
| 20 | Modifier Builder | `/menu/modifiers` or tab | Groups list, min/max rules, POS + public live preview |
| 21 | Inventory | `/inventory` | KPIs, low stock banner, stock table, item drawer, waste + adjustment approval |
| 22 | Purchasing | `?tab=purchasing` | Suppliers, POs, GRN, vendor prices |
| 23 | Branches HQ | `/branches` | KPI cards, branch grid/table, detail drawer, bulk bar; hide if single-branch |
| 24 | Customers | `/customers` | Phone search first, segments, cards/table, preview drawer |
| 25 | Customer Profile | `/customers/:id` | VIP/allergy header, tabs Orders/Loyalty/Complaints/Refunds/Feedback/Offers, reorder one-tap |
| 26 | Staff | `/staff` | Tabs List/Roles/Shifts/Attendance/Tips/Performance/Training; PIN only for managers; training mode visible |
| 27 | Complaints | `/tickets` | Queue, evidence, resolution, customer/order context, escalate |
| 28 | Coupons | `/coupons` | Margin warning, builder drawer, pause > delete, usage limits required |
| 29 | Marketing | `/marketing` | Tabs Templates/Campaigns/Segments/Automations/Broadcast/Images; STOP exclusion default |
| 30 | AI Insights | `/ai` | Category chips, insight cards with evidence + confidence + **action** buttons; no auto-apply risky changes |
| 31 | Analytics/Forecast | `/analytics`, `/predictions` | Horizon explicit, charts + table fallback, KPIs link to source |
| 32 | Reports | `/reports` | Category nav Sales/Menu/Customers/Staff/Inventory/Delivery/Tax/Cash; export every report; owner WhatsApp panel |
| 33 | Payments BO | `/payments` | Tabs Transactions/Refunds/Links/Drawer/Reconciliation/Gift Cards/Billing; separate from fast checkout |
| 34 | Compliance | `/compliance` | Tax profile, invoice types, credit notes, e-invoice readiness, audit, accountant export; AR/EN preview |
| 35 | Reliability | `/reliability` | Health cards Network/Devices/Printers/KDS/Backups/Sync/Errors/Audit; conflict resolve; restore preview |
| 36 | Settings | `/settings` | Category nav + form + help/preview; sticky Save; confirmation on danger; UAE delivery defaults |

### 7.3 Feature categories closed here

- Cat 3, 4, 5 (back office), 6, 8 (manager), 9–14 as UI placement (not necessarily every backend capability if already partial — UI must still **host** the access path)

### 7.4 Per-screen design checklist discipline

Do not mark a manager screen done until:

- [ ] Spec layout zones implemented or explicitly deferred with ticket ID
- [ ] Primary actions reachable without nested “settings inside settings”
- [ ] Row actions open drawer (not tiny icon-only controls)
- [ ] Vitest coverage for critical interactions
- [ ] Dangerous actions call ApprovalPinModal or ConfirmDialog

### 7.5 Exit criteria

- [ ] Screens 14, 18–36 redesigned to shell + layout contract
- [ ] Menu item editor sticky save; dish number + price validation; description line limit enforced in UI
- [ ] Compliance not mixed into cashier checkout
- [ ] Branches hidden/simplified for single-branch tenants
- [ ] `understanding.txt` updated

---

## 8. Phase 4 — Mobile & public surfaces

### 8.1 Goal

Customer and rider experiences that are mobile-first and uncluttered.

### 8.2 Screens

#### 12) Rider Mobile App `/rider-app`

| Spec zone | Deliverable |
| --- | --- |
| Top | Rider status, today COD |
| Center | Task cards sequence; detail: address, phone, map, payment due, notes |
| Bottom sticky | One primary: Picked Up → Arriving → Delivered / Failed |

Also: OTP, proof photo, failure reason required, GPS status  

Checklist:

- [ ] One primary action at a time
- [ ] COD + notes before delivery
- [ ] Failure reason mandatory for undeliverable

#### 15) Public Storefront `/order/:slug`

- Mobile-first menu, categories, item detail (image, modifiers, allergens)
- Cart bottom sheet always reachable
- Closed restaurant state clear
- Coupon/wallet where applicable

#### 16) QR Table Ordering `/order/:slug?table=`

- Table locked banner (customer cannot change table)
- Optional dine-in/QR-only menu
- Send to kitchen → appears on KDS + Floor Plan

#### 17) Customer Tracking `/track/:trackingToken`

- Status + simple ETA language
- Rider map only when assigned/out for delivery
- No internal kitchen details
- Contact restaurant / report issue

### 8.3 Feature categories

- Cat 7 remaining rider-app features
- Cat 8 public ordering surfaces
- Cat 14 public ETA explanation if exposed

### 8.4 Exit criteria

- [ ] All mobile/public rows in Section 3.1 Implemented
- [ ] QR table lock enforced in UI
- [ ] Rider app usable on phone viewport (375px)
- [ ] `understanding.txt` updated

---

## 9. Phase 5 — Cross-cutting hardening (nothing left on the floor)

### 9.1 Goal

Close global concerns that are easy to miss if only done “on one page.”

### 9.2 Workstreams

#### A. Offline & reliability across core screens

- [x] Top bar offline/pending always accurate
- [x] New Order / Orders / KDS / Payments show offline limits (what works / what doesn’t)
- [ ] Printer/channel error banners on relevant screens
- [x] Conflict resolution entry points from core screens → Reliability
- [x] Desktop local queue messaging consistent

#### B. Role, license, and navigation gates

- [x] Sidebar hides modules by role
- [x] Routes redirect with friendly “no access” state
- [x] Training mode visual chrome when enabled
- [ ] Staff PIN switch works in shell
- [ ] Branch selector wired when multi-branch

#### C. Manager PIN & danger actions matrix

Wire ApprovalPinModal for at least:

- [x] Void order
- [x] Refund / partial refund
- [x] Discount override (staff/manager)
- [x] Stock adjustment
- [x] Channel pause (if policy requires)
- [ ] Sensitive settings save

Each modal shows: action name, reason field if required, affected record id.

#### D. Accessibility

- [x] Visible focus ring everywhere
- [x] Icon-only controls have `aria-label`
- [x] Contrast AA on primary text/buttons
- [ ] Keyboard reachability for manager screens
- [x] Reduced motion respected for non-essential animation

#### E. QA / fixtures / performance

- [x] Rush-hour fixture pack: **100 live orders, 20 riders, 8 channels, 6 stations, 5 branches**
- [ ] Live Ops remains usable under that load (no frozen UI; virtualize lists if needed)
- [x] Vitest suite green
- [x] Playwright e2e suite green (smoke + critical POS paths)
- [ ] Optional: dashboard latency e2e still within budget

#### F. Final nothing-missed audit

Run these audits and attach results to `understanding.txt`:

1. **36-screen audit** — Section 3.1 all Implemented  
2. **19-nav audit** — order + visibility  
3. **14-category placement audit** — every feature group has a primary UI location  
4. **Coding-agent checklist** — Section 3.5 all checked  
5. **Always-visible states audit** — cart/SLA/amount/offline on active ops screens  
6. **Danger-action audit** — PIN/confirm matrix  
7. **Spec design checklist audit** — per-screen checklists from MD spec  

### 9.3 Exit criteria (program complete)

- [ ] All audits above pass or have explicitly accepted waivers with owner + date
- [ ] No “coming soon” for any of the 36 screens
- [ ] Frontend redesign complete note in `understanding.txt` with date/time
- [ ] Graphify update if project rules require (`graphify-out` refresh)

---

## 10. Per-phase quality gates (standard template)

Every phase PR batch must satisfy:

| Gate | Requirement |
| --- | --- |
| Spec alignment | Diff maps to screens in this doc |
| TDD / tests | Vitest for new components; update existing tests |
| Regression | `frontend` unit tests + relevant e2e |
| No hallucination | UI only claims actions backend supports; else disabled + tooltip |
| Tokens only | No hard-coded one-off colors/sizes outside tokens without reason |
| Shell respect | Screens use BottomActionBar / Drawer patterns, not ad-hoc footers |
| Docs | Update `understanding.txt` after code changes |
| Commit style | Conventional commits (`feat(ui):`, `chore(ui):`) |

---

## 11. Suggested implementation work packages (tickets)

Use this to cut tickets without losing coverage:

### Phase 0 tickets

1. Tokens + base typography/touch  
2. AppShell top bar + offline + clock + branch/staff slots  
3. NavSidebar reorder + collapse 88/240  
4. AlertCenter shell  
5. TouchButton / MoneySummary / Empty/Error  
6. ApprovalPinModal  
7. Route skeleton for missing surfaces  
8. Vitest + smoke e2e green  

### Phase 1 tickets

9. Login PIN + offline messaging  
10. Onboarding wizard layout  
11. Live Ops 3-pane + bottom actions  
12. Orders cards + drawer + search  
13. New Order grid/cart/bottom bar  
14. KDS full-screen + ticket cards  
15. Riders map+queue  
16. Conversations 3-pane AI takeover  

### Phase 2 tickets

17. Floor Plan screen  
18. Order Detail full page/route  
19. Checkout tender grid  
20. Expo view  
21. Wire PIN on void/refund from Order Detail  

### Phase 3 tickets (group by domain)

22. Menu + Item Editor + Modifiers  
23. Inventory + Purchasing  
24. Customers + Profile  
25. Staff + roles/PIN UI  
26. Tickets + Coupons  
27. Marketing  
28. AI Insights  
29. Analytics + Reports  
30. Payments BO  
31. Channels  
32. Branches  
33. Compliance  
34. Reliability  
35. Settings  

### Phase 4 tickets

36. Public storefront redesign  
37. QR table lock UX  
38. Tracking page polish  
39. Rider mobile app `/rider-app`  

### Phase 5 tickets

40. Global offline banners on core screens  
41. Role/license nav enforcement  
42. Danger-action PIN matrix completion  
43. A11y pass  
44. Rush-hour fixtures + perf  
45. Final 7-audit report  

---

## 12. Explicit deferrals / risks (track, do not forget)

| Item | Risk | Mitigation |
| --- | --- | --- |
| Floor Plan backend incomplete | UI without data | Feature flag + design-doc API contract |
| Multi-tender / Apple Pay / etc. | Provider not wired | Show tenders; disable unavailable with reason |
| Fine-grained RBAC | Roles may be coarse today | Stub gates; Phase 5 hardens |
| Single-branch restaurants | Branches nav clutter | Auto-hide Branches unless multi-branch or flag |
| Electron desktop offline PIN | Desktop-only path | Test behind `isDesktopShell()` |
| 381 features | Scope explosion | Placement = access path in UI; backend may still be partial |
| Graphify / multi-agent rules | Process overhead | Run graph update after each phase merge if required by Claude.md |

---

## 13. Progress tracker (update as phases complete)

| Phase | Status | Start | End | Notes |
| --- | --- | --- | --- | --- |
| 0 Foundation | **Complete** | 2026-07-09 | 2026-07-09 | Tokens, shell, nav, shared primitives (TouchButton, ApprovalPinModal, AlertCenter, BottomActionBar, Empty/Error/MoneySummary), route skeleton |
| 1 Auth + existing core ops | **Integrated (multi-agent)** | 2026-07-09 | 2026-07-09 | Login, Onboarding, LiveOps, Orders, NewOrder, KDS, Riders, Conversations touch-first redesigns |
| 2 Missing core ops | **Integrated (multi-agent)** | 2026-07-09 | 2026-07-09 | FloorPlan `/floor`, OrderDetail `/orders/:id`, Checkout `/orders/:id/pay` (+ tests); Expo KDS view partial via existing KDS |
| 3 Manager & admin | **Integrated (multi-agent)** | 2026-07-09 | 2026-07-09 | Touch/CSS + layout polish across Menu, Inventory, Customers/Profile, Staff, Tickets, Coupons, Marketing, AI, Analytics, Reports, Payments, Channels, Branches, Compliance, Reliability, Settings |
| 4 Mobile & public | **Integrated (multi-agent)** | 2026-07-09 | 2026-07-09 | PublicStore, PublicTracking, RiderApp `/rider-app` (+ tests); QR table param still partial |
| 5 Hardening & final audit | **Integrated (multi-agent)** | 2026-07-09 | 2026-07-09 | Offline banners + useOfflineStatus; RBAC nav gates + NoAccessScreen; PIN matrix (void/refund/discount/stock/channel pause); a11y focus/aria/reduced-motion; rushHour fixtures; e2e smoke chrome. Residual: in-shell staff PIN switch, Settings PIN, list virtualization under load, formal 7-audit pack, QR table lock, Expo KDS deep polish |

**Integration snapshot (2026-07-09 22:49 +04):** orchestrator confirmed App.tsx real screens (no ComingSoon for Phase 2/4 routes); fixed pre-existing `OrderDetailDrawer`/`DishEditModal` tsc errors; **vitest 346 passed / 86 files**; **`tsc --noEmit` clean**.

**Phase 5 integration snapshot (2026-07-09 23:10 +04):** agents 5A–5E landed; AppShell offline + navAccess/training coexist; no merge conflicts; **vitest 409 passed / 95 files**; **`tsc --noEmit` clean**. Residual gaps: TopBar staff PIN switch still stub; Settings sensitive-save PIN not wired; rushHour not virtualized into LiveOps production path; formal Section 9.2F 7-audit report not attached as separate pack; printer/channel error banners partial (channel pause PIN only); branch selector multi-branch wiring still stub.

---

## 14. Final frontend instruction (from spec — acceptance mantra)

> Build this POS like a real restaurant tool, not a generic admin panel.  
> The fastest screens must be **New Order, Checkout, KDS, Floor Plan, Order Detail, and Rider Dispatch**.  
> If those are slow or visually cluttered, the product fails even if every advanced feature exists.

Phase order exists to protect that mantra: **foundation → speed of core ops → complete core → managers → public → harden**.

---

## 15. Document control

| Field | Value |
| --- | --- |
| Version | 1.0 |
| Authoring date | 2026-07-09 |
| Related UI spec version | 1.0 (2026-07-09 catalog date) |
| Delivery model | Phased shell-first |
| Next step after approval | Write Phase 0 implementation plan (task-level TDD) and begin coding |

**Approval:** Review this phases document. When approved, Phase 0 implementation planning starts; no phase is skipped without updating Section 13 and Section 12 waivers.
