# Phase 0 — UI/UX Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish touch-first design tokens, AppShell chrome, shared primitives, and 36-route skeleton so Phases 1–5 can redesign screens without redoing foundations.

**Architecture:** Redesign in place under `frontend/`. Extend existing `tokens.css`, `AppShell`, `NavSidebar`, `TopBar`, `Button`, `SideDrawer`, `ConfirmDialog`. Add thin new components (`ApprovalPinModal`, `AlertCenter`, `BottomActionBar`, `EmptyState`, `ErrorState`, `MoneySummary`, `ComingSoonScreen`) rather than a component library rewrite.

**Tech Stack:** React 18, Vite, CSS modules, React Router, Vitest, Playwright e2e.

**Parent doc:** `docs/superpowers/plans/2026-07-09-pos-frontend-uiux-redesign-phases.md`

---

## File map

| Path | Responsibility |
| --- | --- |
| `frontend/src/styles/tokens.css` | Touch, type, layout tokens |
| `frontend/src/styles/tokens.test.ts` | Token contract tests |
| `frontend/src/styles/base.css` | Body 16px, focus ring, form min touch |
| `frontend/src/components/Button.tsx` + `.module.css` | TouchButton sizes (default primary ≥64) |
| `frontend/src/components/AppShell.tsx` + css | Shell slots: alert, bottom bar host |
| `frontend/src/components/TopBar.tsx` + css | 56–64px status bar, offline, staff/alerts |
| `frontend/src/components/NavSidebar.tsx` + css | Spec order, 88/240 collapse |
| `frontend/src/components/ApprovalPinModal.tsx` | Manager PIN UI |
| `frontend/src/components/AlertCenter.tsx` | Top-right alert panel |
| `frontend/src/components/BottomActionBar.tsx` | Sticky 72–88px action bar |
| `frontend/src/components/EmptyState.tsx` | Empty lists |
| `frontend/src/components/ErrorState.tsx` | Error panels |
| `frontend/src/components/MoneySummary.tsx` | Large totals |
| `frontend/src/screens/ComingSoonScreen.tsx` | Missing surface placeholder |
| `frontend/src/App.tsx` | Routes for floor, order detail, pay, rider-app |

---

### Task 1: Design tokens + base typography

**Files:** `tokens.css`, `tokens.test.ts`, `base.css`

- [ ] Extend tokens with layout/touch/type; body min 16px; tests for new tokens
- [ ] Run: `cd frontend && npm test -- --run src/styles/tokens.test.ts`

### Task 2: TouchButton

**Files:** `Button.tsx`, `Button.module.css`, update existing Button tests if any

- [ ] size=`md`|`lg`|`touch` (touch min-height 64px, min-width 56px)
- [ ] Keep primary/ghost/danger variants

### Task 3: NavSidebar collapse + spec order

**Files:** `NavSidebar.tsx`, `NavSidebar.module.css`, `NavSidebar.test.tsx`

- [ ] Groups: Daily (Live Ops, Floor, Orders, New Order, Kitchen, Payments, Riders, Chats) then Manage (Menu…Settings)
- [ ] Collapse toggle 88/240; Floor Plan links to `/floor`

### Task 4: TopBar status chrome

**Files:** `TopBar.tsx`, `TopBar.module.css`

- [ ] Height 56–64px; offline badge; alert button; clock retained; titles for new routes

### Task 5: Shared primitives

**Files:** ApprovalPinModal, AlertCenter, BottomActionBar, EmptyState, ErrorState, MoneySummary + tests

### Task 6: AppShell integration

**Files:** `AppShell.tsx`, css

- [ ] Host AlertCenter; optional connectionDown offline; main padding compatible with bottom bar

### Task 7: Route skeleton

**Files:** `App.tsx`, `ComingSoonScreen.tsx`

- [ ] `/floor`, `/orders/:id`, `/orders/:id/pay`, `/rider-app` → ComingSoon (or existing screens where partial)
- [ ] Keep existing OrderDetailDrawer behavior until Phase 2

### Task 8: Regression + log

- [ ] `cd frontend && npm test -- --run`
- [ ] Update `understanding.txt`
- [ ] Commit: `feat(ui): phase 0 touch POS shell foundation`

---

## Exit criteria

- Body ≥16px; primary touch buttons ≥64px height
- Sidebar spec order + collapse
- 36 routes resolve (coming-soon OK for missing)
- Vitest green; smoke e2e not broken by selectors if run
