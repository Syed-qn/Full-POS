# Role-Based Screens Implementation Plan

> **For agentic workers:** Use subagent-driven development or execute phase-by-phase. Tasks use checkbox (`- [x]`) syntax. Do not invent features outside `docs/ROLE_SCREEN_FEATURE_PLACEMENT.md` and `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md`.

**Goal:** Deliver **four role experiences** (Waiter, Cashier, Kitchen, Owner) with correct home screens, nav, and feature access — so quantity/instructions live on waiter order flow, bill/pay on cashier, cook/ready on kitchen, and full admin on owner.

**Architecture:** Keep one React app (`frontend/`). Prefer **role modes + landings + chrome variants** over four separate codebases. Reuse existing screens (`FloorPlanScreen`, `NewOrderScreen`, `OrderDetailScreen`, `CheckoutScreen`, `KdsScreen`, `LiveOpsScreen`, `PaymentsScreen`). Extend `navAccess.ts` with `waiter` and role-default routes; optional thin wrappers under `/waiter`, `/cashier` only if mode flags on shared screens are insufficient.

**Tech stack:** React 18, Vite, CSS modules, React Router, Vitest, Playwright (vendored), FastAPI staff JWT roles (backend allow-list if needed).

**Parent docs:**

| Doc | Role |
|-----|------|
| `docs/ROLE_SCREEN_FEATURE_PLACEMENT.md` | **SSOT** — feature → role → screen |
| `docs/ADVANCED_POS_FEATURE_IMPLEMENTATION_STATUS.md` | Feature evidence |
| `docs/FULL_PRODUCT_FEATURE_CATALOG.md` | User catalog |
| `docs/superpowers/plans/2026-07-09-pos-frontend-uiux-redesign-phases.md` | Shell / 36-screen IA |

---

## Phase map

| Phase | Name | Outcome | Depends on |
|-------|------|---------|------------|
| **R0** | Foundations | Role types, landing helper, shell mode API, tests | — |
| **R1** | Role gates + landings | `waiter` role; PIN login lands correctly; nav filtered | R0 |
| **R2** | Waiter experience | Floor-first; qty/notes/modifiers; hide pay/void | R1 |
| **R3** | Cashier experience | Terminal + bill/pay CTAs; drawer | R1 |
| **R4** | Kitchen experience | Fullscreen KDS + Expo defaults | R1 |
| **R5** | Owner experience | Live Ops home; admin nav; alerts/PIN polish | R1 |
| **R6** | Hardening | Staff switch, e2e per role, placement audit | R2–R5 |

```
R0 → R1 → R2 (Waiter)
         → R3 (Cashier)   } parallel after R1
         → R4 (Kitchen)
         → R5 (Owner)
              ↓
             R6
```

**Hard rules:**

1. Placement SSOT is `ROLE_SCREEN_FEATURE_PLACEMENT.md` (P / S / S-PIN / H).
2. Waiter never gets tender grid or unprompted void/refund.
3. Kitchen never creates orders or takes payment.
4. Owner keeps PIN on danger actions (`requireManagerPin`).
5. Do not expose 381 features as 381 pages.

---

## Current baseline (reuse)

| Asset | Path | Use |
|-------|------|-----|
| Role gates | `frontend/src/lib/navAccess.ts` | Extend with `waiter`, landings |
| PIN gate | `frontend/src/lib/requireManagerPin.tsx` | Cashier/owner danger |
| Shell | `AppShell.tsx`, `NavSidebar.tsx`, `TopBar.tsx` | Role chrome modes |
| Floor | `screens/FloorPlanScreen.tsx` | Waiter home |
| Order | `screens/NewOrderScreen.tsx` | Waiter/Cashier modes |
| Detail | `screens/OrderDetailScreen.tsx` | Modify / actions by role |
| Checkout | `screens/CheckoutScreen.tsx` | Cashier bill |
| KDS | `screens/KdsScreen.tsx` | Kitchen home + Expo |
| Live Ops | `screens/LiveOpsScreen.tsx` | Owner home |
| Staff model | `src/app/staff/models.py` (`role` string) | Allow `waiter` |
| Staff login | Login PIN path + JWT `role` claim | Session meta |

---

## Phase R0 — Foundations

**Goal:** Shared helpers so later phases only wire UI.

### Deliverables

- [x] Extend `StaffRole` with `"waiter"` in `navAccess.ts` (+ `KNOWN_ROLES`).
- [x] Add `getRoleHomePath(role): string`:
  - `waiter` → `/floor`
  - `cashier` → `/new-order`
  - `kitchen` → `/kds`
  - `owner` / `manager` / `null` → `/`
  - `staff` → `/floor` (legacy floor staff)
  - `rider` → `/riders` or `/rider-app` (existing)
