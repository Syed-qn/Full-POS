# Phase 5: React Manager Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone Vite + React + TypeScript single-page app under `frontend/` that gives the restaurant manager a dark "tactical operations" command station: JWT login, a live ops board (orders by status with SLA countdown color-threading), order detail, menu manager (upload → diff → activate), dish availability toggles, riders board, conversations with manual takeover, settings, and an analytics placeholder. Real-time is **polling-first** (3–5 s) behind a clean abstraction so a WebSocket transport can be swapped in later with zero component changes.

**Design contract (non-negotiable):** `docs/design/dashboard-design-brief.md` — "Tactical Operations Dark". DM Mono (numerics/IDs/timers) + IBM Plex Sans (prose/labels). Full dark, near-black slate canvas `#0d0f12`. SLA color semantics are the spine of the system. Border-radius ≤ 8px, no box-shadow, no decorative gradients, no responsive/mobile design (target 1440px desktop). Read the brief §1 (color/type tables), §3 (signature moments), §4 (component inventory), §5 (anti-goals) before writing any component. Every CSS variable in this plan is copied verbatim from the brief.

**Tech stack:** Vite 5, React 18, TypeScript 5, React Router 6, plain `fetch` wrapped in a typed client (no axios — keep deps minimal per brief's "assembled from defaults" anti-goal), Vitest + @testing-library/react + jsdom for unit/component tests, Playwright for a single smoke e2e. **No UI framework** (no MUI/AntD/Chakra/Tailwind) — a hand-rolled CSS-variable design system per the brief.

**Backend it talks to (already built, Phases 0–4):** FastAPI at `http://localhost:8000`, all routes prefixed `/api/v1`. JWT bearer auth.
- Auth: `POST /api/v1/auth/signup`, `POST /api/v1/auth/login` → `{access_token, token_type}`, `GET /api/v1/me` → `RestaurantOut{id,name,phone,lat,lng,settings}`.
- Riders: `GET /api/v1/riders` → `RiderOut[]{id,name,phone,status}`, `POST /api/v1/riders`, `PATCH /api/v1/riders/{id}` body `{status}` (status ∈ available|on_delivery|off_shift|deactivated).
- Settings: `PATCH /api/v1/settings` body `{max_orders_per_batch?,max_items_per_order?,delivery_fee_tiers?}`.
- Menu: `POST /api/v1/menus` (multipart files) → `MenuWithDiffOut{id,version,status,dishes[],diff_vs_active?}`, `GET /api/v1/menus/{id}` → `MenuOut`, `POST /api/v1/menus/{id}/dishes`, `PATCH /api/v1/menus/{id}/dishes/{id}`, `DELETE /api/v1/menus/{id}/dishes/{id}`, `PATCH /api/v1/dishes/{id}/availability` body `{is_available}`, `POST /api/v1/menus/{id}/activate`.
- `DishOut`: `{id, dish_number:int|null, name, price_aed:string|null, category:string|null, description:string|null, is_available:bool}`.
- `DiffOut`: `{price_changes[], added[], removed[], conflicts[]}`.
- Orders: endpoints land in Phase 3 Task 9 (`GET /api/v1/orders`, `GET /api/v1/orders/{id}`). **They may not exist yet when this phase runs** — Task 6 below defines a typed client + a fixture-backed fallback so the Live Ops board is buildable and testable against recorded JSON regardless. Order FSM states (from `src/app/ordering/fsm.py`): `draft, pending_confirmation, confirmed, preparing, ready, assigned, picked_up, arriving, delivered, cancelled, undeliverable, on_resale, resold, written_off`.
- Conversations: `GET /api/v1/conversations`, `GET /api/v1/conversations/{id}/messages`, takeover endpoints — also Phase-dependent; Task 12 uses the same fixture-fallback client pattern.

**Prerequisite:** Node 20+ and npm available. Backend running on :8000 for live integration is optional — all component tests mock the client; the Playwright smoke uses a stubbed network (route interception), so the suite is green without a live backend.

---

## File structure (locked in)

```
frontend/
  package.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  vitest.config.ts          (merged into vite.config.ts via test field — single file)
  playwright.config.ts
  index.html
  .env.example              VITE_API_BASE=http://localhost:8000
  src/
    main.tsx                React root + Router
    App.tsx                 route table, AuthGuard
    vite-env.d.ts
    styles/
      tokens.css            ALL CSS variables from brief §1 (colors, type)
      base.css              reset, html/body, font-face, scrollbars
      fonts.css             @font-face DM Mono + IBM Plex Sans (Google Fonts @import)
    lib/
      apiClient.ts          typed fetch wrapper, bearer injection, error envelope
      auth.ts               token storage (localStorage), login/logout, useAuth
      types.ts              shared API DTO types (RestaurantOut, RiderOut, DishOut, OrderOut, ...)
      sla.ts                SLA math: remainingMs, slaTier(), formatCountdown()
      transport/
        index.ts            Transport interface + getTransport() (polling default)
        pollingTransport.ts setInterval-based subscribe(), swappable
      usePoll.ts            React hook: usePoll(fetcher, intervalMs)
      fixtures/
        orders.json         recorded sample orders (fallback + tests)
        conversations.json
    components/
      AppShell.tsx          sidebar + main slot + WS-down banner
      NavSidebar.tsx        flat nav, active state, unread badge
      StatusPill.tsx        all 14 FSM states → color
      CountdownTimer.tsx    MM:SS, color by sla tier, <5min size bump
      KPITile.tsx           label + DM Mono value + delta flash
      SLAOrderCard.tsx      yellow/red lane card, pulse, breach bleed
      LiveOrderRow.tsx      feed row, slide-in
      DishCard.tsx          available/unavailable/diff variants, toggle
      DiffPanel.tsx         current vs incoming side-by-side
      RiderCard.tsx         status, stale-location border
      ConversationRow.tsx   unread/selected
      MessageBubble.tsx     inbound/outbound/system
      SideDrawer.tsx        right slide-in 480px
      SectionBanner.tsx     warning/error/info/success
      CompactTable.tsx      generic table, compact toggle, empty/error states
      Button.tsx            primary/ghost/danger
      Spinner.tsx
    screens/
      LoginScreen.tsx
      LiveOpsScreen.tsx
      OrdersScreen.tsx
      OrderDetailDrawer.tsx
      MenuManagerScreen.tsx
      RidersScreen.tsx
      ConversationsScreen.tsx
      SettingsScreen.tsx
      AnalyticsScreen.tsx   placeholder per scope
  tests/                    (component tests colocated as *.test.tsx next to source)
  e2e/
    smoke.spec.ts           Playwright: login → live ops renders
```

**Commands (run from `frontend/`):**
```bash
npm install
npm run dev          # vite dev server :5173, proxies /api → :8000
npm run build        # tsc + vite build
npm run test         # vitest run (component/unit)
npm run test:watch   # vitest
npm run lint         # tsc --noEmit (type-check as lint gate)
npm run e2e          # playwright test
```

---

### Task 1: Scaffold Vite + React + TS project with test harness

**Files:** Create `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/.env.example`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/vite-env.d.ts`.

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "restaurant-dashboard",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "tsc --noEmit",
    "e2e": "playwright test"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2"
  },
  "devDependencies": {
    "@playwright/test": "^1.47.2",
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^25.0.0",
    "typescript": "^5.5.4",
    "vite": "^5.4.6",
    "vitest": "^2.1.1"
  }
}
```

- [ ] **Step 2: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "e2e"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 3: Create `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noEmit": true
  },
  "include": ["vite.config.ts", "playwright.config.ts"]
}
```

- [ ] **Step 4: Create `frontend/vite.config.ts`** (Vite + Vitest config in one file)

```ts
/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    exclude: ["e2e/**", "node_modules/**"],
  },
});
```

- [ ] **Step 5: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1440" />
    <title>Ops Terminal</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create `frontend/.env.example`**

```
VITE_API_BASE=http://localhost:8000
```

- [ ] **Step 7: Create `frontend/src/vite-env.d.ts`**

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 8: Create `frontend/src/main.tsx`** (App.tsx and styles are created in later tasks; create minimal stubs so this compiles now)

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/base.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] **Step 9: Create temporary `frontend/src/App.tsx`** (replaced by the real router in Task 5)

```tsx
export default function App() {
  return <div>Ops Terminal — bootstrapping</div>;
}
```

- [ ] **Step 10: Create `frontend/src/test/setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 11: Create empty style stubs so `main.tsx` imports resolve** (real content in Task 2). Create `frontend/src/styles/fonts.css`, `frontend/src/styles/tokens.css`, `frontend/src/styles/base.css` each containing a single comment line `/* placeholder — filled in Task 2 */`.

- [ ] **Step 12: Install and verify build**

Run:
```bash
cd frontend && npm install && npm run lint && npm run build
```
Expected: `tsc --noEmit` clean, `vite build` produces `dist/` with no errors.

- [ ] **Step 13: Verify dev server boots** (manual sanity, then Ctrl-C)

Run: `cd frontend && timeout 8 npm run dev || true`
Expected: "Local: http://localhost:5173" printed, no compile error.

- [ ] **Step 14: Commit**

```bash
git add frontend/package.json frontend/tsconfig*.json frontend/vite.config.ts frontend/index.html frontend/.env.example frontend/src/main.tsx frontend/src/App.tsx frontend/src/vite-env.d.ts frontend/src/test/setup.ts frontend/src/styles
git commit -m "chore: scaffold Vite+React+TS dashboard with vitest harness"
```

---

### Task 2: Design tokens + base styles (the brief's CSS variables)

**Files:** Replace `frontend/src/styles/tokens.css`, `frontend/src/styles/base.css`, `frontend/src/styles/fonts.css`. Test: `frontend/src/styles/tokens.test.ts`.

**Why a test on CSS:** guards that the SLA spine variables exist verbatim — the rest of the design system reads them via `var()`. A typo here silently breaks color threading.

- [ ] **Step 1: Write the failing test** — `frontend/src/styles/tokens.test.ts`

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

describe("design tokens", () => {
  it.each([
    ["--bg-canvas", "#0d0f12"],
    ["--bg-surface", "#141720"],
    ["--sla-safe", "#1adb8e"],
    ["--sla-warn", "#f5a623"],
    ["--sla-critical", "#ff3d55"],
    ["--sla-breach", "#ff1a37"],
    ["--accent-primary", "#3d8bff"],
    ["--status-delivered", "#1adb8e"],
    ["--text-primary", "#e8ecf5"],
  ])("defines %s = %s", (name, value) => {
    const re = new RegExp(`${name}:\\s*${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
    expect(css).toMatch(re);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- tokens`
Expected: FAIL — placeholder css has no variables.

- [ ] **Step 3: Write `frontend/src/styles/tokens.css`** — copy the full variable table from brief §1 verbatim. Include every variable group: Backgrounds, Borders, Text, SLA Semantics, Operational Accents, Status Pills, Map. Also add the type-scale tokens:

```css
:root {
  /* ─── Backgrounds ─── */
  --bg-canvas: #0d0f12;
  --bg-surface: #141720;
  --bg-surface-raised: #1c2030;
  --bg-surface-inset: #0a0c0f;
  --bg-overlay: rgba(13, 15, 18, 0.85);

  /* ─── Borders ─── */
  --border-subtle: #252a38;
  --border-default: #323848;
  --border-strong: #4a5268;

  /* ─── Text ─── */
  --text-primary: #e8ecf5;
  --text-secondary: #8b93a8;
  --text-muted: #525a70;
  --text-inverse: #0d0f12;

  /* ─── SLA Semantics ─── */
  --sla-safe: #1adb8e;
  --sla-safe-dim: rgba(26, 219, 142, 0.12);
  --sla-warn: #f5a623;
  --sla-warn-dim: rgba(245, 166, 35, 0.12);
  --sla-critical: #ff3d55;
  --sla-critical-dim: rgba(255, 61, 85, 0.14);
  --sla-breach: #ff1a37;

  /* ─── Operational Accents ─── */
  --accent-primary: #3d8bff;
  --accent-primary-dim: rgba(61, 139, 255, 0.15);
  --accent-dispatch: #a78bfa;
  --accent-rider: #38bdf8;
  --accent-revenue: #34d399;
  --accent-ai: #818cf8;
  --accent-ai-dim: rgba(129, 140, 248, 0.18);

  /* ─── Status Pills ─── */
  --status-pending: #6b7280;
  --status-confirmed: #3d8bff;
  --status-preparing: #f5a623;
  --status-ready: #a78bfa;
  --status-assigned: #38bdf8;
  --status-pickedup: #a78bfa;
  --status-delivered: #1adb8e;
  --status-cancelled: #ff3d55;
  --status-resale: #fbbf24;

  /* ─── Map ─── */
  --map-bg: #0f1419;
  --map-road: #1e2535;
  --map-water: #0d1520;
  --map-rider-active: #38bdf8;
  --map-rider-stale: #525a70;
  --map-order-pin: #f5a623;
  --map-batch-hull: rgba(167, 139, 250, 0.18);
  --map-batch-stroke: #a78bfa;

  /* ─── Type ─── */
  --font-mono: "DM Mono", ui-monospace, monospace;
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;

  /* ─── Spacing (4px base) ─── */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --radius: 8px;
}
```

- [ ] **Step 4: Write `frontend/src/styles/fonts.css`** (Google Fonts import — both families)

```css
@import url("https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap");
```

- [ ] **Step 5: Write `frontend/src/styles/base.css`** (reset + canvas + dark scrollbars + type defaults)

```css
*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html,
body,
#root {
  height: 100%;
}

body {
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
}

button,
input,
textarea,
select {
  font-family: inherit;
  font-size: inherit;
  color: inherit;
}

a {
  color: var(--accent-primary);
  text-decoration: none;
}

.mono {
  font-family: var(--font-mono);
}

.label-upper {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-secondary);
}

::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-track {
  background: var(--bg-canvas);
}
::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 6px;
}

