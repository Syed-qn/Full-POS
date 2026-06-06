# Manager Dashboard — Design Brief

**Project:** Restaurant WhatsApp Service — Manager Dashboard  
**Date:** 2026-06-06  
**Status:** Locked for implementation  
**Stack:** React + TypeScript + Vite SPA, WebSocket live updates, REST API  
**Audience:** Restaurant manager in Dubai running own-fleet delivery ops under a hard 40-minute SLA

---

## 1. Design Direction

### Chosen Aesthetic: Tactical Operations Dark

This is not an analytics dashboard. It is a **command station for a person who loses money every minute they are not watching it.** The aesthetic is drawn from air traffic control displays, industrial process control systems, and military operations rooms — not from SaaS admin templates, not from fintech clean-UIs, not from "modern dashboards."

**Commitment: full dark environment, high information density, controlled tension through color, zero decoration.**

The visual grammar says: *something is always happening*. Live data is never static. SLA clocks are always ticking. Every screen communicates state with color, not prose.

**Why this choice over alternatives:**
- "Kitchen-heat editorial" (warm amber/red tones, editorial typography) is too artistic for a manager refreshing at 11pm during a Friday rush.
- "Industrial utilitarian" (gray monochrome, tight grid) is correct in density but lacks the urgency encoding this ops environment demands.
- "Tactical Operations Dark" delivers both: the density of industrial UI with a precise, semantic color system that puts live danger on screen at all times. The manager can glance from 2 meters away and know if the operation is healthy.

---

### Typography

**Display / Headings:** `DM Mono` — monospaced, mechanical, legible at small sizes, reads like real operational data. Used for KPI numbers, order IDs, timer countdowns, rider codes, all numeric readouts.

**Body / UI:** `IBM Plex Sans` — engineered humanist sans with narrow optical weight variants. Clean at 13–14px, excellent at small-size labels, strong Arabic-adjacent rendering for Dubai operational context. Used for all prose, labels, status text, navigation.

**Why not Inter/Roboto/Arial/Space Grotesk:** Those fonts carry the visual baggage of generic SaaS. DM Mono + IBM Plex Sans reads as *designed for this*, not assembled from defaults.

**Type scale:**
| Token | Value | Usage |
|---|---|---|
| `--text-kpi` | `DM Mono 32px / 700` | KPI strip numbers |
| `--text-countdown` | `DM Mono 24px / 700` | SLA timer per order |
| `--text-label-upper` | `IBM Plex Sans 10px / 600 / 0.1em tracking / uppercase` | Section labels, column headers |
| `--text-body` | `IBM Plex Sans 13px / 400` | Feed items, descriptions |
| `--text-body-strong` | `IBM Plex Sans 13px / 600` | Order IDs, names, status pills |
| `--text-nav` | `IBM Plex Sans 12px / 500` | Sidebar nav items |

---

### Color System

Full dark. Background is near-black desaturated slate — not pure `#000000` (kills contrast), not `#1a1a2e` (purple taint, a cardinal sin for this brief).

#### CSS Variable Table