- [x] Add `getRoleChrome(role): { showSidebar, showBottomBarDefault, mode }`.
- [x] Add query/context flag `roleMode` or derive from `getSessionRole()` only (prefer session, no fake query in prod).
- [x] Unit tests: `navAccess.test.ts` landings + waiter known role.

### Files

| Path | Action |
|------|--------|
| `frontend/src/lib/navAccess.ts` | Extend |
| `frontend/src/lib/navAccess.test.ts` | Extend |
| Optional `frontend/src/lib/roleChrome.ts` | New if chrome helpers grow |

### Exit criteria

- [x] All roles resolve a home path.
- [x] Vitest for landings green.
- [x] No UI behavior change yet (except tests).

---

## Phase R1 — Role gates + landings

**Goal:** After PIN/email login, user lands on role home and only sees allowed nav.

### Deliverables

- [x] Update `ROUTE_ROLE_MAP`:
  - `waiter`: `/`, `/floor`, `/orders`, `/new-order`, `/orders/:id` (not pay as primary); hide menu/inventory/staff/marketing/reports/ai/branches/channels/settings/compliance/coupons/analytics.
  - Align `cashier`, `kitchen` with placement doc (already partial).
- [x] Post-login redirect: LoginScreen staff PIN success → `getRoleHomePath(role)`.
- [x] Owner email login → `/` (unchanged).
- [x] Guarded route: if `!canAccess(path, role)` → `NoAccessScreen` (exists).
- [x] `NavSidebar`: filter by role; for kitchen optionally hide collapse chrome later (R4).
- [x] Backend: accept `waiter` in staff create/update validation if there is an enum/allow-list.
- [x] Tests: nav filter for waiter/cashier/kitchen/owner; login redirect mock.

### Files

| Path | Action |
|------|--------|
| `frontend/src/lib/navAccess.ts` | ROUTE_ROLE_MAP |
| `frontend/src/screens/LoginScreen.tsx` | Redirect |
| `frontend/src/App.tsx` | Guarded soft-gate already — verify |
| `frontend/src/components/NavSidebar.tsx` | Filter already — verify waiter |
| `src/app/staff/*` | Role allow-list if any |
| `tests/staff/*` or FE tests | Role string `waiter` |

### Exit criteria

- [x] Staff PIN as `waiter` lands on `/floor`.
- [x] Staff PIN as `kitchen` lands on `/kds`.
- [x] Staff PIN as `cashier` lands on `/new-order`.
- [x] Waiter cannot open `/settings` (NoAccess or hidden).
- [x] Vitest green.

---

## Phase R2 — Waiter experience

**Goal:** Floor-first order taking with **quantity**, **instructions**, modifiers; no pay/void surface.

### Screens / modes

| Surface | Behavior |
|---------|----------|
| Floor Plan | Home; large tables; New Table Order → waiter order mode |
| New Order | **Waiter mode:** order types limited (dine-in, tableside); cart qty +/−; item notes; kitchen notes; modifiers; sticky **Send to Kitchen** / Hold; **hide Pay / tender** |
| Order Detail | Modify qty/notes until ready; fire course; optional rush; void → escalate PIN only |
| Orders list | Open/held only filters default |

### Tasks

- [x] `NewOrderScreen`: `const role = getSessionRole()`; if waiter: hide payment CTAs; label primary “Send to kitchen”; ensure qty controls and note fields visible and touch-sized.
- [x] `OrderDetailScreen`: waiter action bar without Pay primary (or Pay → secondary “Ask cashier”); hide refund.
- [x] `FloorPlanScreen`: after table select, deep-link `/new-order?table=&type=dine_in`.
- [x] Minimal waiter nav: Floor, Orders, New Order only (optional Live Ops H).
- [x] Tests: waiter mode hides Pay button; shows notes/qty; floor link.

### Files

| Path | Action |
|------|--------|
| `frontend/src/screens/NewOrderScreen.tsx` + css | Waiter mode |
| `frontend/src/screens/OrderDetailScreen.tsx` | Action bar by role |
| `frontend/src/screens/FloorPlanScreen.tsx` | Deep-link |
| `frontend/src/components/NavSidebar.tsx` | Waiter item set |
| `*.test.tsx` | Role-mode tests |

### Exit criteria

- [x] Placement pack §4.1 Waiter must-haves covered in UI.
- [x] No tender grid for waiter.
- [x] Vitest green.

---

## Phase R3 — Cashier experience

**Goal:** Terminal + **see bill**, create/modify, pay, drawer.

### Screens / modes