@keyframes fade-up {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes slide-in-right {
  from {
    opacity: 0;
    transform: translateX(24px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes pulse-critical {
  0%,
  100% {
    background: var(--bg-surface);
  }
  50% {
    background: var(--sla-critical-dim);
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.001ms !important;
    transition-duration: 0.001ms !important;
  }
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npm run test -- tokens`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/styles
git commit -m "feat: tactical-dark design tokens and base styles from design brief"
```

---

### Task 3: API client, auth store, and shared types

**Files:** Create `frontend/src/lib/types.ts`, `frontend/src/lib/apiClient.ts`, `frontend/src/lib/auth.ts`. Tests: `frontend/src/lib/apiClient.test.ts`, `frontend/src/lib/auth.test.ts`.

- [ ] **Step 1: Write `frontend/src/lib/types.ts`** (DTOs mirroring backend schemas exactly)

```ts
export interface RestaurantOut {
  id: number;
  name: string;
  phone: string;
  lat: number;
  lng: number;
  settings: Record<string, unknown>;
}

export interface TokenOut {
  access_token: string;
  token_type: string;
}

export type RiderStatus = "available" | "on_delivery" | "off_shift" | "deactivated";

export interface RiderOut {
  id: number;
  name: string;
  phone: string;
  status: RiderStatus;
}

export interface DishOut {
  id: number;
  dish_number: number | null;
  name: string;
  price_aed: string | null;
  category: string | null;
  description: string | null;
  is_available: boolean;
}

export interface DiffOut {
  price_changes: Array<Record<string, unknown>>;
  added: Array<Record<string, unknown>>;
  removed: Array<Record<string, unknown>>;
  conflicts: Array<Record<string, unknown>>;
}

export interface MenuOut {
  id: number;
  version: number;
  status: string;
  dishes: DishOut[];
}

export interface MenuWithDiffOut extends MenuOut {
  diff_vs_active: DiffOut | null;
}

// FSM states from src/app/ordering/fsm.py
export type OrderStatus =
  | "draft"
  | "pending_confirmation"
  | "confirmed"
  | "preparing"
  | "ready"
  | "assigned"
  | "picked_up"
  | "arriving"
  | "delivered"
  | "cancelled"
  | "undeliverable"
  | "on_resale"
  | "resold"
  | "written_off";

export interface OrderItemOut {
  dish_number: number | null;
  name: string;
  qty: number;
  price_aed: string;
}

export interface OrderOut {
  id: number;
  status: OrderStatus;
  customer_name: string;
  customer_phone: string;
  items: OrderItemOut[];
  total_aed: string;
  rider_id: number | null;
  rider_name: string | null;
  /** ISO 8601 — when the 40-min SLA clock started (order confirmed). */
  sla_started_at: string | null;
  created_at: string;
  address: string | null;
  lat: number | null;
  lng: number | null;
}

export interface ConversationOut {
  id: number;
  phone: string;
  counterpart: string;
  manual_takeover: boolean;
  last_message_preview: string | null;
  unread: boolean;
  updated_at: string;
}

export interface MessageOut {
  id: number;
  direction: "inbound" | "outbound";
  type: string;
  payload: Record<string, unknown>;
  ts: number;
}
```

NOTE: `OrderOut` / `ConversationOut` / `MessageOut` are the **contract this dashboard expects**. If the Phase 3/Phase 2 backend schemas differ when wiring live, adjust these types in one place; fixtures (Task 6/12) define the canonical shape for tests.

- [ ] **Step 2: Write the failing apiClient test** — `frontend/src/lib/apiClient.test.ts`

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiClient } from "./apiClient";

describe("apiClient", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it("injects bearer token from localStorage", async () => {
    localStorage.setItem("ops_token", "tok-123");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiClient.get("/api/v1/me");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  it("omits Authorization when no token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("{}", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiClient.get("/api/v1/health");
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("throws ApiError with status and detail on non-2xx", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "bad credentials" }), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiClient.post("/api/v1/auth/login", {})).rejects.toMatchObject({
      status: 401,
      detail: "bad credentials",
    });
    await expect(apiClient.post("/api/v1/auth/login", {})).rejects.toBeInstanceOf(ApiError);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm run test -- apiClient`
Expected: FAIL — module not found.

- [ ] **Step 4: Write `frontend/src/lib/apiClient.ts`**

```ts
const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const TOKEN_KEY = "ops_token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  isForm = false,
): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders() };
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    if (isForm) {
      payload = body as FormData;
    } else {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
  }
  const resp = await fetch(`${API_BASE}${path}`, { method, headers, body: payload });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const apiClient = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
  postForm: <T>(path: string, form: FormData) => request<T>("POST", path, form, true),
  TOKEN_KEY,
};
```

- [ ] **Step 5: Write the failing auth test** — `frontend/src/lib/auth.test.ts`

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getToken, login, logout, setToken } from "./auth";

describe("auth store", () => {
  beforeEach(() => localStorage.clear());

  it("stores and reads token", () => {
    setToken("abc");
    expect(getToken()).toBe("abc");
  });

  it("logout clears token", () => {
    setToken("abc");
    logout();
    expect(getToken()).toBeNull();
  });

  it("login posts credentials and persists token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access_token: "jwt-xyz", token_type: "bearer" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await login("+97150000000", "password1");
    expect(getToken()).toBe("jwt-xyz");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/auth/login");
  });
});
```

- [ ] **Step 6: Write `frontend/src/lib/auth.ts`**

```ts
import { apiClient } from "./apiClient";
import type { TokenOut } from "./types";

const TOKEN_KEY = apiClient.TOKEN_KEY;

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

export async function login(phone: string, password: string): Promise<void> {
  const res = await apiClient.post<TokenOut>("/api/v1/auth/login", { phone, password });
  setToken(res.access_token);
}
```

NOTE on httpOnly: brief/scope calls for localStorage now with a documented upgrade path. localStorage is chosen because the SPA is served separately from the API (cross-origin) and needs the token for the `Authorization` header; an httpOnly-cookie flow would require backend CSRF + same-site cookie issuance not yet built. Leave a `// SECURITY: migrate to httpOnly cookie + CSRF when backend supports it` comment above `setToken`.

- [ ] **Step 7: Run tests to verify pass**

Run: `cd frontend && npm run test -- apiClient auth && npm run lint`
Expected: all PASS, type-check clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/apiClient.ts frontend/src/lib/auth.ts frontend/src/lib/apiClient.test.ts frontend/src/lib/auth.test.ts
git commit -m "feat: typed fetch API client, auth store, shared DTO types"
```

---

### Task 4: SLA math + real-time transport abstraction

**Files:** Create `frontend/src/lib/sla.ts`, `frontend/src/lib/transport/index.ts`, `frontend/src/lib/transport/pollingTransport.ts`, `frontend/src/lib/usePoll.ts`. Tests: `frontend/src/lib/sla.test.ts`, `frontend/src/lib/transport/pollingTransport.test.ts`, `frontend/src/lib/usePoll.test.tsx`.

**SLA rules (brief §3.1):** 40-minute breach window from `sla_started_at`. Remaining = white >15min, `--sla-warn` 10–15min, `--sla-critical` <10min, `--sla-breach` at ≤0. (The board groups by *elapsed*: yellow lane 30–35min elapsed, red lane 35–40min — derived from the same remaining value.)

- [ ] **Step 1: Write the failing SLA test** — `frontend/src/lib/sla.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { formatCountdown, remainingMs, slaTier } from "./sla";

const NOW = Date.parse("2026-06-06T10:00:00Z");
const iso = (minsAgo: number) => new Date(NOW - minsAgo * 60_000).toISOString();

describe("sla", () => {
  it("remainingMs counts down from 40-min window", () => {
    expect(remainingMs(iso(0), NOW)).toBe(40 * 60_000);
    expect(remainingMs(iso(30), NOW)).toBe(10 * 60_000);
    expect(remainingMs(iso(45), NOW)).toBe(-5 * 60_000);
  });

  it("remainingMs returns full window when start is null", () => {
    expect(remainingMs(null, NOW)).toBe(40 * 60_000);
  });

  it.each([
    [0, "safe"],
    [24, "safe"],
    [26, "warn"], // 14 min remaining
    [31, "critical"], // 9 min remaining
    [40, "breach"],
    [42, "breach"],
  ])("slaTier at %i min elapsed = %s", (mins, tier) => {
    expect(slaTier(iso(mins), NOW)).toBe(tier);
  });

  it("formatCountdown renders MM:SS, clamps at 00:00", () => {
    expect(formatCountdown(10 * 60_000 + 5_000)).toBe("10:05");
    expect(formatCountdown(-3_000)).toBe("00:00");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- sla`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `frontend/src/lib/sla.ts`**

```ts
export const SLA_WINDOW_MS = 40 * 60_000;

export type SlaTier = "safe" | "warn" | "critical" | "breach";

export function remainingMs(slaStartedAt: string | null, now: number = Date.now()): number {
  if (!slaStartedAt) return SLA_WINDOW_MS;
  const elapsed = now - Date.parse(slaStartedAt);
  return SLA_WINDOW_MS - elapsed;
}

export function slaTier(slaStartedAt: string | null, now: number = Date.now()): SlaTier {
  const rem = remainingMs(slaStartedAt, now);
  if (rem <= 0) return "breach";
  if (rem < 10 * 60_000) return "critical";
  if (rem < 15 * 60_000) return "warn";
  return "safe";
}

export function tierColorVar(tier: SlaTier): string {
  switch (tier) {
    case "safe":
      return "var(--text-primary)";
    case "warn":
      return "var(--sla-warn)";
    case "critical":
      return "var(--sla-critical)";
    case "breach":
      return "var(--sla-breach)";
  }
}

export function formatCountdown(ms: number): string {
  const clamped = Math.max(0, ms);
  const totalSec = Math.floor(clamped / 1000);
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}
```

- [ ] **Step 4: Write the failing transport test** — `frontend/src/lib/transport/pollingTransport.test.ts`

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PollingTransport } from "./pollingTransport";

describe("PollingTransport", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("calls fetcher immediately then on interval, pushing to subscriber", async () => {
    let n = 0;
    const fetcher = vi.fn(async () => ++n);
    const received: number[] = [];
    const t = new PollingTransport(fetcher, 3000);
    const unsub = t.subscribe((v) => received.push(v));

    await vi.advanceTimersByTimeAsync(0); // immediate fetch
    expect(received).toEqual([1]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(received).toEqual([1, 2]);
    unsub();
    await vi.advanceTimersByTimeAsync(6000);
    expect(received).toEqual([1, 2]); // stopped after unsubscribe
  });

  it("surfaces fetch errors to onError without stopping the loop", async () => {
    let call = 0;
    const fetcher = vi.fn(async () => {
      call++;
      if (call === 1) throw new Error("net down");
      return call;
    });
    const errors: unknown[] = [];
    const values: number[] = [];
    const t = new PollingTransport(fetcher, 1000);
    t.subscribe((v) => values.push(v), (e) => errors.push(e));

    await vi.advanceTimersByTimeAsync(0);
    expect(errors).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(values).toEqual([2]); // recovered
  });
});
```

- [ ] **Step 5: Write `frontend/src/lib/transport/index.ts`**

```ts
export type Listener<T> = (value: T) => void;
export type ErrorListener = (err: unknown) => void;

/** Real-time transport contract. PollingTransport is the default impl;
 * a WebSocketTransport can be dropped in later with the same surface. */
export interface Transport<T> {
  subscribe(onValue: Listener<T>, onError?: ErrorListener): () => void;
}
```

- [ ] **Step 6: Write `frontend/src/lib/transport/pollingTransport.ts`**

```ts
import type { ErrorListener, Listener, Transport } from "./index";

export class PollingTransport<T> implements Transport<T> {
  private timer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<{ onValue: Listener<T>; onError?: ErrorListener }>();

  constructor(
    private fetcher: () => Promise<T>,
    private intervalMs: number,
  ) {}

  private async tick(): Promise<void> {
    try {
      const value = await this.fetcher();
      for (const l of this.listeners) l.onValue(value);
    } catch (err) {
      for (const l of this.listeners) l.onError?.(err);
    }
  }

  subscribe(onValue: Listener<T>, onError?: ErrorListener): () => void {
    const entry = { onValue, onError };
    this.listeners.add(entry);
    if (this.timer === null) {
      void this.tick(); // fire immediately
      this.timer = setInterval(() => void this.tick(), this.intervalMs);
    }
    return () => {
      this.listeners.delete(entry);
      if (this.listeners.size === 0 && this.timer !== null) {
        clearInterval(this.timer);
        this.timer = null;
      }
    };
  }
}
```

- [ ] **Step 7: Write the failing usePoll test** — `frontend/src/lib/usePoll.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { usePoll } from "./usePoll";

function Probe({ fetcher }: { fetcher: () => Promise<string> }) {
  const { data, error } = usePoll(fetcher, 1000);
  return <div>{error ? `err:${String(error)}` : (data ?? "loading")}</div>;
}

describe("usePoll", () => {
  it("renders fetched data", async () => {
    const fetcher = vi.fn(async () => "HELLO");
    render(<Probe fetcher={fetcher} />);
    await waitFor(() => expect(screen.getByText("HELLO")).toBeInTheDocument());
  });
});
```

- [ ] **Step 8: Write `frontend/src/lib/usePoll.ts`**

```ts
import { useEffect, useRef, useState } from "react";
import { PollingTransport } from "./transport/pollingTransport";

export function usePoll<T>(fetcher: () => Promise<T>, intervalMs = 4000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    const transport = new PollingTransport<T>(() => fetcherRef.current(), intervalMs);
    const unsub = transport.subscribe(
      (v) => {
        setData(v);
        setError(null);
      },
      (e) => setError(e),
    );
    return unsub;
  }, [intervalMs]);

  return { data, error };
}
```

- [ ] **Step 9: Run all lib tests + type-check**

Run: `cd frontend && npm run test -- sla transport usePoll && npm run lint`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/lib/sla.ts frontend/src/lib/sla.test.ts frontend/src/lib/transport frontend/src/lib/usePoll.ts frontend/src/lib/usePoll.test.tsx
git commit -m "feat: SLA countdown math + polling transport abstraction (WS-swappable) + usePoll hook"
```

---

### Task 5: Primitive components — Button, Spinner, StatusPill, SectionBanner, SideDrawer

**Files:** Create `frontend/src/components/Button.tsx`, `Spinner.tsx`, `StatusPill.tsx`, `SectionBanner.tsx`, `SideDrawer.tsx` (each with a colocated `.module.css`). Tests: `StatusPill.test.tsx`, `SideDrawer.test.tsx`.

CSS-MODULE CONVENTION: every component owns a `Name.module.css`. Import as `import s from "./Name.module.css"`. Vite handles CSS modules out of the box. Use `var(--token)` for every color/space.

- [ ] **Step 1: Write `frontend/src/components/Button.tsx`**

```tsx
import type { ButtonHTMLAttributes } from "react";
import s from "./Button.module.css";

type Variant = "primary" | "ghost" | "danger";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({ variant = "primary", className = "", ...rest }: Props) {
  return <button className={`${s.btn} ${s[variant]} ${className}`} {...rest} />;
}
```

`frontend/src/components/Button.module.css`:

```css
.btn {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  padding: 8px 14px;
  border-radius: var(--radius);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 150ms ease-out, border-color 150ms ease-out;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.primary {
  background: var(--accent-primary);
  color: var(--text-inverse);
}
.primary:hover:not(:disabled) {
  background: #2f7bf0;
}
.ghost {
  background: transparent;
  border-color: var(--border-default);
  color: var(--text-primary);
}
.ghost:hover:not(:disabled) {
  border-color: var(--border-strong);
}
.danger {
  background: transparent;
  border-color: var(--sla-critical);
  color: var(--sla-critical);
}
.danger:hover:not(:disabled) {
  background: var(--sla-critical-dim);
}
```

- [ ] **Step 2: Write `frontend/src/components/Spinner.tsx`** + `Spinner.module.css`

```tsx
import s from "./Spinner.module.css";
export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className={s.spinner} role="status" aria-label={label} />;
}
```

```css
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--border-default);
  border-top-color: var(--accent-primary);
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
```

- [ ] **Step 3: Write the failing StatusPill test** — `frontend/src/components/StatusPill.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("renders human label for FSM status", () => {
    render(<StatusPill status="picked_up" />);
    expect(screen.getByText("Picked Up")).toBeInTheDocument();
  });

  it("sets color CSS var from status", () => {
    render(<StatusPill status="delivered" />);
    const pill = screen.getByText("Delivered");
    expect(pill.style.getPropertyValue("--pill")).toBe("var(--status-delivered)");
  });

  it("falls back to muted for unknown status", () => {
    // @ts-expect-error testing runtime fallback
    render(<StatusPill status="weird_state" />);
    expect(screen.getByText("weird_state")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Write `frontend/src/components/StatusPill.tsx`** + `StatusPill.module.css`

```tsx
import type { OrderStatus } from "../lib/types";
import s from "./StatusPill.module.css";

const LABELS: Record<string, string> = {
  draft: "Draft",
  pending_confirmation: "Pending",
  confirmed: "Confirmed",
  preparing: "Preparing",
  ready: "Ready",
  assigned: "Assigned",
  picked_up: "Picked Up",
  arriving: "Arriving",
  delivered: "Delivered",
  cancelled: "Cancelled",
  undeliverable: "Undeliverable",
  on_resale: "On Resale",
  resold: "Resold",
  written_off: "Written Off",
};

const COLOR: Record<string, string> = {
  pending_confirmation: "var(--status-pending)",
  confirmed: "var(--status-confirmed)",
  preparing: "var(--status-preparing)",
  ready: "var(--status-ready)",
  assigned: "var(--status-assigned)",
  picked_up: "var(--status-pickedup)",
  arriving: "var(--status-pickedup)",
  delivered: "var(--status-delivered)",
  cancelled: "var(--status-cancelled)",
  undeliverable: "var(--status-cancelled)",
  on_resale: "var(--status-resale)",
  resold: "var(--status-resale)",
};

export function StatusPill({ status }: { status: OrderStatus }) {
  const label = LABELS[status] ?? status;
  const color = COLOR[status] ?? "var(--text-muted)";
  return (
    <span className={s.pill} style={{ ["--pill" as string]: color }}>
      {label}
    </span>
  );
}
```

```css
.pill {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  color: var(--pill);
  background: color-mix(in srgb, var(--pill) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--pill) 35%, transparent);
  white-space: nowrap;
}
```

- [ ] **Step 5: Write `frontend/src/components/SectionBanner.tsx`** + `SectionBanner.module.css`

```tsx
import type { ReactNode } from "react";
import s from "./SectionBanner.module.css";

type Tone = "warning" | "error" | "info" | "success";

export function SectionBanner({
  tone,
  children,
  onDismiss,
}: {
  tone: Tone;
  children: ReactNode;
  onDismiss?: () => void;
}) {
  return (
    <div className={`${s.banner} ${s[tone]}`} role="status">
      <span>{children}</span>
      {onDismiss && (
        <button className={s.x} onClick={onDismiss} aria-label="Dismiss">
          ✕
        </button>
      )}
    </div>
  );
}
```

```css
.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 500;
  border-radius: var(--radius);
}
.warning {
  background: var(--sla-warn-dim);
  color: var(--sla-warn);
  border: 1px solid var(--sla-warn);
}
.error {
  background: var(--sla-critical-dim);
  color: var(--sla-critical);
  border: 1px solid var(--sla-critical);
}
.info {
  background: var(--accent-primary-dim);
  color: var(--accent-primary);
  border: 1px solid var(--accent-primary);
}
.success {
  background: var(--sla-safe-dim);
  color: var(--sla-safe);
  border: 1px solid var(--sla-safe);
}
.x {
  background: none;
  border: none;
  cursor: pointer;
  color: inherit;
  opacity: 0.7;
}
```

- [ ] **Step 6: Write the failing SideDrawer test** — `frontend/src/components/SideDrawer.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SideDrawer } from "./SideDrawer";

describe("SideDrawer", () => {
  it("renders children when open", () => {
    render(
      <SideDrawer open title="Order #047" onClose={() => {}}>
        <p>Detail body</p>
      </SideDrawer>,
    );
    expect(screen.getByText("Detail body")).toBeInTheDocument();
    expect(screen.getByText("Order #047")).toBeInTheDocument();
  });

  it("does not render content when closed", () => {
    render(
      <SideDrawer open={false} title="X" onClose={() => {}}>
        <p>Hidden</p>
      </SideDrawer>,
    );
    expect(screen.queryByText("Hidden")).not.toBeInTheDocument();
  });

  it("calls onClose on scrim click", async () => {
    const onClose = vi.fn();
    render(
      <SideDrawer open title="X" onClose={onClose}>
        <p>Body</p>
      </SideDrawer>,
    );
    await userEvent.click(screen.getByTestId("drawer-scrim"));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 7: Write `frontend/src/components/SideDrawer.tsx`** + `SideDrawer.module.css`

```tsx
import type { ReactNode } from "react";
import s from "./SideDrawer.module.css";

export function SideDrawer({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className={s.root}>
      <div className={s.scrim} data-testid="drawer-scrim" onClick={onClose} />
      <aside className={s.panel} role="dialog" aria-label={title}>
        <header className={s.head}>
          <span className={s.title}>{title}</span>
          <button className={s.x} onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className={s.body}>{children}</div>
      </aside>
    </div>
  );
}
```

```css
.root {
  position: fixed;
  inset: 0;
  z-index: 50;
}
.scrim {
  position: absolute;
  inset: 0;
  background: var(--bg-overlay);
}
.panel {
  position: absolute;
  top: 0;
  right: 0;
  height: 100%;
  width: 480px;
  background: var(--bg-surface-raised);
  border-left: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  animation: slide-in-right 180ms ease-out;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border-subtle);
}
.title {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 15px;
}
.x {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
}
.body {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}
```

- [ ] **Step 8: Run tests + type-check**

Run: `cd frontend && npm run test -- StatusPill SideDrawer && npm run lint`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/Button.tsx frontend/src/components/Button.module.css frontend/src/components/Spinner.tsx frontend/src/components/Spinner.module.css frontend/src/components/StatusPill.tsx frontend/src/components/StatusPill.module.css frontend/src/components/StatusPill.test.tsx frontend/src/components/SectionBanner.tsx frontend/src/components/SectionBanner.module.css frontend/src/components/SideDrawer.tsx frontend/src/components/SideDrawer.module.css frontend/src/components/SideDrawer.test.tsx
git commit -m "feat: primitive components (Button, Spinner, StatusPill, SectionBanner, SideDrawer)"
```

---

### Task 6: App shell, router, AuthGuard, NavSidebar, Login screen

**Files:** Replace `frontend/src/App.tsx`. Create `frontend/src/components/AppShell.tsx` (+css), `frontend/src/components/NavSidebar.tsx` (+css), `frontend/src/screens/LoginScreen.tsx` (+css). Tests: `frontend/src/screens/LoginScreen.test.tsx`, `frontend/src/App.test.tsx`.

- [ ] **Step 1: Write the failing Login test** — `frontend/src/screens/LoginScreen.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginScreen } from "./LoginScreen";

describe("LoginScreen", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("submits credentials and stores token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access_token: "jwt-1", token_type: "bearer" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <LoginScreen />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText(/phone/i), "+97150000000");
    await userEvent.type(screen.getByLabelText(/password/i), "password1");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(localStorage.getItem("ops_token")).toBe("jwt-1"));
  });

  it("shows error banner on 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "bad credentials" }), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <LoginScreen />
      </MemoryRouter>,
    );
    await userEvent.type(screen.getByLabelText(/phone/i), "+97150000000");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(screen.getByText(/bad credentials/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Write `frontend/src/screens/LoginScreen.tsx`** + `LoginScreen.module.css`

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { ApiError } from "../lib/apiClient";
import { login } from "../lib/auth";
import s from "./LoginScreen.module.css";

export function LoginScreen() {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(phone, password);
      nav("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.wrap}>
      <form className={s.card} onSubmit={submit}>
        <div className={s.brand}>OPS TERMINAL</div>
        {error && <SectionBanner tone="error">{error}</SectionBanner>}
        <label className={s.field}>
          <span className="label-upper">Phone</span>
          <input
            aria-label="Phone"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="username"
          />
        </label>
        <label className={s.field}>
          <span className="label-upper">Password</span>
          <input
            aria-label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        <Button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign In"}
        </Button>
      </form>
    </div>
  );
}
```

```css
.wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
.card {
  width: 360px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 28px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.brand {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 18px;
  letter-spacing: 0.15em;
  text-align: center;
  color: var(--text-primary);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field input {
  background: var(--bg-surface-inset);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  padding: 9px 12px;
  color: var(--text-primary);
}
.field input:focus {
  outline: none;
  border-color: var(--accent-primary);
}
```

- [ ] **Step 3: Write `frontend/src/components/NavSidebar.tsx`** + `NavSidebar.module.css`

```tsx
import { NavLink } from "react-router-dom";
import s from "./NavSidebar.module.css";

const ITEMS: Array<{ to: string; label: string }> = [
  { to: "/", label: "Live Ops" },
  { to: "/orders", label: "Orders" },
  { to: "/menu", label: "Menu" },
  { to: "/riders", label: "Riders" },
  { to: "/conversations", label: "Conversations" },
  { to: "/analytics", label: "Analytics" },
  { to: "/settings", label: "Settings" },
];

export function NavSidebar({ unread = 0 }: { unread?: number }) {
  return (
    <nav className={s.nav}>
      <div className={s.logo}>OPS</div>
      {ITEMS.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.to === "/"}
          className={({ isActive }) => `${s.item} ${isActive ? s.active : ""}`}
        >
          {it.label}
          {it.to === "/conversations" && unread > 0 && (
            <span className={s.badge}>{unread}</span>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
```

```css
.nav {
  width: 220px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  padding: 16px 8px;
  gap: 2px;
}
.logo {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.2em;
  padding: 8px 12px 16px;
  color: var(--text-primary);
}
.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  padding: 9px 12px;
  border-radius: 6px;
}
.item:hover {
  background: var(--bg-surface-raised);
  color: var(--text-primary);
}
.active {
  background: var(--accent-primary-dim);
  color: var(--accent-primary);
}
.badge {
  font-family: var(--font-mono);
  font-size: 10px;
  background: var(--sla-critical);
  color: var(--text-inverse);
  border-radius: 8px;
  padding: 1px 6px;
}
```

- [ ] **Step 4: Write `frontend/src/components/AppShell.tsx`** + `AppShell.module.css`

```tsx
import type { ReactNode } from "react";
import { NavSidebar } from "./NavSidebar";
import { SectionBanner } from "./SectionBanner";
import s from "./AppShell.module.css";

export function AppShell({
  children,
  connectionDown = false,
  unread = 0,
}: {
  children: ReactNode;
  connectionDown?: boolean;
  unread?: number;
}) {
  return (
    <div className={s.shell}>
      <NavSidebar unread={unread} />
      <main className={s.main}>
        {connectionDown && (
          <SectionBanner tone="warning">
            Live updates paused — reconnecting.
          </SectionBanner>
        )}
        {children}
      </main>
    </div>
  );
}
```

```css
.shell {
  display: flex;
  height: 100%;
}
.main {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
```

- [ ] **Step 5: Write the failing App routing test** — `frontend/src/App.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App";

describe("App routing", () => {
  beforeEach(() => localStorage.clear());

  it("redirects unauthenticated users to /login", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText(/sign in/i)).toBeInTheDocument();
  });

  it("renders shell when authenticated", () => {
    localStorage.setItem("ops_token", "tok");
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(screen.getByText("Live Ops")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Write `frontend/src/App.tsx`** (real router + AuthGuard). Import each screen; screens not yet built in later tasks get a one-line placeholder export now and are filled in their own task — to keep this compiling, create minimal placeholder screen files for any screen not yet implemented (each: `export function XScreen(){return <div className="label-upper">X</div>}`). Replace placeholders in their dedicated tasks.

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { isAuthenticated } from "./lib/auth";
import { AnalyticsScreen } from "./screens/AnalyticsScreen";
import { ConversationsScreen } from "./screens/ConversationsScreen";
import { LiveOpsScreen } from "./screens/LiveOpsScreen";
import { LoginScreen } from "./screens/LoginScreen";
import { MenuManagerScreen } from "./screens/MenuManagerScreen";
import { OrdersScreen } from "./screens/OrdersScreen";
import { RidersScreen } from "./screens/RidersScreen";
import { SettingsScreen } from "./screens/SettingsScreen";

function Guarded({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <AppShell>{children}</AppShell>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/" element={<Guarded><LiveOpsScreen /></Guarded>} />
      <Route path="/orders" element={<Guarded><OrdersScreen /></Guarded>} />
      <Route path="/menu" element={<Guarded><MenuManagerScreen /></Guarded>} />
      <Route path="/riders" element={<Guarded><RidersScreen /></Guarded>} />
      <Route path="/conversations" element={<Guarded><ConversationsScreen /></Guarded>} />
      <Route path="/analytics" element={<Guarded><AnalyticsScreen /></Guarded>} />
      <Route path="/settings" element={<Guarded><SettingsScreen /></Guarded>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

- [ ] **Step 7: Create placeholder screen files** so App compiles — for each of `LiveOpsScreen`, `OrdersScreen`, `MenuManagerScreen`, `RidersScreen`, `ConversationsScreen`, `AnalyticsScreen`, `SettingsScreen` create `frontend/src/screens/<Name>.tsx`:

```tsx
export function LiveOpsScreen() {
  return <div className="label-upper">Live Ops</div>;
}
```
(adjust name/label per file; these are replaced in Tasks 7–13 except Analytics which stays a placeholder per scope).

- [ ] **Step 8: Run tests + type-check + build**

Run: `cd frontend && npm run test -- LoginScreen App && npm run lint && npm run build`
Expected: all PASS, build clean.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/components/AppShell.tsx frontend/src/components/AppShell.module.css frontend/src/components/NavSidebar.tsx frontend/src/components/NavSidebar.module.css frontend/src/screens
git commit -m "feat: app shell, router with AuthGuard, nav sidebar, login screen"
```

---

### Task 7: Orders data layer — fixtures, ordersApi with fixture fallback, CountdownTimer, KPITile

**Files:** Create `frontend/src/lib/fixtures/orders.json`, `frontend/src/lib/ordersApi.ts`, `frontend/src/components/CountdownTimer.tsx` (+css), `frontend/src/components/KPITile.tsx` (+css). Tests: `frontend/src/lib/ordersApi.test.ts`, `frontend/src/components/CountdownTimer.test.tsx`, `frontend/src/components/KPITile.test.tsx`.

**Why a fixture fallback:** the Orders backend (Phase 3 Task 9) may not be deployed when this UI is built. `ordersApi` tries the live endpoint and, on 404/connection error, returns recorded fixtures so the Live Ops board renders and tests pass deterministically. When the real endpoint exists, it is used automatically — no code change.

- [ ] **Step 1: Write `frontend/src/lib/fixtures/orders.json`** (realistic sample; timestamps relative-safe — use fixed ISO and let SLA math compute against `Date.now()` in dev, tests pin `now`)

```json
[
  {
    "id": 47,
    "status": "preparing",
    "customer_name": "Ali Hassan",
    "customer_phone": "+971501234567",
    "items": [{ "dish_number": 110, "name": "Chicken Biryani", "qty": 2, "price_aed": "22.00" }],
    "total_aed": "44.00",
    "rider_id": null,
    "rider_name": null,
    "sla_started_at": "2026-06-06T09:28:00Z",
    "created_at": "2026-06-06T09:27:30Z",
    "address": "Jumeirah 1, Villa 12",
    "lat": 25.2048,
    "lng": 55.2708
  },
  {
    "id": 48,
    "status": "assigned",
    "customer_name": "Omar Farouq",
    "customer_phone": "+971559876543",
    "items": [{ "dish_number": 201, "name": "Mutton Karahi", "qty": 1, "price_aed": "35.00" }],
    "total_aed": "40.00",
    "rider_id": 3,
    "rider_name": "Bilal",
    "sla_started_at": "2026-06-06T09:33:00Z",
    "created_at": "2026-06-06T09:32:40Z",
    "address": "Business Bay, Tower 3",
    "lat": 25.1865,
    "lng": 55.2654
  },
  {
    "id": 49,
    "status": "confirmed",
    "customer_name": "Sara Khan",
    "customer_phone": "+971502223344",
    "items": [{ "dish_number": 110, "name": "Chicken Biryani", "qty": 1, "price_aed": "22.00" }],
    "total_aed": "27.00",
    "rider_id": null,
    "rider_name": null,
    "sla_started_at": "2026-06-06T09:42:00Z",
    "created_at": "2026-06-06T09:41:50Z",
    "address": "Al Barsha 2",
    "lat": 25.1119,
    "lng": 55.2003
  }
]
```

- [ ] **Step 2: Write the failing ordersApi test** — `frontend/src/lib/ordersApi.test.ts`

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchOrders } from "./ordersApi";

describe("ordersApi", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns live orders when endpoint responds", async () => {
    const live = [{ id: 1, status: "ready", customer_name: "X", customer_phone: "+9715", items: [], total_aed: "10.00", rider_id: null, rider_name: null, sla_started_at: null, created_at: "2026-06-06T09:00:00Z", address: null, lat: null, lng: null }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(live), { status: 200 })));
    const orders = await fetchOrders();
    expect(orders).toHaveLength(1);
    expect(orders[0].customer_name).toBe("X");
  });

  it("falls back to fixtures on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not found", { status: 404 })));
    const orders = await fetchOrders();
    expect(orders.length).toBeGreaterThan(0);
    expect(orders.some((o) => o.id === 47)).toBe(true);
  });

  it("falls back to fixtures on network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const orders = await fetchOrders();
    expect(orders.some((o) => o.id === 47)).toBe(true);
  });
});
```

- [ ] **Step 3: Write `frontend/src/lib/ordersApi.ts`**

```ts
import { apiClient, ApiError } from "./apiClient";
import fixtureOrders from "./fixtures/orders.json";
import type { OrderOut } from "./types";