```css
/* ─── Backgrounds ─── */
--bg-canvas:        #0d0f12;   /* page canvas — deep slate-black */
--bg-surface:       #141720;   /* cards, panels — slight blue-slate */
--bg-surface-raised:#1c2030;   /* modals, dropdowns */
--bg-surface-inset: #0a0c0f;   /* input fields, code blocks, map base */
--bg-overlay:       rgba(13,15,18,0.85); /* overlay scrim */

/* ─── Borders ─── */
--border-subtle:    #252a38;   /* card edges, dividers */
--border-default:   #323848;   /* form fields, table rows */
--border-strong:    #4a5268;   /* active state outlines */

/* ─── Text ─── */
--text-primary:     #e8ecf5;   /* headings, KPI values */
--text-secondary:   #8b93a8;   /* labels, secondary info */
--text-muted:       #525a70;   /* timestamps, disabled */
--text-inverse:     #0d0f12;   /* text on bright accent fills */

/* ─── SLA Semantics (the spine of this system) ─── */
--sla-safe:         #1adb8e;   /* >15 min remaining — cool green, not neon */
--sla-safe-dim:     rgba(26,219,142,0.12);
--sla-warn:         #f5a623;   /* yellow lane: 30–35 min elapsed */
--sla-warn-dim:     rgba(245,166,35,0.12);
--sla-critical:     #ff3d55;   /* red lane: 35–40 min / at breach */
--sla-critical-dim: rgba(255,61,85,0.14);
--sla-breach:       #ff1a37;   /* past 40 min — full bleed pulse */

/* ─── Operational Accents ─── */
--accent-primary:   #3d8bff;   /* interactive: buttons, links, selected state */
--accent-primary-dim: rgba(61,139,255,0.15);
--accent-dispatch:  #a78bfa;   /* dispatch / batch events — cool violet */
--accent-rider:     #38bdf8;   /* rider dots on map, rider status pills */
--accent-revenue:   #34d399;   /* revenue KPIs — emerald, distinct from sla-safe */
--accent-ai:        #818cf8;   /* AI-generated content, prediction cards — indigo */

/* ─── Status Pills ─── */
--status-pending:   #6b7280;
--status-confirmed: #3d8bff;
--status-preparing: #f5a623;
--status-ready:     #a78bfa;
--status-assigned:  #38bdf8;
--status-pickedup:  #a78bfa;
--status-delivered: #1adb8e;
--status-cancelled: #ff3d55;
--status-resale:    #fbbf24;

/* ─── Map ─── */
--map-bg:           #0f1419;   /* dark satellite base */
--map-road:         #1e2535;
--map-water:        #0d1520;
--map-rider-active: #38bdf8;
--map-rider-stale:  #525a70;
--map-order-pin:    #f5a623;
--map-batch-hull:   rgba(167,139,250,0.18); /* batch lasso fill */
--map-batch-stroke: #a78bfa;
```

---

### Dark vs Light

**Dark. Non-negotiable.**

The Dubai delivery operation runs evenings, nights, and Ramadan midnight peaks. A bright white UI in a restaurant back-office at 1am is an ergonomic failure. Dark mode also makes the SLA color semantics hit harder — `--sla-critical` on dark is a visceral red alert; on white it is just a badge.

---

### Background and Texture Treatment

**No decorative textures.** No gradients for their own sake. The only "texture" is the grid system and the live-data motion.

**Specifics:**
- Canvas (`--bg-canvas`) is flat — no grain, no noise, no subtle pattern.
- Cards sit at `--bg-surface` with a single 1px `--border-subtle` border and 8px border-radius. No box-shadow. Depth comes from background layering, not shadow.
- Map panel has its own dark tile base (`--map-bg`) — the only area that feels "layered."
- SLA escalation introduces the only background pulse: at critical state, the order card background cycles `--bg-surface → --sla-critical-dim → --bg-surface` at 2s interval.

---

### Motion Principles

**Rule: motion must carry information, never decorate.**

| Moment | Motion |
|---|---|
| Page load / screen mount | Staggered fade-up: nav instant, KPI strip 80ms delay, primary panel 160ms, secondary panels 240ms. Duration: 200ms ease-out. No bounce, no spring. |
| KPI value update (WebSocket) | Number morphs with a 120ms cross-fade via CSS `@counter-style` or JS digit flip. Background of the KPI card flashes `--accent-primary-dim` for 300ms then settles. |
| New order arrival | Order feed item slides in from right (translateX +24px → 0, 180ms ease-out). Row background pulses `--sla-safe-dim` once. |
| SLA yellow threshold | Card border transitions to `--sla-warn` over 400ms. Timer text color shifts. No animation — the color change *is* the alert. |
| SLA red threshold | Card border `--sla-critical`, border-width 2px. Background pulse starts (2s loop). Timer switches to `DM Mono 700`. |
| SLA breach | Full card background bleeds to `rgba(255,29,55,0.22)`. Pulse frequency doubles (1s loop). Card rises in z-index above siblings. |
| Rider dot on map | Smooth position interpolation between location pings (1s CSS transition on `transform`). Stale rider dot fades to `--map-rider-stale` and gains a 4px dashed border. |
| Batch lasso on map | Convex hull polygon draws with a SVG stroke-dasharray animation over 400ms, then fills with `--map-batch-hull`. |
| Template pending shimmer | AI-generated template card shows a left-to-right shimmer scan (`--bg-surface → --accent-ai-dim → --bg-surface`, 1.6s loop) while Meta approval is pending. |
| Prediction confidence bar | On mount, bar width animates from 0 to value over 600ms ease-out. Low confidence (<60%) bars render in `--sla-warn`. |