| Surface | Behavior |
|---------|----------|
| New Order | All order types; cart; sticky **Pay** + Send kitchen |
| Checkout | Primary bill: MoneySummary, tenders, split, tips |
| Orders | Search phone/order #; open → Pay CTA |
| Order Detail | Primary **Pay**; modify; staff discount; manager discount PIN |
| Payments | Drawer cash in/out; optional EOD escalate to owner |

### Tasks

- [x] Cashier landing already `/new-order`; add dashboard strip: “Open unpaid” count → `/orders?status=...` if API allows.
- [x] `CheckoutScreen` / `OrderDetailScreen`: ensure sticky Pay and bill always visible (MoneySummary).
- [x] Discounts: staff discount OK; manager discount → `useManagerPinGate`.
- [x] Refunds: PIN only (existing).
- [x] Nav: Floor optional S; Payments, Orders, Customers, New Order.
- [x] Tests: cashier sees Pay; manager discount triggers PIN modal mock.

### Files

| Path | Action |
|------|--------|
| `NewOrderScreen.tsx` | Cashier CTAs |
| `CheckoutScreen.tsx` | Bill prominence |
| `OrderDetailScreen.tsx` | Pay primary |
| `PaymentsScreen.tsx` | Drawer emphasis |
| `navAccess.ts` | Confirm cashier map |

### Exit criteria

- [x] Placement pack §4.2 Cashier must-haves in UI.
- [x] Vitest green.

---

## Phase R4 — Kitchen experience

**Goal:** Fullscreen cook board; mark ready for pickup/delivery.

### Screens / modes

| Surface | Behavior |
|---------|----------|
| KDS | Fullscreen, **no sidebar** for `kitchen`; stations; start/bump/recall; allergens; timers |
| Expo | `/kds?view=expo` in nav or tab; packaging, missing, QC, ready handoff |

### Tasks

- [x] `AppShell` / `NavSidebar`: if `kitchen`, `showSidebar=false` (or slim station tabs only).
- [x] Default filters: active tickets; Expo entry obvious.
- [x] Ensure bump/start ≥64px (already tokens).
- [x] Kitchen cannot route to `/new-order` / `/payments` (R1).
- [x] Tests: kitchen chrome hides sidebar; expo link.

### Files

| Path | Action |
|------|--------|
| `AppShell.tsx` | Chrome by role |
| `NavSidebar.tsx` / `TopBar.tsx` | Kitchen minimal top |
| `KdsScreen.tsx` | Expo entry, defaults |

### Exit criteria

- [x] Placement pack §4.3 Kitchen must-haves.
- [x] Kitchen user cannot open New Order via nav.
- [x] Vitest green.

---

## Phase R5 — Owner experience

**Goal:** Full admin + ops; Live Ops home; complete information architecture.

### Screens / modes

| Surface | Behavior |
|---------|----------|
| Live Ops | Home: late unavoidable, map, quick actions |
| Full nav | Daily + Manage + More (existing redesign) |
| Danger | PIN matrix already: void, refund, stock, channel pause — audit completeness |
| Alerts | Wire AlertCenter to late orders / low stock if APIs exist; else keep structure |

### Tasks

- [x] Confirm owner/manager land on `/` and see full nav.
- [x] Live Ops bottom bar: New Order, Orders, KDS, Riders.
- [x] Audit `useManagerPinGate` coverage vs placement S-PIN list.
- [x] Optional: owner-only “Admin” nav group label.
- [x] Tests: owner canAccess all admin routes.

### Files

| Path | Action |
|------|--------|
| `LiveOpsScreen.tsx` | Owner quick actions |
| `navAccess.ts` | Full access unchanged |
| PIN call sites | Inventory, Channels, Checkout, Order Detail |

### Exit criteria

- [x] Placement pack §4.4 Owner domains reachable.
- [x] PIN on danger actions.
- [x] Vitest green.

---

## Phase R6 — Hardening & verification

**Goal:** Production confidence and placement compliance.

### Deliverables

- [x] In-shell **staff PIN switch** (TopBar): switch role without full logout when API allows; else document residual.
- [x] Playwright e2e (or extended unit) scenarios:
  1. Waiter: login PIN → floor → add item qty/note → no Pay button.
  2. Cashier: login → new order → pay path visible.
  3. Kitchen: login → kds → no new-order nav.
  4. Owner: login → live ops → settings reachable.
- [x] Placement audit checklist: walk `ROLE_SCREEN_FEATURE_PLACEMENT.md` cat 1–2–5 must-haves against UI.
- [x] Update `understanding.txt` + status/catalog links if roles ship.
- [x] Optional: `docs/ROLE_SCREEN_FEATURE_PLACEMENT.md` §6 mark gaps closed.

### Files

| Path | Action |
|------|--------|
| `TopBar.tsx` | Staff switch |
| `frontend/e2e/*.spec.ts` | Role scenarios |
| Docs | Gap updates |