export async function fetchOrders(): Promise<OrderOut[]> {
  try {
    return await apiClient.get<OrderOut[]>("/api/v1/orders");
  } catch (err) {
    // Endpoint not yet deployed (404) or backend unreachable → recorded fixtures.
    if (err instanceof ApiError && err.status !== 404) throw err;
    return fixtureOrders as OrderOut[];
  }
}

export async function fetchOrder(id: number): Promise<OrderOut> {
  try {
    return await apiClient.get<OrderOut>(`/api/v1/orders/${id}`);
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
    const match = (fixtureOrders as OrderOut[]).find((o) => o.id === id);
    if (!match) throw err;
    return match;
  }
}
```

- [ ] **Step 4: Write the failing CountdownTimer test** — `frontend/src/components/CountdownTimer.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CountdownTimer } from "./CountdownTimer";

const NOW = Date.parse("2026-06-06T10:00:00Z");
const iso = (m: number) => new Date(NOW - m * 60_000).toISOString();

describe("CountdownTimer", () => {
  beforeEach(() => vi.useFakeTimers({ now: NOW }));
  afterEach(() => vi.useRealTimers());

  it("renders MM:SS remaining", () => {
    render(<CountdownTimer slaStartedAt={iso(30)} />); // 10 min left
    expect(screen.getByText("10:00")).toBeInTheDocument();
  });

  it("applies critical tier under 10 min", () => {
    render(<CountdownTimer slaStartedAt={iso(31)} />);
    const el = screen.getByTestId("countdown");
    expect(el.style.color).toContain("sla-critical");
  });

  it("freezes at 00:00 on breach", () => {
    render(<CountdownTimer slaStartedAt={iso(45)} />);
    expect(screen.getByText("00:00")).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Write `frontend/src/components/CountdownTimer.tsx`** + `CountdownTimer.module.css`

```tsx
import { useEffect, useState } from "react";
import { formatCountdown, remainingMs, slaTier, tierColorVar } from "../lib/sla";
import s from "./CountdownTimer.module.css";

export function CountdownTimer({ slaStartedAt }: { slaStartedAt: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const rem = remainingMs(slaStartedAt, now);
  const tier = slaTier(slaStartedAt, now);
  const urgent = rem > 0 && rem < 5 * 60_000;

  return (
    <span
      data-testid="countdown"
      className={`${s.timer} ${urgent ? s.urgent : ""} ${tier === "breach" ? s.breach : ""}`}
      style={{ color: tierColorVar(tier) }}
    >
      {formatCountdown(rem)}
    </span>
  );
}
```

```css
.timer {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 24px;
  font-variant-numeric: tabular-nums;
  transition: color 400ms ease-out;
}
.urgent {
  font-size: 26px;
  letter-spacing: 0.04em;
}
.breach {
  animation: pulse-critical 1s infinite;
}
```

- [ ] **Step 6: Write the failing KPITile test** — `frontend/src/components/KPITile.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KPITile } from "./KPITile";

describe("KPITile", () => {
  it("renders label, value, and positive delta in safe color", () => {
    render(<KPITile label="Revenue Today" value="AED 4,820" delta={12} />);
    expect(screen.getByText("Revenue Today")).toBeInTheDocument();
    expect(screen.getByText("AED 4,820")).toBeInTheDocument();
    const delta = screen.getByText(/↑/);
    expect(delta.style.color).toContain("sla-safe");
  });

  it("renders negative delta in critical color", () => {
    render(<KPITile label="SLA %" value="92%" delta={-4} />);
    expect(screen.getByText(/↓/).style.color).toContain("sla-critical");
  });
});
```

- [ ] **Step 7: Write `frontend/src/components/KPITile.tsx`** + `KPITile.module.css`

```tsx
import s from "./KPITile.module.css";

export function KPITile({
  label,
  value,
  delta,
}: {
  label: string;
  value: string;
  delta?: number;
}) {
  return (
    <div className={s.tile}>
      <span className="label-upper">{label}</span>
      <span className={s.value}>{value}</span>
      {delta !== undefined && delta !== 0 && (
        <span
          className={s.delta}
          style={{ color: delta > 0 ? "var(--sla-safe)" : "var(--sla-critical)" }}
        >
          {delta > 0 ? "↑" : "↓"} {Math.abs(delta)}%
        </span>
      )}
    </div>
  );
}
```

```css
.tile {
  min-width: 150px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.value {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 32px;
  line-height: 1;
  color: var(--text-primary);
}
.delta {
  font-family: var(--font-mono);
  font-size: 12px;
}
```

- [ ] **Step 8: Run tests + type-check**

Run: `cd frontend && npm run test -- ordersApi CountdownTimer KPITile && npm run lint`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/fixtures/orders.json frontend/src/lib/ordersApi.ts frontend/src/lib/ordersApi.test.ts frontend/src/components/CountdownTimer.tsx frontend/src/components/CountdownTimer.module.css frontend/src/components/CountdownTimer.test.tsx frontend/src/components/KPITile.tsx frontend/src/components/KPITile.module.css frontend/src/components/KPITile.test.tsx
git commit -m "feat: orders data layer with fixture fallback, CountdownTimer, KPITile"
```

---

### Task 8: SLAOrderCard + LiveOrderRow components

**Files:** Create `frontend/src/components/SLAOrderCard.tsx` (+css), `frontend/src/components/LiveOrderRow.tsx` (+css). Tests: `frontend/src/components/SLAOrderCard.test.tsx`, `frontend/src/components/LiveOrderRow.test.tsx`.

- [ ] **Step 1: Write the failing SLAOrderCard test** — `frontend/src/components/SLAOrderCard.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SLAOrderCard } from "./SLAOrderCard";
import type { OrderOut } from "../lib/types";

const NOW = Date.parse("2026-06-06T10:00:00Z");
const iso = (m: number) => new Date(NOW - m * 60_000).toISOString();

function order(over: Partial<OrderOut> = {}): OrderOut {
  return {
    id: 47, status: "preparing", customer_name: "Ali", customer_phone: "+9715",
    items: [{ dish_number: 110, name: "Biryani", qty: 2, price_aed: "22.00" }],
    total_aed: "44.00", rider_id: null, rider_name: null,
    sla_started_at: iso(32), created_at: iso(33), address: "J1", lat: null, lng: null, ...over,
  };
}

describe("SLAOrderCard", () => {
  beforeEach(() => vi.useFakeTimers({ now: NOW }));
  afterEach(() => vi.useRealTimers());

  it("shows order id, customer, and countdown", () => {
    render(<SLAOrderCard order={order()} />);
    expect(screen.getByText(/#47/)).toBeInTheDocument();
    expect(screen.getByText("Ali")).toBeInTheDocument();
    expect(screen.getByTestId("countdown")).toBeInTheDocument();
  });

  it("applies critical lane styling under 10 min remaining", () => {
    render(<SLAOrderCard order={order({ sla_started_at: iso(31) })} />);
    expect(screen.getByTestId("sla-card").className).toContain("critical");
  });

  it("applies breach styling past 40 min", () => {
    render(<SLAOrderCard order={order({ sla_started_at: iso(45) })} />);
    expect(screen.getByTestId("sla-card").className).toContain("breach");
  });
});
```

- [ ] **Step 2: Write `frontend/src/components/SLAOrderCard.tsx`** + `SLAOrderCard.module.css`

```tsx
import { CountdownTimer } from "./CountdownTimer";
import { StatusPill } from "./StatusPill";
import { slaTier } from "../lib/sla";
import type { OrderOut } from "../lib/types";
import s from "./SLAOrderCard.module.css";

export function SLAOrderCard({ order, onClick }: { order: OrderOut; onClick?: () => void }) {
  const tier = slaTier(order.sla_started_at);
  const itemsSummary = order.items
    .map((i) => `${i.qty}× ${i.name}`)
    .join(", ");
  return (
    <div
      data-testid="sla-card"
      className={`${s.card} ${s[tier]}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <div className={s.top}>
        <span className={s.id}>#{order.id}</span>
        <CountdownTimer slaStartedAt={order.sla_started_at} />
      </div>
      <div className={s.cust}>{order.customer_name}</div>
      <div className={s.items}>{itemsSummary}</div>
      <div className={s.foot}>
        <StatusPill status={order.status} />
        {order.rider_name && <span className={s.rider}>{order.rider_name}</span>}
      </div>
    </div>
  );
}
```

```css
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  cursor: pointer;
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.id {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 13px;
  color: var(--text-secondary);
}
.cust {
  font-weight: 600;
  font-size: 13px;
}
.items {
  font-size: 12px;
  color: var(--text-secondary);
}
.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 2px;
}
.rider {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent-rider);
}
.warn {
  border-color: var(--sla-warn);
}
.critical {
  border-color: var(--sla-critical);
  border-width: 2px;
  animation: pulse-critical 2s infinite;
}
.breach {
  border-color: var(--sla-breach);
  border-width: 2px;
  background: rgba(255, 29, 55, 0.22);
  animation: pulse-critical 1s infinite;
}
```

- [ ] **Step 3: Write the failing LiveOrderRow test** — `frontend/src/components/LiveOrderRow.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LiveOrderRow } from "./LiveOrderRow";
import type { OrderOut } from "../lib/types";

const o: OrderOut = {
  id: 48, status: "assigned", customer_name: "Omar", customer_phone: "+9715",
  items: [{ dish_number: 201, name: "Karahi", qty: 1, price_aed: "35.00" }],
  total_aed: "40.00", rider_id: 3, rider_name: "Bilal",
  sla_started_at: "2026-06-06T09:33:00Z", created_at: "2026-06-06T09:32:00Z",
  address: null, lat: null, lng: null,
};

describe("LiveOrderRow", () => {
  it("renders order number, customer, status, rider", () => {
    render(<LiveOrderRow order={o} onOpen={() => {}} />);
    expect(screen.getByText(/#48/)).toBeInTheDocument();
    expect(screen.getByText("Omar")).toBeInTheDocument();
    expect(screen.getByText("Assigned")).toBeInTheDocument();
    expect(screen.getByText("Bilal")).toBeInTheDocument();
  });

  it("calls onOpen when clicked", async () => {
    const onOpen = vi.fn();
    render(<LiveOrderRow order={o} onOpen={onOpen} />);
    await userEvent.click(screen.getByText(/#48/));
    expect(onOpen).toHaveBeenCalledWith(48);
  });
});
```

- [ ] **Step 4: Write `frontend/src/components/LiveOrderRow.tsx`** + `LiveOrderRow.module.css`

```tsx
import { CountdownTimer } from "./CountdownTimer";
import { StatusPill } from "./StatusPill";
import type { OrderOut } from "../lib/types";
import s from "./LiveOrderRow.module.css";

export function LiveOrderRow({
  order,
  onOpen,
  isNew = false,
}: {
  order: OrderOut;
  onOpen: (id: number) => void;
  isNew?: boolean;
}) {
  const items = order.items.map((i) => `${i.qty}× ${i.name}`).join(", ");
  return (
    <div
      className={`${s.row} ${isNew ? s.new : ""}`}
      onClick={() => onOpen(order.id)}
      role="button"
      tabIndex={0}
    >
      <span className={s.id}>#{order.id}</span>
      <span className={s.cust}>{order.customer_name}</span>
      <span className={s.items}>{items}</span>
      <StatusPill status={order.status} />
      <span className={s.rider}>{order.rider_name ?? "—"}</span>
      <span className={s.timer}>
        <CountdownTimer slaStartedAt={order.sla_started_at} />
      </span>
    </div>
  );
}
```

```css
.row {
  display: grid;
  grid-template-columns: 56px 120px 1fr 110px 90px 90px;
  align-items: center;
  gap: 12px;
  height: 44px;
  padding: 0 12px;
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
}
.row:hover {
  background: var(--bg-surface-raised);
}
.new {
  animation: slide-in-right 180ms ease-out;
  background: var(--sla-safe-dim);
}
.id {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--text-secondary);
}
.cust {
  font-weight: 600;
}
.items {
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rider {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent-rider);
}
.timer :global(span) {
  font-size: 14px;
}
```

- [ ] **Step 5: Run tests + type-check**

Run: `cd frontend && npm run test -- SLAOrderCard LiveOrderRow && npm run lint`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/SLAOrderCard.tsx frontend/src/components/SLAOrderCard.module.css frontend/src/components/SLAOrderCard.test.tsx frontend/src/components/LiveOrderRow.tsx frontend/src/components/LiveOrderRow.module.css frontend/src/components/LiveOrderRow.test.tsx
git commit -m "feat: SLAOrderCard (lane + breach styling) and LiveOrderRow (feed)"
```

---

### Task 9: Live Ops screen — KPI strip, SLA board (two lanes), live order feed

**Files:** Replace `frontend/src/screens/LiveOpsScreen.tsx` (+css). Test: `frontend/src/screens/LiveOpsScreen.test.tsx`.

**Composition (brief Screen 1):** KPI strip (7 tiles, derived from polled orders), a placeholder dispatch-map panel (map integration is out of this phase's scope — render a labeled `--map-bg` panel with "Map — riders & batches (live tracking phase)"), the SLA board (yellow lane = 30–35 min elapsed, red lane = 35–40 min), and the live order feed at the bottom with a status-filter pill row. Polls `fetchOrders` every 4 s via `usePoll`. WS-down banner is driven by `usePoll` error state lifted to AppShell — for this screen, surface a local `SectionBanner` on error.

- [ ] **Step 1: Write the failing screen test** — `frontend/src/screens/LiveOpsScreen.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveOpsScreen } from "./LiveOpsScreen";

const NOW = Date.parse("2026-06-06T10:00:00Z");

describe("LiveOpsScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date", "setInterval", "clearInterval"] });
    // 404 → ordersApi fixture fallback (orders 47/48/49)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.useRealTimers());

  it("renders KPI strip and the live feed from fixtures", async () => {
    render(
      <MemoryRouter>
        <LiveOpsScreen />
      </MemoryRouter>,
    );
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Orders Today")).toBeInTheDocument());
    // fixture order 47 customer in feed
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
  });

  it("routes order 47 (32 min elapsed) into the yellow SLA lane", async () => {
    render(
      <MemoryRouter>
        <LiveOpsScreen />
      </MemoryRouter>,
    );
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      const yellow = screen.getByTestId("sla-lane-yellow");
      expect(yellow.textContent).toContain("#47");
    });
  });
});
```

- [ ] **Step 2: Write `frontend/src/screens/LiveOpsScreen.tsx`** + `LiveOpsScreen.module.css`

```tsx
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { KPITile } from "../components/KPITile";
import { LiveOrderRow } from "../components/LiveOrderRow";
import { SectionBanner } from "../components/SectionBanner";
import { SLAOrderCard } from "../components/SLAOrderCard";
import { fetchOrders } from "../lib/ordersApi";
import { remainingMs } from "../lib/sla";
import type { OrderOut } from "../lib/types";
import { usePoll } from "../lib/usePoll";
import s from "./LiveOpsScreen.module.css";

const ACTIVE: OrderOut["status"][] = [
  "confirmed", "preparing", "ready", "assigned", "picked_up", "arriving",
];

export function LiveOpsScreen() {
  const { data, error } = usePoll<OrderOut[]>(fetchOrders, 4000);
  const orders = data ?? [];
  const nav = useNavigate();
  const [filter, setFilter] = useState<OrderOut["status"] | "all">("all");

  const kpis = useMemo(() => {
    const delivered = orders.filter((o) => o.status === "delivered");
    const revenue = orders.reduce((sum, o) => sum + Number(o.total_aed), 0);
    const aov = orders.length ? revenue / orders.length : 0;
    return {
      count: orders.length,
      revenue: `AED ${revenue.toFixed(0)}`,
      aov: `AED ${aov.toFixed(0)}`,
      delivered: delivered.length,
    };
  }, [orders]);

  const active = orders.filter((o) => ACTIVE.includes(o.status));
  const yellow = active.filter((o) => {
    const rem = remainingMs(o.sla_started_at);
    return rem <= 10 * 60_000 && rem > 5 * 60_000;
  });
  const red = active.filter((o) => remainingMs(o.sla_started_at) <= 5 * 60_000);

  const feed = filter === "all" ? orders : orders.filter((o) => o.status === filter);

  return (
    <div className={s.screen}>
      {error && <SectionBanner tone="warning">Live updates paused — reconnecting.</SectionBanner>}

      <div className={s.kpiStrip}>
        <KPITile label="Orders Today" value={String(kpis.count)} />
        <KPITile label="Revenue Today" value={kpis.revenue} />
        <KPITile label="AOV" value={kpis.aov} />
        <KPITile label="Avg Delivery Time" value="—" />
        <KPITile label="SLA %" value="—" />
        <KPITile label="Late Count" value="0" />
        <KPITile label="Coupons Issued" value="0" />
      </div>

      <div className={s.midRow}>
        <div className={s.mapPanel}>
          <span className="label-upper">Dispatch Map</span>
          <div className={s.mapBody}>Map — riders &amp; batches (live tracking phase)</div>
        </div>

        <div className={s.slaBoard}>
          <span className="label-upper">SLA Board</span>
          <div className={s.lane}>
            <span className={s.laneLabel} style={{ color: "var(--sla-warn)" }}>Yellow Lane</span>
            <div data-testid="sla-lane-yellow" className={s.laneCards}>
              {yellow.length === 0 ? (
                <span className={s.clear}>All clear</span>
              ) : (
                yellow.map((o) => <SLAOrderCard key={o.id} order={o} onClick={() => nav(`/orders?id=${o.id}`)} />)
              )}
            </div>
          </div>
          <div className={s.lane}>
            <span className={s.laneLabel} style={{ color: "var(--sla-critical)" }}>Red Lane</span>
            <div data-testid="sla-lane-red" className={s.laneCards}>
              {red.length === 0 ? (
                <span className={s.clear}>All clear</span>
              ) : (
                red.map((o) => <SLAOrderCard key={o.id} order={o} onClick={() => nav(`/orders?id=${o.id}`)} />)
              )}
            </div>
          </div>
        </div>
      </div>

      <div className={s.feed}>
        <div className={s.feedHead}>
          <span className="label-upper">Live Order Feed</span>
          <div className={s.filters}>
            {(["all", ...ACTIVE] as const).map((st) => (
              <button
                key={st}
                className={`${s.filterPill} ${filter === st ? s.filterActive : ""}`}
                onClick={() => setFilter(st)}
              >
                {st}
              </button>
            ))}
          </div>
        </div>
        {feed.length === 0 ? (
          <div className={s.empty}>No orders yet today.</div>
        ) : (
          feed.map((o) => <LiveOrderRow key={o.id} order={o} onOpen={(id) => nav(`/orders?id=${id}`)} />)
        )}
      </div>
    </div>
  );
}
```

```css
.screen {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.kpiStrip {
  display: flex;
  gap: 12px;
  overflow-x: auto;
}
.midRow {
  display: grid;
  grid-template-columns: 1fr 380px;
  gap: 16px;
}
.mapPanel {
  background: var(--map-bg);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  min-height: 420px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mapBody {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 12px;
}
.slaBoard {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.lane {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.laneLabel {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.laneCards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.clear {
  color: var(--text-muted);
  font-size: 12px;
}
.feed {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 16px;
}
.feedHead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.filters {
  display: flex;
  gap: 6px;
}
.filterPill {
  font-size: 11px;
  text-transform: capitalize;
  background: var(--bg-surface-inset);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 3px 10px;
  color: var(--text-secondary);
  cursor: pointer;
}
.filterActive {
  border-color: var(--accent-primary);
  color: var(--accent-primary);
}
.empty {
  color: var(--text-muted);
  font-size: 13px;
  padding: 20px 0;
}
```

- [ ] **Step 3: Run test + type-check**

Run: `cd frontend && npm run test -- LiveOpsScreen && npm run lint`
Expected: PASS. (Yellow-lane test asserts order 47 lands in the 5–10 min remaining bucket: at NOW 10:00, sla_started 09:28 = 32 min elapsed = 8 min remaining → yellow.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/screens/LiveOpsScreen.tsx frontend/src/screens/LiveOpsScreen.module.css frontend/src/screens/LiveOpsScreen.test.tsx
git commit -m "feat: Live Ops screen — KPI strip, SLA board lanes, live order feed with filters"
```

---

### Task 10: CompactTable, Orders screen, OrderDetailDrawer

**Files:** Create `frontend/src/components/CompactTable.tsx` (+css), `frontend/src/screens/OrderDetailDrawer.tsx` (+css). Replace `frontend/src/screens/OrdersScreen.tsx` (+css). Tests: `frontend/src/components/CompactTable.test.tsx`, `frontend/src/screens/OrdersScreen.test.tsx`.

- [ ] **Step 1: Write the failing CompactTable test** — `frontend/src/components/CompactTable.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CompactTable } from "./CompactTable";

interface Row { id: number; name: string; }
const cols = [
  { key: "id", header: "#", render: (r: Row) => `#${r.id}` },
  { key: "name", header: "Name", render: (r: Row) => r.name },
];

describe("CompactTable", () => {
  it("renders headers and rows", () => {
    render(<CompactTable<Row> columns={cols} rows={[{ id: 1, name: "Ali" }]} rowKey={(r) => r.id} />);
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Ali")).toBeInTheDocument();
  });

  it("renders empty state when no rows", () => {
    render(<CompactTable<Row> columns={cols} rows={[]} rowKey={(r) => r.id} emptyText="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Write `frontend/src/components/CompactTable.tsx`** + `CompactTable.module.css`

```tsx
import type { ReactNode } from "react";
import s from "./CompactTable.module.css";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
}

export function CompactTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  emptyText = "No rows",
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  emptyText?: string;
}) {
  if (rows.length === 0) {
    return <div className={s.empty}>{emptyText}</div>;
  }
  return (
    <table className={s.table}>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} className="label-upper">
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)} onClick={() => onRowClick?.(row)} className={onRowClick ? s.clickable : ""}>
            {columns.map((c) => (
              <td key={c.key}>{c.render(row)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

```css
.table {
  width: 100%;
  border-collapse: collapse;
}
.table th {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-default);
}
.table td {
  padding: 0 12px;
  height: 44px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 13px;
}
.clickable {
  cursor: pointer;
}
.clickable:hover {
  background: var(--bg-surface-raised);
}
.empty {
  color: var(--text-muted);
  font-size: 13px;
  padding: 24px 12px;
}
```

- [ ] **Step 3: Write `frontend/src/screens/OrderDetailDrawer.tsx`** + `OrderDetailDrawer.module.css`

```tsx
import { useEffect, useState } from "react";
import { SideDrawer } from "../components/SideDrawer";
import { Spinner } from "../components/Spinner";
import { StatusPill } from "../components/StatusPill";
import { CountdownTimer } from "../components/CountdownTimer";
import { fetchOrder } from "../lib/ordersApi";
import type { OrderOut } from "../lib/types";
import s from "./OrderDetailDrawer.module.css";

export function OrderDetailDrawer({ orderId, onClose }: { orderId: number | null; onClose: () => void }) {
  const [order, setOrder] = useState<OrderOut | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (orderId === null) {
      setOrder(null);
      return;
    }
    setLoading(true);
    fetchOrder(orderId)
      .then(setOrder)
      .finally(() => setLoading(false));
  }, [orderId]);

  return (
    <SideDrawer open={orderId !== null} title={order ? `Order #${order.id}` : "Order"} onClose={onClose}>
      {loading || !order ? (
        <Spinner />
      ) : (
        <div className={s.detail}>
          <div className={s.head}>
            <StatusPill status={order.status} />
            <CountdownTimer slaStartedAt={order.sla_started_at} />
          </div>
          <Field label="Customer" value={`${order.customer_name} · ${order.customer_phone}`} />
          <Field label="Address" value={order.address ?? "—"} />
          <Field label="Rider" value={order.rider_name ?? "Unassigned"} />
          <div className={s.items}>
            <span className="label-upper">Items</span>
            {order.items.map((it, i) => (
              <div key={i} className={s.item}>
                <span>{it.qty}× {it.name}</span>
                <span className={s.price}>AED {it.price_aed}</span>
              </div>
            ))}
          </div>
          <Field label="Total" value={`AED ${order.total_aed}`} />
        </div>
      )}
    </SideDrawer>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.field}>
      <span className="label-upper">{label}</span>
      <span className={s.val}>{value}</span>
    </div>
  );
}
```

```css
.detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.val {
  font-size: 13px;
}
.items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.item {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.price {
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
```

- [ ] **Step 4: Write the failing OrdersScreen test** — `frontend/src/screens/OrdersScreen.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OrdersScreen } from "./OrdersScreen";

describe("OrdersScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists orders from fixtures", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
    expect(screen.getByText("Omar Farouq")).toBeInTheDocument();
  });

  it("opens detail drawer on row click", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.click(screen.getByText("Ali Hassan"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  });

  it("filters to empty with a no-match message", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.type(screen.getByPlaceholderText(/search/i), "#9999");
    await waitFor(() => expect(screen.getByText(/no orders match/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 5: Write `frontend/src/screens/OrdersScreen.tsx`** + `OrdersScreen.module.css`

```tsx
import { useEffect, useMemo, useState } from "react";
import { CompactTable, type Column } from "../components/CompactTable";
import { StatusPill } from "../components/StatusPill";
import { fetchOrders } from "../lib/ordersApi";
import type { OrderOut } from "../lib/types";
import { OrderDetailDrawer } from "./OrderDetailDrawer";
import s from "./OrdersScreen.module.css";

export function OrdersScreen() {
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    fetchOrders().then(setOrders);
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().replace(/^#/, "").toLowerCase();
    if (!q) return orders;
    return orders.filter(
      (o) =>
        String(o.id).includes(q) ||
        o.customer_name.toLowerCase().includes(q) ||
        o.customer_phone.includes(q),
    );
  }, [orders, search]);

  const columns: Column<OrderOut>[] = [
    { key: "id", header: "#", render: (o) => <span className={s.mono}>#{o.id}</span> },
    { key: "cust", header: "Customer", render: (o) => o.customer_name },
    { key: "items", header: "Items", render: (o) => o.items.map((i) => `${i.qty}× ${i.name}`).join(", ") },
    { key: "total", header: "Total", render: (o) => <span className={s.mono}>AED {o.total_aed}</span> },
    { key: "rider", header: "Rider", render: (o) => o.rider_name ?? "—" },
    { key: "status", header: "Status", render: (o) => <StatusPill status={o.status} /> },
  ];

  return (
    <div className={s.screen}>
      <div className={s.filterBar}>
        <input
          className={s.search}
          placeholder="Search #ID / name / phone"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <CompactTable<OrderOut>
        columns={columns}
        rows={filtered}
        rowKey={(o) => o.id}
        onRowClick={(o) => setOpenId(o.id)}
        emptyText="No orders match these filters"
      />
      <OrderDetailDrawer orderId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}
```

```css
.screen {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.filterBar {
  display: flex;
  gap: 12px;
}
.search {
  flex: 1;
  max-width: 320px;
  background: var(--bg-surface-inset);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  padding: 8px 12px;
  color: var(--text-primary);
}
.search:focus {
  outline: none;
  border-color: var(--accent-primary);
}
.mono {
  font-family: var(--font-mono);
}
```

- [ ] **Step 6: Run tests + type-check**

Run: `cd frontend && npm run test -- CompactTable OrdersScreen && npm run lint`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/CompactTable.tsx frontend/src/components/CompactTable.module.css frontend/src/components/CompactTable.test.tsx frontend/src/screens/OrderDetailDrawer.tsx frontend/src/screens/OrderDetailDrawer.module.css frontend/src/screens/OrdersScreen.tsx frontend/src/screens/OrdersScreen.module.css frontend/src/screens/OrdersScreen.test.tsx
git commit -m "feat: CompactTable, Orders screen with search, order detail drawer"
```

---

### Task 11: Menu Manager — menuApi, DishCard, DiffPanel, screen (upload → diff → activate, availability toggles)

**Files:** Create `frontend/src/lib/menuApi.ts`, `frontend/src/components/DishCard.tsx` (+css), `frontend/src/components/DiffPanel.tsx` (+css). Replace `frontend/src/screens/MenuManagerScreen.tsx` (+css). Tests: `frontend/src/components/DishCard.test.tsx`, `frontend/src/components/DiffPanel.test.tsx`, `frontend/src/screens/MenuManagerScreen.test.tsx`.

**Menu flow (brief Screen 3):** Normal mode = dish grid (3 cols) with 1-click availability toggle (PATCH `/api/v1/dishes/{id}/availability`). Upload new menu → POST `/api/v1/menus` (multipart) returns `MenuWithDiffOut` with `diff_vs_active` → Confirmation Mode shows DiffPanel (current vs incoming, price-change / new / removed counts; extraction errors = dishes missing number or price get `--sla-warn` border, block confirm) → Confirm activates via POST `/api/v1/menus/{id}/activate`.

- [ ] **Step 1: Write `frontend/src/lib/menuApi.ts`**

```ts
import { apiClient } from "./apiClient";
import type { DishOut, MenuOut, MenuWithDiffOut } from "./types";

export async function getMenu(menuId: number): Promise<MenuOut> {
  return apiClient.get<MenuOut>(`/api/v1/menus/${menuId}`);
}

export async function uploadMenu(files: File[]): Promise<MenuWithDiffOut> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return apiClient.postForm<MenuWithDiffOut>("/api/v1/menus", form);
}

export async function activateMenu(menuId: number): Promise<MenuOut> {
  return apiClient.post<MenuOut>(`/api/v1/menus/${menuId}/activate`);
}

export async function setAvailability(dishId: number, isAvailable: boolean): Promise<DishOut> {
  return apiClient.patch<DishOut>(`/api/v1/dishes/${dishId}/availability`, {
    is_available: isAvailable,
  });
}
```

- [ ] **Step 2: Write the failing DishCard test** — `frontend/src/components/DishCard.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DishCard } from "./DishCard";
import type { DishOut } from "../lib/types";

const dish: DishOut = {
  id: 1, dish_number: 110, name: "Chicken Biryani", price_aed: "22.00",
  category: "Rice", description: null, is_available: true,
};

describe("DishCard", () => {
  it("renders number, name, price", () => {
    render(<DishCard dish={dish} onToggle={() => {}} />);
    expect(screen.getByText("#110")).toBeInTheDocument();
    expect(screen.getByText("Chicken Biryani")).toBeInTheDocument();
    expect(screen.getByText("AED 22.00")).toBeInTheDocument();
  });

  it("calls onToggle with negated availability", async () => {
    const onToggle = vi.fn();
    render(<DishCard dish={dish} onToggle={onToggle} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onToggle).toHaveBeenCalledWith(1, false);
  });

  it("flags extraction error when number or price missing", () => {
    render(<DishCard dish={{ ...dish, dish_number: null }} onToggle={() => {}} />);
    expect(screen.getByTestId("dish-card").className).toContain("error");
  });
});
```

- [ ] **Step 3: Write `frontend/src/components/DishCard.tsx`** + `DishCard.module.css`

```tsx
import type { DishOut } from "../lib/types";
import s from "./DishCard.module.css";

export function DishCard({
  dish,
  onToggle,
}: {
  dish: DishOut;
  onToggle: (id: number, next: boolean) => void;
}) {
  const hasError = dish.dish_number === null || dish.price_aed === null;
  return (
    <div data-testid="dish-card" className={`${s.card} ${hasError ? s.error : ""}`}>
      <div className={s.top}>
        <span className={s.num}>#{dish.dish_number ?? "??"}</span>
        <button
          role="switch"
          aria-checked={dish.is_available}
          className={`${s.toggle} ${dish.is_available ? s.on : s.off}`}
          onClick={() => onToggle(dish.id, !dish.is_available)}
        >
          {dish.is_available ? "Available" : "Unavailable"}
        </button>
      </div>
      <div className={s.name}>{dish.name}</div>
      <div className={s.price}>AED {dish.price_aed ?? "—"}</div>
    </div>
  );
}
```

```css
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.error {
  border-color: var(--sla-warn);
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.num {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--text-secondary);
}
.name {
  font-weight: 600;
  font-size: 13px;
}
.price {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}
.toggle {
  font-size: 11px;
  font-weight: 600;
  border-radius: 12px;
  padding: 2px 10px;
  cursor: pointer;
  border: 1px solid;
}
.on {
  color: var(--sla-safe);
  border-color: var(--sla-safe);
  background: var(--sla-safe-dim);
}
.off {
  color: var(--text-muted);
  border-color: var(--border-default);
  background: transparent;
}
```

- [ ] **Step 4: Write the failing DiffPanel test** — `frontend/src/components/DiffPanel.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DiffPanel } from "./DiffPanel";
import type { DiffOut } from "../lib/types";

const diff: DiffOut = {
  price_changes: [{ dish_number: 110, name: "Biryani", old_price: "22.00", new_price: "25.00" }],
  added: [{ dish_number: 310, name: "Falooda", price_aed: "12.00" }],
  removed: [{ dish_number: 201, name: "Karahi" }],
  conflicts: [{ dish_number: null, name: "Mystery", reason: "missing number" }],
};

describe("DiffPanel", () => {
  it("renders change counts", () => {
    render(<DiffPanel diff={diff} />);
    expect(screen.getByText(/Changed: 1/)).toBeInTheDocument();
    expect(screen.getByText(/New: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Removed: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Errors: 1/)).toBeInTheDocument();
  });

  it("renders a price-change row with old and new values", () => {
    render(<DiffPanel diff={diff} />);
    expect(screen.getByText(/22\.00/)).toBeInTheDocument();
    expect(screen.getByText(/25\.00/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Write `frontend/src/components/DiffPanel.tsx`** + `DiffPanel.module.css`

```tsx
import type { DiffOut } from "../lib/types";
import s from "./DiffPanel.module.css";

export function DiffPanel({ diff }: { diff: DiffOut }) {
  return (
    <div className={s.panel}>
      <div className={s.counts}>
        <span style={{ color: "var(--sla-warn)" }}>Changed: {diff.price_changes.length}</span>
        <span style={{ color: "var(--sla-safe)" }}>New: {diff.added.length}</span>
        <span style={{ color: "var(--sla-critical)" }}>Removed: {diff.removed.length}</span>
        <span style={{ color: "var(--sla-warn)" }}>Errors: {diff.conflicts.length}</span>
      </div>

      {diff.price_changes.map((c, i) => (
        <div key={`p${i}`} className={s.row}>
          <span className={s.num}>#{String(c.dish_number)}</span>
          <span>{String(c.name)}</span>
          <span className={s.old}>AED {String(c.old_price)}</span>
          <span className={s.arrow}>→</span>
          <span className={s.new}>AED {String(c.new_price)}</span>
        </div>
      ))}

      {diff.conflicts.map((c, i) => (
        <div key={`c${i}`} className={`${s.row} ${s.conflict}`}>
          <span className={s.num}>#{String(c.dish_number ?? "??")}</span>
          <span>{String(c.name)}</span>
          <span className={s.reason}>{String(c.reason ?? "extraction error")}</span>
        </div>
      ))}
    </div>
  );
}
```

```css
.panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.counts {
  display: flex;
  gap: 16px;
  font-family: var(--font-mono);
  font-size: 13px;
  margin-bottom: 8px;
}
.row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  font-size: 13px;
}
.conflict {
  border-color: var(--sla-warn);
}
.num {
  font-family: var(--font-mono);
  color: var(--text-secondary);
}
.old {
  font-family: var(--font-mono);
  color: var(--text-muted);
  text-decoration: line-through;
}
.new {
  font-family: var(--font-mono);
  color: var(--sla-warn);
}
.arrow {
  color: var(--text-muted);
}
.reason {
  color: var(--sla-warn);
  font-size: 12px;
}
```

- [ ] **Step 6: Write the failing MenuManagerScreen test** — `frontend/src/screens/MenuManagerScreen.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MenuManagerScreen } from "./MenuManagerScreen";

const activeMenu = {
  id: 5, version: 2, status: "active",
  dishes: [
    { id: 1, dish_number: 110, name: "Chicken Biryani", price_aed: "22.00", category: "Rice", description: null, is_available: true },
    { id: 2, dish_number: 201, name: "Mutton Karahi", price_aed: "35.00", category: "Curries", description: null, is_available: false },
  ],
};

describe("MenuManagerScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/menus/5") && (!init || init.method === "GET")) {
        return Promise.resolve(new Response(JSON.stringify(activeMenu), { status: 200 }));
      }
      if (typeof url === "string" && url.includes("/availability")) {
        return Promise.resolve(new Response(JSON.stringify({ ...activeMenu.dishes[0], is_available: false }), { status: 200 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    }));
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the active dish grid", async () => {
    render(<MenuManagerScreen initialMenuId={5} />);
    await waitFor(() => expect(screen.getByText("Chicken Biryani")).toBeInTheDocument());
    expect(screen.getByText("Mutton Karahi")).toBeInTheDocument();
  });

  it("toggles availability via API on switch click", async () => {
    const fetchSpy = vi.mocked(fetch);
    render(<MenuManagerScreen initialMenuId={5} />);
    await waitFor(() => screen.getByText("Chicken Biryani"));
    const switches = screen.getAllByRole("switch");
    await userEvent.click(switches[0]);
    await waitFor(() =>
      expect(fetchSpy.mock.calls.some(([u]) => String(u).includes("/availability"))).toBe(true),
    );
  });
});
```

- [ ] **Step 7: Write `frontend/src/screens/MenuManagerScreen.tsx`** + `MenuManagerScreen.module.css`

```tsx
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/Button";
import { DiffPanel } from "../components/DiffPanel";
import { DishCard } from "../components/DishCard";
import { SectionBanner } from "../components/SectionBanner";
import { activateMenu, getMenu, setAvailability, uploadMenu } from "../lib/menuApi";
import type { DishOut, MenuWithDiffOut } from "../lib/types";
import s from "./MenuManagerScreen.module.css";

export function MenuManagerScreen({ initialMenuId }: { initialMenuId?: number }) {
  const [dishes, setDishes] = useState<DishOut[]>([]);
  const [pending, setPending] = useState<MenuWithDiffOut | null>(null);
  const [activeMenuId, setActiveMenuId] = useState<number | null>(initialMenuId ?? null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (activeMenuId !== null && pending === null) {
      getMenu(activeMenuId).then((m) => setDishes(m.dishes)).catch(() => {});
    }
  }, [activeMenuId, pending]);

  async function onToggle(id: number, next: boolean) {
    setDishes((ds) => ds.map((d) => (d.id === id ? { ...d, is_available: next } : d)));
    try {
      await setAvailability(id, next);
    } catch {
      setDishes((ds) => ds.map((d) => (d.id === id ? { ...d, is_available: !next } : d)));
      setError("Failed to update availability.");
    }
  }

  async function onUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    try {
      const result = await uploadMenu(Array.from(files));
      setPending(result);
    } catch {
      setError("Menu upload failed.");
    }
  }

  async function onConfirm() {
    if (!pending) return;
    await activateMenu(pending.id);
    setActiveMenuId(pending.id);
    setPending(null);
  }

  const hasErrors = (pending?.diff_vs_active?.conflicts.length ?? 0) > 0;

  if (pending) {
    return (
      <div className={s.screen}>
        <SectionBanner tone="info">New menu parsed — review and confirm before activating.</SectionBanner>
        {pending.diff_vs_active ? <DiffPanel diff={pending.diff_vs_active} /> : <p>No diff.</p>}
        <div className={s.actions}>
          <Button onClick={onConfirm} disabled={hasErrors}>Confirm &amp; Activate</Button>
          <Button variant="ghost" onClick={() => setPending(null)}>Discard</Button>
          {hasErrors && <span className={s.blocked}>Resolve extraction errors before activating.</span>}
        </div>
      </div>
    );
  }

  return (
    <div className={s.screen}>
      {error && <SectionBanner tone="error" onDismiss={() => setError(null)}>{error}</SectionBanner>}
      <div className={s.bar}>
        <span className="label-upper">Menu</span>
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(e) => onUpload(e.target.files)}
          data-testid="menu-upload"
        />
        <Button onClick={() => fileRef.current?.click()}>Upload new menu</Button>
      </div>
      {dishes.length === 0 ? (
        <div className={s.empty}>Upload your first menu to get started.</div>
      ) : (
        <div className={s.grid}>
          {dishes.map((d) => (
            <DishCard key={d.id} dish={d} onToggle={onToggle} />
          ))}
        </div>
      )}
    </div>
  );
}
```

```css
.screen {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.blocked {
  color: var(--sla-warn);
  font-size: 12px;
}
.empty {
  color: var(--text-muted);
  font-size: 13px;
  padding: 24px 0;
}
```

NOTE: `App.tsx` renders `<MenuManagerScreen />` without props. In a real session the active menu id comes from `GET /api/v1/me` settings or a menus-list endpoint; for now `initialMenuId` is optional and the screen shows the empty state until an upload occurs. Wire the active menu id when the backend exposes it.

- [ ] **Step 8: Run tests + type-check**

Run: `cd frontend && npm run test -- DishCard DiffPanel MenuManagerScreen && npm run lint`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/menuApi.ts frontend/src/components/DishCard.tsx frontend/src/components/DishCard.module.css frontend/src/components/DishCard.test.tsx frontend/src/components/DiffPanel.tsx frontend/src/components/DiffPanel.module.css frontend/src/components/DiffPanel.test.tsx frontend/src/screens/MenuManagerScreen.tsx frontend/src/screens/MenuManagerScreen.module.css frontend/src/screens/MenuManagerScreen.test.tsx
git commit -m "feat: Menu Manager — dish grid, availability toggle, upload→diff→activate flow"
```

---

### Task 12: Riders board — RiderCard, ridersApi, screen

**Files:** Create `frontend/src/lib/ridersApi.ts`, `frontend/src/components/RiderCard.tsx` (+css). Replace `frontend/src/screens/RidersScreen.tsx` (+css). Tests: `frontend/src/components/RiderCard.test.tsx`, `frontend/src/screens/RidersScreen.test.tsx`.

**Riders (brief Screen 4):** grid of rider cards (status pill, current batch placeholder, on-time stats placeholder, View-on-map / shift / deactivate actions). Live location is a placeholder this phase — show a "Location: live tracking phase" line; the stale-location border hook is present (driven by a future `last_location_at` field, defaulted off). Status changes PATCH `/api/v1/riders/{id}`.

- [ ] **Step 1: Write `frontend/src/lib/ridersApi.ts`**

```ts
import { apiClient } from "./apiClient";
import type { RiderOut, RiderStatus } from "./types";

export async function fetchRiders(): Promise<RiderOut[]> {
  return apiClient.get<RiderOut[]>("/api/v1/riders");
}

export async function setRiderStatus(id: number, status: RiderStatus): Promise<RiderOut> {
  return apiClient.patch<RiderOut>(`/api/v1/riders/${id}`, { status });
}
```

- [ ] **Step 2: Write the failing RiderCard test** — `frontend/src/components/RiderCard.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RiderCard } from "./RiderCard";
import type { RiderOut } from "../lib/types";

const rider: RiderOut = { id: 3, name: "Ali Hassan", phone: "+9715", status: "on_delivery" };

describe("RiderCard", () => {
  it("renders name and status label", () => {
    render(<RiderCard rider={rider} onStatusChange={() => {}} />);
    expect(screen.getByText("Ali Hassan")).toBeInTheDocument();
    expect(screen.getByText(/On Delivery/i)).toBeInTheDocument();
  });

  it("deactivate action triggers status change", async () => {
    const onStatusChange = vi.fn();
    render(<RiderCard rider={rider} onStatusChange={onStatusChange} />);
    await userEvent.click(screen.getByRole("button", { name: /deactivate/i }));
    expect(onStatusChange).toHaveBeenCalledWith(3, "deactivated");
  });

  it("shows stale-location border when stale", () => {
    render(<RiderCard rider={rider} onStatusChange={() => {}} stale />);
    expect(screen.getByTestId("rider-card").className).toContain("stale");
  });
});
```

- [ ] **Step 3: Write `frontend/src/components/RiderCard.tsx`** + `RiderCard.module.css`

```tsx
import { Button } from "./Button";
import type { RiderOut, RiderStatus } from "../lib/types";
import s from "./RiderCard.module.css";

const STATUS_LABEL: Record<RiderStatus, string> = {
  available: "Available",
  on_delivery: "On Delivery",
  off_shift: "Off Shift",
  deactivated: "Deactivated",
};

const STATUS_COLOR: Record<RiderStatus, string> = {
  available: "var(--sla-safe)",
  on_delivery: "var(--accent-rider)",
  off_shift: "var(--text-muted)",
  deactivated: "var(--sla-critical)",
};

export function RiderCard({
  rider,
  onStatusChange,
  stale = false,
}: {
  rider: RiderOut;
  onStatusChange: (id: number, status: RiderStatus) => void;
  stale?: boolean;
}) {
  const offShift = rider.status === "off_shift";
  return (
    <div data-testid="rider-card" className={`${s.card} ${stale ? s.stale : ""}`}>
      <div className={s.head}>
        <span className={s.name}>{rider.name}</span>
        <span className={s.status} style={{ color: STATUS_COLOR[rider.status] }}>
          ● {STATUS_LABEL[rider.status]}
        </span>
      </div>
      {stale && <span className={s.staleBadge}>Location stale</span>}
      <span className={s.loc}>Location: live tracking phase</span>
      <span className={s.stats}>On-time: — · Avg —</span>
      <div className={s.actions}>
        <Button variant="ghost" onClick={() => onStatusChange(rider.id, offShift ? "available" : "off_shift")}>
          {offShift ? "Start shift" : "End shift"}
        </Button>
        <Button variant="danger" onClick={() => onStatusChange(rider.id, "deactivated")}>
          Deactivate
        </Button>
      </div>
    </div>
  );
}
```

```css
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.stale {
  border-color: var(--sla-warn);
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.name {
  font-weight: 600;
  font-size: 14px;
}
.status {
  font-size: 12px;
  font-weight: 500;
}
.staleBadge {
  align-self: flex-start;
  font-size: 10px;
  color: var(--sla-warn);
  border: 1px solid var(--sla-warn);
  border-radius: 4px;
  padding: 1px 6px;
}
.loc,
.stats {
  font-size: 12px;
  color: var(--text-secondary);
}
.actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
```

- [ ] **Step 4: Write the failing RidersScreen test** — `frontend/src/screens/RidersScreen.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RidersScreen } from "./RidersScreen";

const riders = [
  { id: 3, name: "Ali Hassan", phone: "+9715", status: "on_delivery" },
  { id: 4, name: "Omar Farouq", phone: "+9716", status: "off_shift" },
];

describe("RidersScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(riders), { status: 200 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders rider cards from API", async () => {
    render(<RidersScreen />);
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
    expect(screen.getByText("Omar Farouq")).toBeInTheDocument();
  });

  it("shows empty state when no riders", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response("[]", { status: 200 }));
    render(<RidersScreen />);
    await waitFor(() => expect(screen.getByText(/register your first rider/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 5: Write `frontend/src/screens/RidersScreen.tsx`** + `RidersScreen.module.css`

```tsx
import { useEffect, useState } from "react";
import { RiderCard } from "../components/RiderCard";
import { fetchRiders, setRiderStatus } from "../lib/ridersApi";
import type { RiderOut, RiderStatus } from "../lib/types";
import s from "./RidersScreen.module.css";

export function RidersScreen() {
  const [riders, setRiders] = useState<RiderOut[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetchRiders()
      .then(setRiders)
      .finally(() => setLoaded(true));
  }, []);

  async function onStatusChange(id: number, status: RiderStatus) {
    const updated = await setRiderStatus(id, status);
    setRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  if (loaded && riders.length === 0) {
    return <div className={s.empty}>No riders yet — register your first rider.</div>;
  }

  return (
    <div className={s.grid}>
      {riders.map((r) => (
        <RiderCard key={r.id} rider={r} onStatusChange={onStatusChange} />
      ))}
    </div>
  );
}
```

```css
.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
.empty {
  color: var(--text-muted);
  font-size: 13px;
  padding: 24px 0;
}
```

- [ ] **Step 6: Run tests + type-check**

Run: `cd frontend && npm run test -- RiderCard RidersScreen && npm run lint`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/ridersApi.ts frontend/src/components/RiderCard.tsx frontend/src/components/RiderCard.module.css frontend/src/components/RiderCard.test.tsx frontend/src/screens/RidersScreen.tsx frontend/src/screens/RidersScreen.module.css frontend/src/screens/RidersScreen.test.tsx
git commit -m "feat: Riders board — rider cards, status changes, stale-location hook"
```

---

### Task 13: Conversations — ConversationRow, MessageBubble, conversationsApi (fixture fallback), screen with manual takeover

**Files:** Create `frontend/src/lib/fixtures/conversations.json`, `frontend/src/lib/conversationsApi.ts`, `frontend/src/components/ConversationRow.tsx` (+css), `frontend/src/components/MessageBubble.tsx` (+css). Replace `frontend/src/screens/ConversationsScreen.tsx` (+css). Tests: `frontend/src/components/MessageBubble.test.tsx`, `frontend/src/screens/ConversationsScreen.test.tsx`.

**Conversations (brief Screen 7):** left list (320px) + right viewer. Manual takeover toggle: amber banner "You are controlling this conversation"; uses fixture fallback like ordersApi because the conversations REST endpoints are Phase-dependent.

- [ ] **Step 1: Write `frontend/src/lib/fixtures/conversations.json`**

```json
{
  "conversations": [
    { "id": 1, "phone": "+971501234567", "counterpart": "customer", "manual_takeover": false, "last_message_preview": "I want to order biryani", "unread": true, "updated_at": "2026-06-06T09:58:00Z" },
    { "id": 2, "phone": "+971559876543", "counterpart": "customer", "manual_takeover": false, "last_message_preview": "Delivered, thanks!", "unread": false, "updated_at": "2026-06-06T09:15:00Z" }
  ],
  "messages": {
    "1": [
      { "id": 11, "direction": "inbound", "type": "text", "payload": { "text": "Hi" }, "ts": 1717660800 },
      { "id": 12, "direction": "outbound", "type": "text", "payload": { "text": "Welcome! Here is our menu…" }, "ts": 1717660830 },
      { "id": 13, "direction": "inbound", "type": "text", "payload": { "text": "I want to order biryani" }, "ts": 1717660900 }
    ],
    "2": [
      { "id": 21, "direction": "outbound", "type": "text", "payload": { "text": "Your order is on the way." }, "ts": 1717650000 }
    ]
  }
}
```

- [ ] **Step 2: Write `frontend/src/lib/conversationsApi.ts`**

```ts
import { apiClient, ApiError } from "./apiClient";
import fixtures from "./fixtures/conversations.json";
import type { ConversationOut, MessageOut } from "./types";

type Fix = { conversations: ConversationOut[]; messages: Record<string, MessageOut[]> };
const FIX = fixtures as Fix;

export async function fetchConversations(): Promise<ConversationOut[]> {
  try {
    return await apiClient.get<ConversationOut[]>("/api/v1/conversations");
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
    return FIX.conversations;
  }
}

export async function fetchMessages(conversationId: number): Promise<MessageOut[]> {
  try {
    return await apiClient.get<MessageOut[]>(`/api/v1/conversations/${conversationId}/messages`);
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
    return FIX.messages[String(conversationId)] ?? [];
  }
}

export async function setTakeover(conversationId: number, active: boolean): Promise<void> {
  try {
    await apiClient.post(`/api/v1/conversations/${conversationId}/takeover`, { active });
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
    // fixture mode: no-op
  }
}

export async function sendMessage(conversationId: number, text: string): Promise<void> {
  try {
    await apiClient.post(`/api/v1/conversations/${conversationId}/messages`, { text });
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
  }
}
```

- [ ] **Step 3: Write the failing MessageBubble test** — `frontend/src/components/MessageBubble.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "./MessageBubble";
import type { MessageOut } from "../lib/types";

const inbound: MessageOut = { id: 1, direction: "inbound", type: "text", payload: { text: "Hi" }, ts: 1717660800 };
const outbound: MessageOut = { id: 2, direction: "outbound", type: "text", payload: { text: "Welcome" }, ts: 1717660830 };

describe("MessageBubble", () => {
  it("renders inbound text on the left", () => {
    render(<MessageBubble message={inbound} />);
    expect(screen.getByText("Hi").parentElement?.className).toContain("inbound");
  });
  it("renders outbound text on the right", () => {
    render(<MessageBubble message={outbound} />);
    expect(screen.getByText("Welcome").parentElement?.className).toContain("outbound");
  });
});
```

- [ ] **Step 4: Write `frontend/src/components/MessageBubble.tsx`** + `MessageBubble.module.css`

```tsx
import type { MessageOut } from "../lib/types";
import s from "./MessageBubble.module.css";

export function MessageBubble({ message }: { message: MessageOut }) {
  const text = typeof message.payload.text === "string" ? message.payload.text : JSON.stringify(message.payload);
  return (
    <div className={`${s.row} ${s[message.direction]}`}>
      <div className={s.bubble}>{text}</div>
    </div>
  );
}
```

```css
.row {
  display: flex;
  margin-bottom: 8px;
}
.inbound {
  justify-content: flex-start;
}
.outbound {
  justify-content: flex-end;
}
.bubble {
  max-width: 70%;
  padding: 8px 12px;
  border-radius: var(--radius);
  font-size: 13px;
}
.inbound .bubble {
  background: var(--bg-surface-raised);
  color: var(--text-primary);
}
.outbound .bubble {
  background: var(--accent-primary-dim);
  color: var(--text-primary);
  border: 1px solid var(--accent-primary);
}
```

- [ ] **Step 5: Write `frontend/src/components/ConversationRow.tsx`** + `ConversationRow.module.css`

```tsx
import type { ConversationOut } from "../lib/types";
import s from "./ConversationRow.module.css";

export function ConversationRow({
  conversation,
  selected,
  onClick,
}: {
  conversation: ConversationOut;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <div className={`${s.row} ${selected ? s.selected : ""}`} onClick={onClick} role="button" tabIndex={0}>
      <div className={s.top}>
        {conversation.unread && <span className={s.dot} />}
        <span className={s.phone}>{conversation.phone}</span>
      </div>
      <span className={s.preview}>{conversation.last_message_preview ?? "—"}</span>
    </div>
  );
}
```

```css
.row {
  padding: 12px;
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.row:hover {
  background: var(--bg-surface-raised);
}
.selected {
  background: var(--accent-primary-dim);
}
.top {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--sla-safe);
}
.phone {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
}
.preview {
  font-size: 12px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 6: Write the failing ConversationsScreen test** — `frontend/src/screens/ConversationsScreen.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConversationsScreen } from "./ConversationsScreen";

describe("ConversationsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists conversations from fixtures", async () => {
    render(<ConversationsScreen />);
    await waitFor(() => expect(screen.getByText("+971501234567")).toBeInTheDocument());
  });

  it("opens a thread and shows takeover toggle", async () => {
    render(<ConversationsScreen />);
    await waitFor(() => screen.getByText("+971501234567"));
    await userEvent.click(screen.getByText("+971501234567"));
    await waitFor(() => expect(screen.getByText("I want to order biryani")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /take over/i })).toBeInTheDocument();
  });

  it("activating takeover shows the control banner", async () => {
    render(<ConversationsScreen />);
    await waitFor(() => screen.getByText("+971501234567"));
    await userEvent.click(screen.getByText("+971501234567"));
    await userEvent.click(screen.getByRole("button", { name: /take over/i }));
    await waitFor(() => expect(screen.getByText(/you are controlling this conversation/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 7: Write `frontend/src/screens/ConversationsScreen.tsx`** + `ConversationsScreen.module.css`

```tsx
import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { ConversationRow } from "../components/ConversationRow";
import { MessageBubble } from "../components/MessageBubble";
import { SectionBanner } from "../components/SectionBanner";
import { fetchConversations, fetchMessages, sendMessage, setTakeover } from "../lib/conversationsApi";
import type { ConversationOut, MessageOut } from "../lib/types";
import s from "./ConversationsScreen.module.css";

export function ConversationsScreen() {
  const [convs, setConvs] = useState<ConversationOut[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [takeover, setTakeoverState] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    fetchConversations().then(setConvs);
  }, []);

  useEffect(() => {
    if (activeId === null) return;
    fetchMessages(activeId).then(setMessages);
    const c = convs.find((x) => x.id === activeId);
    setTakeoverState(c?.manual_takeover ?? false);
  }, [activeId, convs]);

  async function toggleTakeover() {
    if (activeId === null) return;
    const next = !takeover;
    setTakeoverState(next);
    await setTakeover(activeId, next);
  }

  async function send() {
    if (activeId === null || !draft.trim()) return;
    await sendMessage(activeId, draft.trim());
    setMessages((m) => [
      ...m,
      { id: Date.now(), direction: "outbound", type: "text", payload: { text: draft.trim() }, ts: Math.floor(Date.now() / 1000) },
    ]);
    setDraft("");
  }

  return (
    <div className={s.layout}>
      <aside className={s.list}>
        {convs.map((c) => (
          <ConversationRow key={c.id} conversation={c} selected={c.id === activeId} onClick={() => setActiveId(c.id)} />
        ))}
        {convs.length === 0 && <div className={s.empty}>Conversations will appear here.</div>}
      </aside>
      <section className={s.viewer}>
        {activeId === null ? (
          <div className={s.empty}>Select a conversation.</div>
        ) : (
          <>
            <div className={s.viewerHead}>
              <Button variant={takeover ? "danger" : "ghost"} onClick={toggleTakeover}>
                {takeover ? "Return to bot" : "Take over"}
              </Button>
            </div>
            {takeover && (
              <SectionBanner tone="warning">You are controlling this conversation.</SectionBanner>
            )}
            <div className={s.thread}>
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </div>
            <div className={s.composer}>
              <input
                className={s.input}
                placeholder="Type message"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={!takeover}
              />
              <Button onClick={send} disabled={!takeover}>Send</Button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
```

```css
.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  height: 100%;
}
.list {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  overflow-y: auto;
}
.viewer {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.viewerHead {
  display: flex;
  justify-content: flex-end;
}
.thread {
  flex: 1;
  overflow-y: auto;
}
.composer {
  display: flex;
  gap: 8px;
}
.input {
  flex: 1;
  background: var(--bg-surface-inset);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  padding: 8px 12px;
  color: var(--text-primary);
}
.input:focus {
  outline: none;
  border-color: var(--accent-primary);
}
.empty {
  color: var(--text-muted);
  font-size: 13px;
  padding: 24px;
}
```

- [ ] **Step 8: Run tests + type-check**

Run: `cd frontend && npm run test -- MessageBubble ConversationsScreen && npm run lint`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/fixtures/conversations.json frontend/src/lib/conversationsApi.ts frontend/src/components/ConversationRow.tsx frontend/src/components/ConversationRow.module.css frontend/src/components/MessageBubble.tsx frontend/src/components/MessageBubble.module.css frontend/src/components/MessageBubble.test.tsx frontend/src/screens/ConversationsScreen.tsx frontend/src/screens/ConversationsScreen.module.css frontend/src/screens/ConversationsScreen.test.tsx
git commit -m "feat: Conversations screen — list, thread viewer, manual takeover, send"
```

---

### Task 14: Settings screen + Analytics placeholder

**Files:** Replace `frontend/src/screens/SettingsScreen.tsx` (+css), `frontend/src/screens/AnalyticsScreen.tsx` (+css). Test: `frontend/src/screens/SettingsScreen.test.tsx`.

**Settings (brief Screen 9):** tabbed General / Fees & Radius / Batching. Editable: delivery fee tiers, max radius (≤10), max orders/batch, max items/order. PATCH `/api/v1/settings`. Loads current values from `GET /api/v1/me` → `settings`. Analytics is an explicit placeholder per phase scope.

- [ ] **Step 1: Write the failing SettingsScreen test** — `frontend/src/screens/SettingsScreen.test.tsx`

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsScreen } from "./SettingsScreen";

const me = {
  id: 1, name: "Test Resto", phone: "+9714", lat: 25.2, lng: 55.2,
  settings: { max_orders_per_batch: 3, max_items_per_order: 20 },
};

describe("SettingsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (String(url).includes("/me")) {
        return Promise.resolve(new Response(JSON.stringify(me), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify(me), { status: 200 }));
    }));
  });
  afterEach(() => vi.restoreAllMocks());

  it("loads current batching settings", async () => {
    render(<SettingsScreen />);
    await waitFor(() => expect((screen.getByLabelText(/orders per batch/i) as HTMLInputElement).value).toBe("3"));
  });

  it("PATCHes settings on save", async () => {
    const spy = vi.mocked(fetch);
    render(<SettingsScreen />);
    await waitFor(() => screen.getByLabelText(/orders per batch/i));
    await userEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() =>
      expect(spy.mock.calls.some(([u, i]) => String(u).includes("/settings") && i?.method === "PATCH")).toBe(true),
    );
  });
});
```

- [ ] **Step 2: Write `frontend/src/screens/SettingsScreen.tsx`** + `SettingsScreen.module.css`

```tsx
import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
import s from "./SettingsScreen.module.css";

type Tab = "general" | "fees" | "batching";

export function SettingsScreen() {
  const [me, setMe] = useState<RestaurantOut | null>(null);
  const [tab, setTab] = useState<Tab>("batching");
  const [ordersPerBatch, setOrdersPerBatch] = useState(3);
  const [itemsPerOrder, setItemsPerOrder] = useState(20);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiClient.get<RestaurantOut>("/api/v1/me").then((r) => {
      setMe(r);
      const sset = r.settings as Record<string, number>;
      if (typeof sset.max_orders_per_batch === "number") setOrdersPerBatch(sset.max_orders_per_batch);
      if (typeof sset.max_items_per_order === "number") setItemsPerOrder(sset.max_items_per_order);
    });
  }, []);

  async function save() {
    await apiClient.patch("/api/v1/settings", {
      max_orders_per_batch: ordersPerBatch,
      max_items_per_order: itemsPerOrder,
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className={s.screen}>
      <div className={s.tabs}>
        {(["general", "fees", "batching"] as Tab[]).map((t) => (
          <button key={t} className={`${s.tab} ${tab === t ? s.active : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      {saved && <SectionBanner tone="success">Settings saved.</SectionBanner>}

      {tab === "general" && (
        <div className={s.section}>
          <Field label="Restaurant" value={me?.name ?? "—"} />
          <Field label="Phone" value={me?.phone ?? "—"} />
        </div>
      )}

      {tab === "fees" && (
        <div className={s.section}>
          <p className={s.note}>Fee tiers: ≤3km free · 3–5km AED 5 · &gt;5km AED 10. Max radius 10 km.</p>
        </div>
      )}

      {tab === "batching" && (
        <div className={s.section}>
          <label className={s.field}>
            <span className="label-upper">Max orders per batch</span>
            <input
              aria-label="orders per batch"
              type="number"
              min={1}
              max={6}
              value={ordersPerBatch}
              onChange={(e) => setOrdersPerBatch(Number(e.target.value))}
            />
          </label>
          <label className={s.field}>
            <span className="label-upper">Max items per order</span>
            <input
              aria-label="items per order"
              type="number"
              min={1}
              max={100}
              value={itemsPerOrder}
              onChange={(e) => setItemsPerOrder(Number(e.target.value))}
            />
          </label>
          <Button onClick={save}>Save</Button>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.field}>
      <span className="label-upper">{label}</span>
      <span>{value}</span>
    </div>
  );
}
```

```css
.screen {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 520px;
}
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border-subtle);
}
.tab {
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  padding: 8px 12px;
  text-transform: capitalize;
  cursor: pointer;
  font-size: 13px;
}
.active {
  color: var(--accent-primary);
  border-bottom-color: var(--accent-primary);
}
.section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field input {
  background: var(--bg-surface-inset);
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  padding: 8px 12px;
  color: var(--text-primary);
  width: 160px;
}
.note {
  color: var(--text-secondary);
  font-size: 13px;
}
```

- [ ] **Step 3: Write `frontend/src/screens/AnalyticsScreen.tsx`** + `AnalyticsScreen.module.css`

```tsx
import s from "./AnalyticsScreen.module.css";

export function AnalyticsScreen() {
  return (
    <div className={s.wrap}>
      <span className="label-upper">Analytics</span>
      <p className={s.note}>Analytics dashboard arrives in a later phase (Predictions &amp; reporting).</p>
    </div>
  );
}
```

```css
.wrap {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 24px;
}
.note {
  color: var(--text-muted);
  font-size: 13px;
}
```

- [ ] **Step 4: Run test + type-check**

Run: `cd frontend && npm run test -- SettingsScreen && npm run lint`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/SettingsScreen.tsx frontend/src/screens/SettingsScreen.module.css frontend/src/screens/SettingsScreen.test.tsx frontend/src/screens/AnalyticsScreen.tsx frontend/src/screens/AnalyticsScreen.module.css
git commit -m "feat: Settings screen (tabbed, batching editor) + Analytics placeholder"
```

---

### Task 15: Playwright smoke e2e + full-suite gate

**Files:** Create `frontend/playwright.config.ts`, `frontend/e2e/smoke.spec.ts`.

**Smoke goal:** boot the built app via Playwright's webServer (vite preview), intercept all `/api/**` calls with stubbed JSON (no live backend), drive login → assert Live Ops renders with a KPI tile and a feed row. One spec, fast, deterministic.

- [ ] **Step 1: Install Playwright browsers**

Run: `cd frontend && npx playwright install chromium`
Expected: chromium downloaded.

- [ ] **Step 2: Write `frontend/playwright.config.ts`**

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:4173",
    headless: true,
  },
  webServer: {
    command: "npm run build && npm run preview -- --port 4173",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

- [ ] **Step 3: Write `frontend/e2e/smoke.spec.ts`**

```ts
import { expect, test } from "@playwright/test";

test("login → live ops renders KPI strip and feed", async ({ page }) => {
  // Stub auth + me; orders endpoint returns 404 so the UI uses fixtures.
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ access_token: "e2e-token", token_type: "bearer" }) }),
  );
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 1, name: "E2E Resto", phone: "+9714", lat: 25.2, lng: 55.2, settings: {} }) }),
  );
  await page.route("**/api/v1/orders", (route) =>
    route.fulfill({ status: 404, contentType: "text/plain", body: "not found" }),
  );

  await page.goto("/login");
  await page.getByLabel("Phone").fill("+97150000000");
  await page.getByLabel("Password").fill("password1");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page.getByText("Orders Today")).toBeVisible();
  await expect(page.getByText("Ali Hassan")).toBeVisible();
});
```

NOTE: fixtures are bundled into the build (imported JSON), so the 404-fallback path runs entirely client-side — the smoke needs no live API.

- [ ] **Step 4: Run the smoke**

Run: `cd frontend && npm run e2e`
Expected: 1 passed.

- [ ] **Step 5: Full-suite gate — run everything**

Run:
```bash
cd frontend && npm run lint && npm run test && npm run build && npm run e2e
```
Expected: type-check clean, all vitest specs PASS, build succeeds, 1 Playwright spec PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e/smoke.spec.ts
git commit -m "test: Playwright smoke e2e (login → live ops) + full suite gate"
```

---

## Phase 5 completion checklist (gate before declaring done)

- [ ] `npm run lint` (tsc --noEmit) clean — no type errors, no unused.
- [ ] `npm run test` — all vitest component/unit specs green.
- [ ] `npm run build` — production bundle builds with no errors.
- [ ] `npm run e2e` — Playwright smoke passes.
- [ ] All 9 brief screens present: Login, Live Ops, Orders, Menu Manager, Riders, Conversations, Settings, Analytics (placeholder) — Audit/Marketing/Predictions explicitly deferred to a later phase and NOT in this plan's scope (scope lists 9 screens: the 8 built + analytics placeholder).
- [ ] SLA color threading verified visually: order 47 in yellow lane, breach styling on a >40min order.
- [ ] Design tokens match brief §1 verbatim (tokens.test.ts guards the spine).
- [ ] Polling abstraction (`Transport` interface) in place — a `WebSocketTransport` can be added later implementing the same `subscribe()` surface with zero screen changes.
- [ ] Do NOT commit `frontend/node_modules`, `frontend/dist`, `frontend/test-results`, `frontend/playwright-report`. Add a `frontend/.gitignore` with these entries in Task 1 if not already present (append: `node_modules/`, `dist/`, `test-results/`, `playwright-report/`, `.env`).

## Scope notes for the implementer

- **Marketing Studio, Predictions, Audit Explorer** (brief screens 5, 6, 8) are intentionally OUT of this phase per the task scope (9 screens defined as: the operational 8 + analytics placeholder). Their nav entries are omitted; add them in a follow-up phase when the backend endpoints exist.
- **Dispatch map** (real Mapbox/Google tiles, rider dots, batch hulls) is a labeled placeholder panel here — live tracking + map is its own phase. The SLA board and feed deliver the operational value without it.
- **Real-time** is polling at 4s. The `Transport`/`PollingTransport` split is the seam for a future WebSocket (`/ws/dashboard` per brief). Do not inline `setInterval` into screens — always go through `usePoll`.
- **Auth token** in localStorage with a documented httpOnly upgrade path (Task 3). Acceptable for a separately-hosted SPA against a bearer API; revisit when the backend issues same-site cookies.
- **Order/Conversation endpoints** that may not exist yet use the fixture-fallback pattern (Tasks 7, 13) so the UI is fully buildable and testable today and switches to live data automatically once the endpoints ship.