**No page transitions.** Client-side navigation is instant — the sidebar nav item activates, main content swaps. Transitions between screens waste time for an operator who switches screens under pressure.

---

### Spatial Composition — Density Rules

**Controlled density: maximum information per square centimeter, zero clutter.**

- Base spacing unit: 4px. All spacing is multiples of 4.
- Standard card padding: 16px.
- Tight mode (order cards, table rows): 12px vertical padding.
- KPI strip: 24px padding, KPI values dominate visually at 32px.
- Table row height: 44px default, 36px in compact mode (user toggle per table).
- Sidebar width: 220px expanded, 56px collapsed (icon only). Default expanded.
- Map panel minimum height: 420px; expands to fill available vertical space.
- SLA board: two-column grid (yellow | red), stacks vertically on narrower viewports.

**Whitespace is rationed, not lavished.** Section headers get 20px top margin. Empty states are compact (40px icon + 2 lines of text, no hero illustrations).

---

## 2. Information Architecture

### Screen List

1. **Live Ops** (default / home)
2. **Orders**
3. **Menu Manager**
4. **Riders**
5. **Marketing Studio**
6. **Predictions**
7. **Conversations**
8. **Audit Explorer**
9. **Settings**

---

### Screen 1: Live Ops (Default)

This is the screen the manager leaves open all day. Every WebSocket event lands here.