### Exit criteria

- [x] Role e2e or documented manual UAT script green.
- [x] No waiter path to unguarded refund.
- [x] Full FE vitest suite green.

---

## File map (all phases)

| Path | Phases |
|------|--------|
| `frontend/src/lib/navAccess.ts` | R0–R1, R5 |
| `frontend/src/lib/navAccess.test.ts` | R0–R1 |
| `frontend/src/lib/requireManagerPin.tsx` | R3, R5 |
| `frontend/src/components/AppShell.tsx` | R4 |
| `frontend/src/components/NavSidebar.tsx` | R1–R4 |
| `frontend/src/components/TopBar.tsx` | R4, R6 |
| `frontend/src/screens/LoginScreen.tsx` | R1 |
| `frontend/src/screens/NewOrderScreen.tsx` | R2, R3 |
| `frontend/src/screens/OrderDetailScreen.tsx` | R2, R3 |
| `frontend/src/screens/FloorPlanScreen.tsx` | R2 |
| `frontend/src/screens/CheckoutScreen.tsx` | R3 |
| `frontend/src/screens/PaymentsScreen.tsx` | R3 |
| `frontend/src/screens/KdsScreen.tsx` | R4 |
| `frontend/src/screens/LiveOpsScreen.tsx` | R5 |
| `frontend/src/App.tsx` | R1 (if routes) |
| `src/app/staff/*` | R1 waiter role validation |
| `frontend/e2e/*` | R6 |
| `docs/ROLE_SCREEN_FEATURE_PLACEMENT.md` | R6 gap updates |

---

## Testing strategy

| Level | What |
|-------|------|
| Unit | `navAccess` landings, filters, canAccess matrix |
| Component | Role-mode buttons on NewOrder / OrderDetail / AppShell |
| Integration | Login PIN → redirect (mock API) |
| E2E | Four role smoke paths (R6) |
| Regression | Full `frontend` vitest after each phase |

Commands:

```bash
cd frontend && npm test -- --run src/lib/navAccess.test.ts
cd frontend && npm test -- --run
cd frontend && npm run lint
# R6
cd frontend && npx playwright test e2e/smoke.spec.ts
```

---

## Progress tracker

| Phase | Status | Notes |
|-------|--------|-------|
| R0 Foundations | **Done** | waiter role, getRoleHomePath, getRoleChrome, helpers |
| R1 Gates + landings | **Done** | ROUTE_ROLE_MAP, PIN login redirect, kitchen no sidebar |
| R2 Waiter | **Done** | Floor deep-link; Send to kitchen; Bill at cashier; no void |
| R3 Cashier | **Done** | Terminal strip; Place & Pay → `/orders/:id/pay`; Pay on detail |
| R4 Kitchen | **Done** | No sidebar; Expo toggle + Ready for delivery tab |
| R5 Owner | **Done** | Live Ops bar Floor/Expo/Reports; Admin nav label; PIN matrix retained |
| R6 Hardening | **Done** | StaffSwitchModal TopBar; vitest role modes; `e2e/role-smoke.spec.ts` |

---

## Risk register

| Risk | Mitigation |
|------|------------|
| Waiter mode regresses cashier Pay CTA | Branch UI on `getSessionRole()` only; dual tests |
| Kitchen needs sidebar for station switch | Keep station tabs in KDS header, not full admin nav |
| Backend rejects `waiter` role | Validate staff create API; store free string if already free-form |
| Staff switch security | Re-auth PIN; don’t cache owner token as staff |
| Scope creep to 381 pages | Stick to placement P surfaces only |

---

## Definition of done (program)

- [x] Four roles land on correct homes after login.
- [x] Waiter: qty + instructions + no pay surface.
- [x] Cashier: bill + pay + create/modify.
- [x] Kitchen: see tickets + mark ready (bump/expo).
- [x] Owner: full admin + Live Ops + PIN dangers.
- [x] Placement doc gaps §6 updated or residual listed.
- [x] Tests + `understanding.txt` log.

---

## Out of scope

- Separate native apps per role (beyond existing rider-app).
- New marketplace adapters (already separate).
- Replacing backend FSM or business rules.
- Building every Cat 10 report UI from scratch (owner uses existing Reports).

---

## Related commands after ship

```bash
# Local stack for role UAT
colima start && docker compose up -d
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
cd frontend && npm run dev
# or desktop
cd frontend && VITE_API_BASE=http://127.0.0.1:8000 npm run build:electron
```

Create staff PINs with roles `waiter` | `cashier` | `kitchen` via Staff admin (owner) once R1 allows `waiter`.

---

*Plan date: 2026-07-13. Placement SSOT: `docs/ROLE_SCREEN_FEATURE_PLACEMENT.md`.*