**Layout:**
```
┌─────────────────────────────────────────────────────────────────────┐
│ SIDEBAR │  KPI STRIP (full width)                                    │
│         ├─────────────────────────────────────────────────────────── │
│  [logo] │  ┌──────────────────────────────┐  ┌─────────────────────┐│
│         │  │                              │  │  SLA BOARD          ││
│  Live   │  │   DISPATCH MAP               │  │  ─────────────────  ││
│  Orders │  │   (riders, orders, batches,  │  │  YELLOW LANE        ││
│  Menu   │  │    geofences, batch hulls)   │  │  [order card ×n]    ││
│  Riders │  │                              │  │  ─────────────────  ││
│  Mktg   │  │                              │  │  RED LANE           ││
│  Predict│  │                              │  │  [order card ×n]    ││
│  Convs  │  └──────────────────────────────┘  └─────────────────────┘│
│  Audit  │  ┌──────────────────────────────────────────────────────── │
│  Config │  │  LIVE ORDER FEED                                       ││
│         │  │  [order row] [order row] [order row] ... (scroll)      ││
│         │  └────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

**KPI Strip:** 7 tiles, horizontally scrollable on narrow:
- Orders Today | Revenue Today | AOV | Avg Delivery Time | SLA % | Late Count | Coupons Issued
- Each tile: label (`--text-label-upper`), value (`DM Mono 32px`), delta from yesterday (↑/↓ in `--sla-safe` / `--sla-critical`).

**Dispatch Map:**
- Dark Mapbox/Google Maps tile (`--map-bg`).
- Rider dots: color-coded by status (active `--accent-rider`, on-delivery pulsing `--accent-rider`, stale gray).
- Order pins: color by SLA state.
- Batch hulls: dashed convex polygon in `--map-batch-stroke`.
- Clicking a rider or order pin opens a side-drawer with detail.

**SLA Board (right panel):**
- Yellow lane: orders 30–35 min elapsed. Amber border. Timer prominent.
- Red lane: orders 35–40 min elapsed. Red border, pulsing background. Escalation active.
- Cards auto-move between lanes as time elapses. No manual sort.
- Empty lane: "All clear" text in `--text-muted` — no illustration.

**Live Order Feed (bottom strip):**
- Chronological, newest at top.
- Each row: order number, customer name, status pill, items summary, assigned rider, SLA timer, quick-action button (reassign / force state).
- WebSocket events animate new rows in.
- Filterable by status (multi-select pills above feed).

**Primary actions:** Force-assign rider (modal), pause new orders, manual takeover (links to Conversations).

**Live-update behavior:** Every WebSocket message from `/ws/dashboard` diffs the current state and applies targeted DOM updates — no full re-render.

**Error state:** WebSocket disconnected → top-of-screen banner: "Live updates paused — reconnecting." Banner is `--sla-warn` background. Data shown is last known, with a staleness timestamp.

**Empty state:** New restaurant, no orders today — KPI strip shows zeros, map shows restaurant pin only, feed shows "No orders yet today."

---

### Screen 2: Orders

Full order history + filtering. This is the forensics screen.

**Layout:**
```
┌───────────────────────────────────────────────────────────────────┐
│ FILTER BAR: [Status pills] [Date range] [Rider] [Search: #ID]     │
├───────────────────────────────────────────────────────────────────┤
│ TABLE: #  │ Customer │ Items │ Total │ Rider │ Status │ SLA │ Time │
│           │          │       │       │       │        │     │      │
│ (rows, 44px height, compact toggle)                               │
├───────────────────────────────────────────────────────────────────┤
│ ORDER DETAIL DRAWER (slide-in from right, 480px wide)             │
│ Full order, address, rider trail, audit timeline, coupon info     │
└───────────────────────────────────────────────────────────────────┘
```

**Primary actions:** Export CSV, reopen order detail, manual coupon issue.

**Live-update:** Active orders' status pills and SLA timers update live. Historical rows do not animate.

**Empty state:** Filters yield nothing — "No orders match these filters" with a reset-filters link.

**Error state:** API fetch failure — inline error row with retry button, no full-page error.

---

### Screen 3: Menu Manager

Two modes: normal (active menu management) and **Confirmation Mode** (triggered when a new menu upload finishes parsing).

**Layout — Confirmation Mode:**
```
┌─────────────────────────────────────────────────────────────────┐
│ BANNER: "New menu parsed — review and confirm before activating" │
├─────────────────────────────────────────────────────────────────┤
│ DIFF VIEW                                                        │
│ ┌──────────────────────────┐  ┌──────────────────────────────┐  │
│ │ CURRENT (active)         │  │ INCOMING (parsed)            │  │
│ │ 110. Chicken Biryani     │  │ 110. Chicken Biryani         │  │
│ │ AED 22                   │  │ AED 25  ← PRICE CHANGE flag  │  │
│ └──────────────────────────┘  └──────────────────────────────┘  │
│ Changed: 3 | New: 7 | Removed: 1 | Extraction errors: 2         │
│ [Confirm & Activate] [Edit before activating] [Discard]          │
└─────────────────────────────────────────────────────────────────┘
```

**Layout — Normal Mode:**
```
┌─────────────────────────────────────────────────────────────────┐
│ CATEGORY TABS: All | Mains | Sides | Drinks | ...               │
├─────────────────────────────────────────────────────────────────┤
│ SEARCH: [                    ] [+ Add dish] [Upload new menu]    │
├─────────────────────────────────────────────────────────────────┤
│ DISH GRID (3 cols)                                               │
│ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐        │
│ │ #110           │ │ #111           │ │ #112           │        │
│ │ Chicken Biryani│ │ Special Biryani│ │ Lamb Mandi     │        │
│ │ AED 22         │ │ AED 28         │ │ AED 35         │        │
│ │ [Available ●]  │ │ [Available ●]  │ │ [Unavailable ○]│        │
│ └────────────────┘ └────────────────┘ └────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

**Primary actions:** Toggle dish availability (immediate — sends to active menu, affects live conversations), edit dish inline, upload new menu.

**Availability toggle:** Confirmed with 1-click — no modal. Toggle flips instantly. Toggling off a dish that has pending orders shows a warning: "3 active orders contain this dish."

**Extraction errors:** Dishes with missing number or price flagged with `--sla-warn` border in diff view. Cannot confirm menu with unresolved errors.

**Empty state:** No active menu — "Upload your first menu to get started" with upload CTA.

---

### Screen 4: Riders

**Layout:**
```
┌─────────────────────────────────────────────────────────────────┐
│ RIDER CARDS (grid, 2 cols)                                       │
│ ┌────────────────────────┐  ┌────────────────────────┐           │
│ │ Ali Hassan             │  │ Omar Farouq            │           │
│ │ ● On delivery          │  │ ○ Off shift            │           │
│ │ Batch #B-047 · 2 stops │  │                        │           │
│ │ On-time: 94%  Avg 23min│  │ On-time: 88%  Avg 28min│           │
│ │ [View on map] [Deact.] │  │ [Start shift] [Deact.] │           │
│ └────────────────────────┘  └────────────────────────┘           │
├─────────────────────────────────────────────────────────────────┤
│ COD RECONCILIATION                                               │
│ Date: [today ▼]                                                  │
│ Rider      │ Expected │ Collected │ Variance │ Status             │
│ Ali Hassan │ AED 340  │ AED 340   │ AED 0    │ ✓ Balanced         │
│ Omar Farouq│ AED 210  │ AED 190   │ -AED 20  │ ⚠ Variance         │
└─────────────────────────────────────────────────────────────────┘
```

**Primary actions:** Deactivate rider from future assignment (modal confirm), force shift on/off, resolve COD variance (note + amount).

**Live-update:** Rider status pills and current batch info update via WebSocket. Location-based status (returning, at restaurant) updates live.

**Empty state:** No riders registered — CTA to register first rider.

**Stale-location alert:** If a rider has a stale location (>3 min), their card gains a `--sla-warn` border and a "Location stale" badge.

---

### Screen 5: Marketing Studio

Three sub-sections: Today's Special, Segments, Automations.

**Layout — Today's Special:**
```
┌─────────────────────────────────────────────────────────────────┐
│ TODAY'S SPECIAL COMPOSER                                         │
│ ┌─────────────────────────┐  ┌──────────────────────────────┐   │
│ │ COMPOSE                 │  │ PREVIEW (WhatsApp render)    │   │
│ │ Image: [upload]         │  │ ┌──────────────────────────┐ │   │
│ │ Body text:              │  │ │ [image header]           │ │   │
│ │ [textarea]              │  │ │ Today only: Half-price    │ │   │
│ │                         │  │ │ Biryani! Order now ▶      │ │   │
│ │ [Generate with AI]      │  │ └──────────────────────────┘ │   │
│ │ [Edit template]         │  │ AI-generated                 │   │
│ └─────────────────────────┘  └──────────────────────────────┘   │
│                                                                  │
│ APPROVAL STATUS TIMELINE                                         │
│ ○ Draft → ● Submitted to Meta → … Pending → ✓ Approved → → Sent │
│                                                                  │
│ SEND TO: [All customers ▼] or [Select segment]                   │
│ [Submit for Approval] [Send Now (if approved)] [Cancel]          │
└─────────────────────────────────────────────────────────────────┘
```

**Template shimmer:** While Meta approval is pending, the preview card renders with the `--accent-ai` shimmer animation.

**Rejection flow:** If rejected, the rejection reason is shown inline below the preview. A "Fix with AI" button triggers a revised template generation, auto-applying the suggested fix.

**Layout — Segments:**
```
┌─────────────────────────────────────────────────────────────────┐
│ SEGMENTS                                          [+ New Segment]│
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────────────────────────┐ │
│ │ Plain-English input:                                         │ │
│ │ "customers who ordered biryani 3+ times in the last 30 days" │ │
│ │ [Compile Segment]                                            │ │
│ │ Preview: 47 customers match                                  │ │
│ │ [Save as Segment]                                            │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ Saved segments table: Name | Count | Last updated | Actions       │
└─────────────────────────────────────────────────────────────────┘
```

**Layout — Automations:**
Plain-English trigger/condition/action builder. Three inputs. Preview of compiled DSL (collapsed by default, expandable for technical review). Enable/disable toggle.

**Empty state:** No campaigns sent yet — "Create your first Today's Special" CTA.

---

### Screen 6: Predictions

**Layout:**
```
┌─────────────────────────────────────────────────────────────────┐
│ PREDICTIONS                    Model accuracy: 84% MAPE  ●●●●○   │
├────────────────┬──────────────────────────────────────────────── │
│ NEXT HOUR      │ TODAY'S WINDOWS                                  │
│ Orders: 14     │ ┌────────────┐ ┌────────────┐ ┌────────────┐    │
│ Revenue: AED420│ │ BREAKFAST  │ │  LUNCH     │ │  DINNER    │    │
│ Top dish:      │ │ 07–11      │ │  12–16     │ │  18–23     │    │
│ Biryani ×6     │ │ Orders: 28 │ │  Orders:67 │ │  Orders:95 │    │
│                │ │ Rev: AED840│ │  Rev: 2010 │ │  Rev: 2850 │    │
│                │ └────────────┘ └────────────┘ └────────────┘    │
│                │ ┌────────────┐                                   │
│                │ │ MIDNIGHT   │                                   │
│                │ │  23–03     │                                   │
│                │ │ Orders: 31 │                                   │
│                │ └────────────┘                                   │
├────────────────┴──────────────────────────────────────────────── │
│ ACCURACY SPARKLINE (7-day trailing MAPE per horizon)             │
├─────────────────────────────────────────────────────────────────┤
│ PLAIN-ENGLISH OVERRIDE                                           │
│ "Big corporate order expected Thursday afternoon"                │
│ [Apply Override]                                                 │
│ Active overrides: [×] "Road closed near campus, Fri 14:00–16:00" │
└─────────────────────────────────────────────────────────────────┘
```

**Prediction cards:** Confidence shown as colored fill bar. Below 60% confidence → `--sla-warn` tone on the card.

**AI reasoning:** Expandable section on each card: "Model adjusted for: Ramadan peak (+18%), active 'Biryani Half-Price' campaign (+12%)."

**Empty state:** Model not yet trained (first week) — "Predictions available after your first week of orders. Check back Monday."

---

### Screen 7: Conversations

**Layout:**
```
┌─────────────────────────────────────────────────────────────────┐
│ CONVERSATION LIST (left 320px)     │ CONVERSATION VIEWER (right) │
│ [Search by phone/name]             │                             │
│ ─────────────────────────────────  │ [Customer name / phone]     │
│ ● Ali (+971-50-xxx-1234)          │ [WhatsApp message thread]   │
│   "I want to order biryani"        │                             │
│   2 min ago                        │ ...                         │
│ ─────────────────────────────────  │                             │
│ Omar (+971-55-xxx-5678)           │ [MANUAL TAKEOVER]            │
│   Delivered · 45 min ago           │ [Type message]  [Send]      │
│                                    │ "Taking over from bot"      │
└─────────────────────────────────────────────────────────────────┘
```

**Manual takeover:** Toggle at top of viewer. When active, an amber banner reads "You are controlling this conversation." Bot is paused. Return-to-bot button available.

**Live-update:** New messages append to the active conversation in real time. Unread count badge on nav.

**Empty state:** No conversations — "Conversations will appear here as customers message your WhatsApp number."

---

### Screen 8: Audit Explorer

**Layout:**
```
┌─────────────────────────────────────────────────────────────────┐
│ FILTERS: [Entity type ▼] [Actor ▼] [Date range] [Search]        │
├─────────────────────────────────────────────────────────────────┤
│ AUDIT LOG TABLE                                                  │
│ Timestamp │ Actor  │ Entity    │ Action          │ Details       │
│ 14:32:01  │ system │ order#047 │ status_changed  │ ready→assigned│
│ 14:31:45  │ manager│ dish#110  │ availability    │ true→false    │
│ 14:29:12  │ system │ batch#B04 │ batch_formed    │ 2 orders      │
├─────────────────────────────────────────────────────────────────┤
│ DETAIL PANEL (expandable): before/after JSON diff               │
└─────────────────────────────────────────────────────────────────┘
```

**Read-only.** No actions. Before/after JSON shown as a colored diff (green additions, red removals, same dark aesthetic).

---

### Screen 9: Settings

Tabbed: **General | Fees & Radius | Batching | Riders | Predictions | Danger Zone**

Key fields:
- Delivery fee tiers (3 zones, editable AED values).
- Max delivery radius (km slider, max 10).
- Max orders per batch, max items per order.
- Weekly model retrain day + time.
- Pause new orders toggle (immediate effect — WhatsApp auto-replies "temporarily closed").

**Danger Zone tab:** Delete restaurant data, reset menu, full audit download.

---

## 3. Signature Moments

### 3.1 SLA Countdown Treatment Per Order Card

Every order card on the SLA board and Live Order Feed shows a countdown timer, not a timestamp.

- Format: `MM:SS` remaining until 40-minute breach. `DM Mono 700`.
- Color: white when >15 min, `--sla-warn` at 10–15 min, `--sla-critical` at <10 min.
- At <5 min: the digits take on a hard pixel-level visual urgency — they grow 2px in size with a `letter-spacing` expansion. Not animated as "shaky" (that would be annoying) — the size increase alone registers alarm.
- At breach (0:00): timer freezes at 0:00 in `--sla-breach` and the card background bleeds fully. Manager cannot miss it.

### 3.2 Dispatch Map Batch Lasso Animation

When the dispatch engine forms a new batch, the map plays a deliberate 400ms animation:
1. Individual order pins on the map briefly pulse once.
2. A convex hull polygon draws outward from the first pin to encompass all batch stops — SVG `stroke-dasharray` draw animation, `--map-batch-stroke` color.
3. The hull fills with `--map-batch-hull` (translucent violet).
4. Batch ID label appears at the centroid.

This makes the batching decision legible as a spatial event — the manager can see "the system grouped these 3 orders" as it happens.

### 3.3 Approval-Pending Template Shimmer

When a Today's Special template is submitted to Meta for approval, the WhatsApp preview card in the Marketing Studio does not sit inert with a "Pending" badge. Instead:
- A left-to-right light sweep crosses the card every 1.6 seconds: `background: linear-gradient(90deg, transparent 0%, rgba(129,140,248,0.18) 50%, transparent 100%)`.
- The shimmer uses `--accent-ai` (indigo) to connote "AI/platform processing" rather than loading state.
- The approval timeline below the card advances: each step lights up as the status transitions from Draft → Submitted → Pending → Approved.
- On approval, the shimmer stops, the card border flashes `--sla-safe` once, and the "Send Now" button becomes active.

### 3.4 Stale Rider Location Decay

A rider whose location has not been updated in >3 minutes enters a visible decay state on the map:
- Their dot desaturates from `--accent-rider` toward `--map-rider-stale` over 30 seconds.
- A dashed border appears around the dot.
- Hovering the dot shows "Last seen: 4 min ago — location may be inaccurate."
- The rider's card in the Riders screen gains a `--sla-warn` border.

This makes the staleness legible as a gradual degradation, not a binary flag — it mirrors the actual uncertainty.

### 3.5 KPI Delta Flash on Live Update

When a KPI value updates (new order delivered, new order placed), the KPI tile does not just swap the number. The delta (`+1 order`, `+AED 28`) briefly materializes as a floating element that rises from the number and fades out over 600ms. Direction: upward for positive deltas, downward for negative. Color: `--sla-safe` for increases, `--sla-critical` for decreases. This is the only animation that exists purely for feedback richness — but it is restrained (600ms, small type, no bounce).

---

## 4. Component Inventory

| Component | Variants | States | Screens |
|---|---|---|---|
| `KPITile` | revenue, count, percentage, duration | default, updating (flash), warning, error | Live Ops |
| `SLAOrderCard` | yellow-lane, red-lane, breach | default, pulsing, breach-bleed | Live Ops |
| `LiveOrderRow` | default, compact | default, new-arrival (slide-in), updating | Live Ops, Orders |
| `RiderDot` (map) | active, on-delivery, stale, off-shift | animated-position, stale-decay, selected | Live Ops |
| `BatchHull` (map) | forming, active, completing | draw-animation, filled, dissolving | Live Ops |
| `StatusPill` | all FSM states (10 states) | default, pulse (for active transitions) | Orders, Live Ops, Riders |
| `CountdownTimer` | order-card, mini (in rows) | safe, warn, critical, breach | Live Ops, SLA Board |
| `DishCard` | available, unavailable, diff-new, diff-changed, diff-removed, extraction-error | default, toggling, hover | Menu Manager |
| `DiffPanel` | side-by-side (current vs incoming) | clean, with-changes | Menu Manager |
| `RiderCard` | active, on-delivery, off-shift, deactivated | default, stale-location, selected | Riders |
| `CODReconciliationRow` | balanced, variance | default, resolved | Riders |
| `TemplatePreviewCard` | draft, pending-meta, approved, rejected, sent | default, shimmer, approved-flash | Marketing Studio |
| `ApprovalTimeline` | horizontal, vertical | each step: pending / active / complete / failed | Marketing Studio |
| `SegmentBuilder` | plain-english, compiled | idle, compiling, preview-ready, error | Marketing Studio |
| `PredictionCard` | next-1h, breakfast, lunch, dinner, midnight | default, low-confidence, with-override | Predictions |
| `AccuracySparkline` | — | default, degraded | Predictions |
| `OverridePill` | active, expired | — | Predictions |
| `ConversationRow` | customer, rider, takeover-active | unread, read, selected | Conversations |
| `MessageBubble` | inbound, outbound, system, error | default, sending, delivered, failed | Conversations |
| `AuditRow` | state-change, manual, system, error | default, expanded | Audit Explorer |
| `JSONDiff` | addition, deletion, unchanged | — | Audit Explorer, Orders detail |
| `SideDrawer` | order-detail, rider-detail, map-pin | closed, open, loading | Live Ops, Orders |
| `SectionBanner` | warning, error, info, success | dismissible, persistent | All screens |
| `CompactTable` | — | default, compact-mode, loading, error, empty | Orders, Riders, Audit |
| `NavSidebar` | expanded, collapsed | default, item-active, unread-badge | All screens |

---

## 5. Anti-Goals

This dashboard must **never** look like any of the following:

**Generic admin template.** No Ant Design default palette, no Bootstrap table aesthetic, no breadcrumb trails to "Dashboard > Orders > Order #047". The nav is flat and direct.

**Purple-gradient AI slop.** The `--accent-ai` indigo is used only for AI-specific moments (template shimmer, prediction cards, override pills). It is never used as a hero color or gradient background. No "Powered by AI" badges on every surface.

**Analytics-first layout.** This is an operations tool, not a reporting tool. Charts and sparklines are secondary — they appear only on the Predictions screen and as small inline deltas. The primary content is always live operational state: orders, riders, SLA.

**Cluttered notification system.** No notification center drawer with 40 unread items. Alerts manifest as card state changes (SLA board) and a top banner for critical degradations (WebSocket down, LLM down). The live data on screen is the notification.

**Responsive/mobile-first design.** This dashboard targets a 1440px-wide desktop display in a restaurant back-office or laptop. It is not designed for mobile. Tables do not stack. The map does not collapse to a list. Compactness serves the information density requirement, not responsive breakpoints.

**Onboarding overlays and empty-state heroes.** No large illustrated empty states with 3-paragraph encouragements. Empty states are one icon + one line of text + one action. The manager knows what they are doing.

**Soft rounded "friendly" aesthetics.** Border-radius: 8px maximum. No 24px pill cards. No pastel tones. This is a tool for someone who is watching a clock.

---

*Brief locked. This document is the aesthetic and IA contract for the frontend-design implementation phase. Deviations require explicit revision of this document — not in-code improvisation.*
