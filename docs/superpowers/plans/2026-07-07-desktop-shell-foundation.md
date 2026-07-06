# Desktop Shell Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the existing `frontend/` React dashboard in a native Windows Electron shell that adds an offline SQLite cache/queue, a sync engine talking to the existing FastAPI backend, and a boundary for future native hardware access — with zero changes to business logic.

**Architecture:** Electron main process owns a local SQLite cache + write queue and syncs it against the existing cloud backend over HTTPS using the existing REST API (plus two small additions: `updated_since` pull filters and `Idempotency-Key` push dedup). The renderer process is the existing React app, modified only at its HTTP layer (`apiClient.ts`) to route through Electron's IPC bridge when running inside the desktop shell, and to fall back to plain `fetch` when running as a plain browser tab (so existing web deployment and tests keep working unchanged).

**Tech Stack:** Electron + electron-builder, better-sqlite3 (main process, synchronous SQLite — no async driver complexity for a single-writer local cache), TypeScript, existing React/Vite frontend, existing FastAPI/SQLAlchemy backend, Playwright (supports driving Electron apps directly, same vendored install already in repo).

## Global Constraints

- TDD: failing test first, then implementation, per task.
- Commit per task, conventional-commit style (`feat:`, `chore:`, `test:`).
- New backend tables use `TimestampMixin` → add `BEFORE UPDATE` trigger `trg_<table>_updated_at` in the same migration (see `updated_at_triggers` migration for the pattern).
- New backend model modules must be imported in **both** `alembic/env.py` and `tests/conftest.py`.
- Every tenant-scoped table carries `restaurant_id` with an index; routers never touch another module's models — only their own service.
- No new business logic or FSM changes in this plan — this is transport/shell only.
- Existing web (non-Electron) usage of `frontend/` must keep working unmodified after every task (run `npm test -- --run` after each frontend-touching task).

---

### Task 1: Scaffold the Electron shell project

**Files:**
- Create: `desktop/package.json`
- Create: `desktop/tsconfig.json`
- Create: `desktop/src/main/main.ts`
- Create: `desktop/src/main/preload.ts`
- Test: `desktop/src/main/main.test.ts`

**Interfaces:**
- Produces: `desktop/src/main/main.ts` exports `createMainWindow(loadUrl: string): BrowserWindow` — the only entry point later tasks and tests call.

- [ ] **Step 1: Create `desktop/package.json`**

```json
{
  "name": "full-pos-desktop",
  "private": true,
  "version": "0.1.0",
  "main": "dist/main/main.js",
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "start": "npm run build && electron dist/main/main.js",
    "test": "vitest run",
    "dist": "npm run build && electron-builder"
  },
  "devDependencies": {
    "electron": "^31.0.0",
    "electron-builder": "^24.13.3",
    "typescript": "^5.5.4",
    "vitest": "^2.1.1"
  }
}
```

- [ ] **Step 2: Create `desktop/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "CommonJS",
    "moduleResolution": "node",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Write the failing test**

```typescript
// desktop/src/main/main.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("electron", () => {
  class FakeBrowserWindow {
    loadedUrl: string | undefined;
    loadURL(url: string) {
      this.loadedUrl = url;
    }
  }
  return { BrowserWindow: FakeBrowserWindow };
});

import { createMainWindow } from "./main";

describe("createMainWindow", () => {
  it("loads the given URL into a BrowserWindow", () => {
    const win = createMainWindow("http://localhost:5173");
    expect((win as unknown as { loadedUrl: string }).loadedUrl).toBe(
      "http://localhost:5173",
    );
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/main.test.ts`
Expected: FAIL — `Cannot find module './main'` (file doesn't exist yet)

- [ ] **Step 5: Write minimal implementation**

```typescript
// desktop/src/main/main.ts
import { app, BrowserWindow } from "electron";
import path from "path";

export function createMainWindow(loadUrl: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadURL(loadUrl);
  return win;
}

// Real app bootstrap — not exercised by the unit test (mocked `app`/`BrowserWindow`).
if (require.main === module) {
  app.whenReady().then(() => {
    const target = process.env.POS_SHELL_URL ?? "http://localhost:5173";
    createMainWindow(target);
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
```

- [ ] **Step 6: Create the preload stub**

```typescript
// desktop/src/main/preload.ts
// Populated in Task 4 with the posBridge IPC surface. Empty context-isolated
// bridge for now so contextIsolation:true doesn't break window creation.
import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("posBridge", {});
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/main.test.ts`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add desktop/
git commit -m "feat: scaffold Electron shell project"
```

---

### Task 2: Package the shell as a Windows .exe loading the existing dashboard build

**Files:**
- Create: `desktop/electron-builder.yml`
- Modify: `desktop/package.json` (add `build` config reference, `postinstall` note)
- Test: `desktop/scripts/verify_build.sh`

**Interfaces:**
- Consumes: `frontend/dist` (existing `npm run build` output in `frontend/`, unmodified).
- Produces: `desktop/dist_installer/*.exe` (electron-builder output directory).

- [ ] **Step 1: Create `desktop/electron-builder.yml`**

```yaml
appId: com.catalystiq.fullpos.desktop
productName: Full POS
directories:
  output: dist_installer
  buildResources: build
files:
  - dist/main/**/*
  - "../frontend/dist/**/*"
win:
  target: nsis
  artifactName: "FullPOS-Setup-${version}.exe"
nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
```

- [ ] **Step 2: Point the shell at the bundled dashboard instead of localhost in production**

Modify `desktop/src/main/main.ts`'s bootstrap block:

```typescript
if (require.main === module) {
  app.whenReady().then(() => {
    const target =
      process.env.POS_SHELL_URL ??
      `file://${path.join(process.resourcesPath, "frontend", "dist", "index.html")}`;
    createMainWindow(target);
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
```

(`POS_SHELL_URL=http://localhost:5173` is still used for local dev via `npm start`, set by developers; production installer omits it and falls through to the bundled `file://` path.)

- [ ] **Step 3: Write the build verification script**

```bash
#!/usr/bin/env bash
# desktop/scripts/verify_build.sh
set -euo pipefail
cd "$(dirname "$0")/.."
npm run dist
INSTALLER=$(find dist_installer -name "FullPOS-Setup-*.exe" | head -n1)
if [ -z "$INSTALLER" ]; then
  echo "FAIL: no .exe installer produced" >&2
  exit 1
fi
echo "PASS: installer produced at $INSTALLER"
```

- [ ] **Step 4: Run it to verify it fails (frontend not built yet in a fresh checkout)**

Run: `cd frontend && rm -rf dist && cd ../desktop && bash scripts/verify_build.sh`
Expected: FAIL (electron-builder errors — `../frontend/dist` glob matches nothing)

- [ ] **Step 5: Build the frontend, then re-run**

Run: `cd frontend && npm run build && cd ../desktop && chmod +x scripts/verify_build.sh && bash scripts/verify_build.sh`
Expected: `PASS: installer produced at dist_installer/FullPOS-Setup-0.1.0.exe`

- [ ] **Step 6: Commit**

```bash
git add desktop/
git commit -m "feat: package Electron shell into a Windows .exe installer"
```

---

### Task 3: Local SQLite cache module

**Files:**
- Create: `desktop/src/main/db.ts`
- Test: `desktop/src/main/db.test.ts`
- Modify: `desktop/package.json` (add `better-sqlite3` dependency)

**Interfaces:**
- Produces: `openLocalDb(filePath: string): Database.Database` and `initSchema(db: Database.Database): void` — used by Tasks 5, 6, 7.

- [ ] **Step 1: Add dependency**

```json
"dependencies": {
  "better-sqlite3": "^11.3.0"
}
```

- [ ] **Step 2: Write the failing test**

```typescript
// desktop/src/main/db.test.ts
import { describe, it, expect, afterEach } from "vitest";
import fs from "fs";
import os from "os";
import path from "path";
import { openLocalDb, initSchema } from "./db";

const tmpFiles: string[] = [];

afterEach(() => {
  for (const f of tmpFiles.splice(0)) fs.rmSync(f, { force: true });
});

describe("initSchema", () => {
  it("creates local_menu, local_orders, pending_ops, sync_state tables", () => {
    const file = path.join(os.tmpdir(), `posdb-${Date.now()}.sqlite`);
    tmpFiles.push(file);
    const db = openLocalDb(file);
    initSchema(db);
    const tables = db
      .prepare("SELECT name FROM sqlite_master WHERE type='table'")
      .all()
      .map((r: { name: string }) => r.name);
    expect(tables).toEqual(
      expect.arrayContaining([
        "local_menu",
        "local_orders",
        "pending_ops",
        "sync_state",
      ]),
    );
    db.close();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npm install && npx vitest run src/main/db.test.ts`
Expected: FAIL — `Cannot find module './db'`

- [ ] **Step 4: Write minimal implementation**

```typescript
// desktop/src/main/db.ts
import Database from "better-sqlite3";

export function openLocalDb(filePath: string): Database.Database {
  return new Database(filePath);
}

export function initSchema(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS local_menu (
      dish_id INTEGER PRIMARY KEY,
      payload TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS local_orders (
      order_id INTEGER PRIMARY KEY,
      payload TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS pending_ops (
      id TEXT PRIMARY KEY,
      entity TEXT NOT NULL,
      entity_id INTEGER,
      op TEXT NOT NULL CHECK (op IN ('create', 'update')),
      method TEXT NOT NULL,
      path TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'synced', 'failed', 'conflict')),
      attempts INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS sync_state (
      entity TEXT PRIMARY KEY,
      last_synced_at TEXT,
      last_cursor TEXT
    );
  `);
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/db.test.ts`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add desktop/
git commit -m "feat: local SQLite cache schema (menu, orders, pending ops, sync state)"
```

---

### Task 4: Pending-ops queue (enqueue + drain-order read)

**Files:**
- Create: `desktop/src/main/pendingOps.ts`
- Test: `desktop/src/main/pendingOps.test.ts`

**Interfaces:**
- Consumes: `Database.Database` from Task 3's `openLocalDb`/`initSchema`.
- Produces: `enqueueOp(db, op: NewPendingOp): string` (returns generated id), `readPendingOps(db): PendingOp[]` (FIFO by `created_at`), `markOpStatus(db, id: string, status: PendingOpStatus): void`, and the `NewPendingOp`/`PendingOp`/`PendingOpStatus` types — used by Task 6 (apiClient adapter) and Task 7 (push sync loop).

- [ ] **Step 1: Write the failing test**

```typescript
// desktop/src/main/pendingOps.test.ts
import { describe, it, expect, beforeEach } from "vitest";
import { openLocalDb, initSchema } from "./db";
import { enqueueOp, readPendingOps, markOpStatus } from "./pendingOps";
import type Database from "better-sqlite3";

let db: Database.Database;

beforeEach(() => {
  db = openLocalDb(":memory:");
  initSchema(db);
});

describe("pendingOps", () => {
  it("enqueues and reads back in FIFO order", () => {
    const id1 = enqueueOp(db, {
      entity: "orders",
      entityId: 1,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/1/status",
      payload: { status: "preparing" },
    });
    const id2 = enqueueOp(db, {
      entity: "orders",
      entityId: 2,
      op: "create",
      method: "POST",
      path: "/api/v1/orders",
      payload: { customer_id: 5 },
    });
    const rows = readPendingOps(db);
    expect(rows.map((r) => r.id)).toEqual([id1, id2]);
    expect(rows[0].status).toBe("pending");
  });

  it("marks an op's status", () => {
    const id = enqueueOp(db, {
      entity: "orders",
      entityId: 1,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/1/status",
      payload: {},
    });
    markOpStatus(db, id, "synced");
    const rows = readPendingOps(db);
    expect(rows.find((r) => r.id === id)?.status).toBe("synced");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/pendingOps.test.ts`
Expected: FAIL — `Cannot find module './pendingOps'`

- [ ] **Step 3: Write minimal implementation**

```typescript
// desktop/src/main/pendingOps.ts
import type Database from "better-sqlite3";
import { randomUUID } from "crypto";

export type PendingOpStatus = "pending" | "synced" | "failed" | "conflict";

export interface NewPendingOp {
  entity: string;
  entityId: number | null;
  op: "create" | "update";
  method: string;
  path: string;
  payload: unknown;
}

export interface PendingOp extends NewPendingOp {
  id: string;
  createdAt: string;
  status: PendingOpStatus;
  attempts: number;
}

export function enqueueOp(db: Database.Database, newOp: NewPendingOp): string {
  const id = randomUUID();
  db.prepare(
    `INSERT INTO pending_ops
      (id, entity, entity_id, op, method, path, payload, created_at, status, attempts)
     VALUES (@id, @entity, @entityId, @op, @method, @path, @payload, @createdAt, 'pending', 0)`,
  ).run({
    id,
    entity: newOp.entity,
    entityId: newOp.entityId,
    op: newOp.op,
    method: newOp.method,
    path: newOp.path,
    payload: JSON.stringify(newOp.payload),
    createdAt: new Date().toISOString(),
  });
  return id;
}

export function readPendingOps(db: Database.Database): PendingOp[] {
  const rows = db
    .prepare(`SELECT * FROM pending_ops ORDER BY created_at ASC`)
    .all() as Array<{
    id: string;
    entity: string;
    entity_id: number | null;
    op: "create" | "update";
    method: string;
    path: string;
    payload: string;
    created_at: string;
    status: PendingOpStatus;
    attempts: number;
  }>;
  return rows.map((r) => ({
    id: r.id,
    entity: r.entity,
    entityId: r.entity_id,
    op: r.op,
    method: r.method,
    path: r.path,
    payload: JSON.parse(r.payload),
    createdAt: r.created_at,
    status: r.status,
    attempts: r.attempts,
  }));
}

export function markOpStatus(
  db: Database.Database,
  id: string,
  status: PendingOpStatus,
): void {
  db.prepare(`UPDATE pending_ops SET status = @status WHERE id = @id`).run({
    id,
    status,
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/pendingOps.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/
git commit -m "feat: pending-ops offline write queue"
```

---

### Task 5: Backend — `Idempotency-Key` dedup for mutating requests

**Files:**
- Create: `src/app/idempotency/__init__.py`
- Create: `src/app/idempotency/models.py`
- Create: `src/app/idempotency/middleware.py`
- Modify: `src/app/main.py` (register middleware)
- Modify: `alembic/env.py` (import new model module)
- Modify: `tests/conftest.py` (import new model module)
- Create: `alembic/versions/<rev>_idempotency_keys.py`
- Test: `tests/idempotency/test_middleware.py`

**Interfaces:**
- Produces: `IdempotencyKey` model (table `idempotency_keys`); `IdempotencyMiddleware` (Starlette `BaseHTTPMiddleware` subclass) registered in `main.py`. Desktop Task 7 sets the `Idempotency-Key` header this middleware reads.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/idempotency/test_middleware.py
import pytest


@pytest.mark.anyio
async def test_duplicate_idempotency_key_returns_cached_response(
    client, auth_headers, restaurant
):
    headers = {**auth_headers, "Idempotency-Key": "test-key-123"}
    payload = {"name": "Rider One", "phone": "+971500000001"}

    first = await client.post("/api/v1/riders", json=payload, headers=headers)
    assert first.status_code == 201
    first_body = first.json()

    second = await client.post("/api/v1/riders", json=payload, headers=headers)
    assert second.status_code == 201
    assert second.json() == first_body  # replay returns the SAME rider, not a second one
```

(Uses the existing `client`, `auth_headers`, `restaurant` fixtures already defined in `tests/conftest.py` / `tests/identity/conftest.py` for the riders endpoint, which is already a simple authenticated POST with no other required state.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/idempotency/test_middleware.py -v`
Expected: FAIL — second POST creates a second rider (`second.json() != first_body`), or collection error (`tests/idempotency/` doesn't exist yet — add `tests/idempotency/__init__.py`)

- [ ] **Step 3: Create the model**

```python
# src/app/idempotency/models.py
from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.mixins import TimestampMixin


class IdempotencyKey(TimestampMixin, Base):
    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = ({"schema": None},)
```

(`TimestampMixin` and `Base` paths match the existing convention — check `src/app/audit/models.py` for the exact import if `app.mixins`/`app.db` differ; use whatever the existing models in this repo import.)

- [ ] **Step 4: Create `src/app/idempotency/__init__.py`**

```python
# src/app/idempotency/__init__.py
```

- [ ] **Step 5: Write the middleware**

```python
# src/app/idempotency/middleware.py
import json

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.idempotency.models import IdempotencyKey

_MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Dedupe replayed mutating requests carrying an Idempotency-Key header.

    Scoped by (restaurant_id, key, method, path) — a retried desktop-shell
    sync op after a dropped connection replays the exact same call and must
    get back the original response, never re-apply the mutation.
    """

    def __init__(self, app, session_factory) -> None:
        super().__init__(app)
        self._session_factory = session_factory

    async def dispatch(self, request: Request, call_next) -> Response:
        key = request.headers.get("Idempotency-Key")
        if key is None or request.method not in _MUTATING_METHODS:
            return await call_next(request)

        restaurant_id = getattr(request.state, "restaurant_id", None)
        async with self._session_factory() as session:
            if restaurant_id is not None:
                existing = await session.scalar(
                    select(IdempotencyKey).where(
                        IdempotencyKey.restaurant_id == restaurant_id,
                        IdempotencyKey.key == key,
                        IdempotencyKey.method == request.method,
                        IdempotencyKey.path == request.url.path,
                    )
                )
                if existing is not None:
                    return Response(
                        content=existing.response_body,
                        status_code=existing.response_status,
                        media_type="application/json",
                    )

        response = await call_next(request)

        restaurant_id = getattr(request.state, "restaurant_id", None)
        if restaurant_id is not None and 200 <= response.status_code < 300:
            body_chunks = [section async for section in response.body_iterator]
            body = b"".join(body_chunks)
            response.body_iterator = _aiter([body])
            async with self._session_factory() as session:
                session.add(
                    IdempotencyKey(
                        restaurant_id=restaurant_id,
                        key=key,
                        method=request.method,
                        path=request.url.path,
                        response_status=response.status_code,
                        response_body=body.decode(),
                    )
                )
                await session.commit()
            return response
        return response


async def _aiter(chunks):
    for chunk in chunks:
        yield chunk
```

(`request.state.restaurant_id` is set by the existing `current_restaurant` dependency; if that dependency instead returns the restaurant without stashing it on `request.state`, add one line to `identity/deps.py`'s `current_restaurant` to do `request.state.restaurant_id = restaurant.id` before returning — check that file for the exact shape before writing this line.)

- [ ] **Step 6: Register the middleware in `src/app/main.py`**

Add near the existing `SecurityHeadersMiddleware` registration:

```python
from app.idempotency.middleware import IdempotencyMiddleware
from app.db import async_session_factory  # existing session factory used elsewhere in main.py

app.add_middleware(IdempotencyMiddleware, session_factory=async_session_factory)
```

- [ ] **Step 7: Generate and apply the migration**

Add the model import to `alembic/env.py` and `tests/conftest.py` (next to the other model imports), then:

Run: `.venv/bin/alembic revision --autogenerate -m "idempotency_keys"`

Edit the generated migration to add the `updated_at` trigger, following the exact pattern in the existing `updated_at_triggers` migration:

```python
def upgrade() -> None:
    # ... autogenerated create_table for idempotency_keys ...
    op.execute(
        """
        CREATE TRIGGER trg_idempotency_keys_updated_at
        BEFORE UPDATE ON idempotency_keys
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_idempotency_keys_updated_at ON idempotency_keys;")
    # ... autogenerated drop_table ...
```

Run: `.venv/bin/alembic upgrade head`

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/pytest tests/idempotency/test_middleware.py -v`
Expected: PASS

- [ ] **Step 9: Run full backend suite + lint**

Run: `.venv/bin/pytest && .venv/bin/ruff check src apps tests`
Expected: all pass, lint clean

- [ ] **Step 10: Commit**

```bash
git add src/app/idempotency alembic/ tests/idempotency src/app/main.py tests/conftest.py
git commit -m "feat: idempotency-key dedup middleware for mutating API requests"
```

---

### Task 6: Backend — `updated_since` pull filter on menu and orders list endpoints

**Files:**
- Modify: `src/app/menu/router.py` (list endpoint)
- Modify: `src/app/menu/service.py` (query function)
- Modify: `src/app/ordering/router.py` (list endpoint) — check exact function name via `grep -n "def list" src/app/ordering/router.py` before editing
- Test: `tests/menu/test_updated_since_filter.py`

**Interfaces:**
- Produces: `GET /api/v1/menu/dishes?updated_since=<ISO8601>` and `GET /api/v1/orders?updated_since=<ISO8601>` return only rows with `updated_at > updated_since`. Desktop Task 8's pull sync calls these.

- [ ] **Step 1: Write the failing test**

```python
# tests/menu/test_updated_since_filter.py
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.anyio
async def test_updated_since_filters_out_older_dishes(client, auth_headers, active_menu_with_dish):
    cutoff = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()

    resp = await client.get(
        f"/api/v1/menu/dishes?updated_since={cutoff}", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []  # existing dish is older than the cutoff, filtered out

    resp_all = await client.get("/api/v1/menu/dishes", headers=auth_headers)
    assert resp_all.status_code == 200
    assert len(resp_all.json()) >= 1  # without the filter, the dish is still there
```

(`active_menu_with_dish` — use whatever existing fixture in `tests/menu/conftest.py` already creates an active menu with one dish; check that file first and reuse its exact name instead of inventing a new one.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/menu/test_updated_since_filter.py -v`
Expected: FAIL — `updated_since` query param is unknown/ignored, both responses return the same non-empty list

- [ ] **Step 3: Add the query param and filter**

In `src/app/menu/router.py`'s dish list endpoint, add:

```python
from datetime import datetime
from fastapi import Query

# ... inside the existing list_dishes(...) signature, add:
updated_since: datetime | None = Query(default=None),
```

and pass it through to the service call, e.g. `service.list_dishes(session, restaurant.id, updated_since=updated_since)`.

In `src/app/menu/service.py`'s `list_dishes`, add the parameter and filter:

```python
async def list_dishes(
    session: AsyncSession,
    restaurant_id: int,
    updated_since: datetime | None = None,
) -> list[Dish]:
    stmt = select(Dish).where(Dish.restaurant_id == restaurant_id)
    if updated_since is not None:
        stmt = stmt.where(Dish.updated_at > updated_since)
    result = await session.scalars(stmt)
    return list(result)
```

(Match this against the actual current signature/body of `list_dishes` — read the file first and adapt the diff to whatever filters/ordering already exist there; don't remove existing behavior.)

Repeat the same `updated_since` param + filter for the orders list endpoint in `src/app/ordering/router.py` / its service function.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/menu/test_updated_since_filter.py -v`
Expected: PASS

- [ ] **Step 5: Run full backend suite + lint**

Run: `.venv/bin/pytest && .venv/bin/ruff check src apps tests`
Expected: all pass, lint clean

- [ ] **Step 6: Commit**

```bash
git add src/app/menu src/app/ordering tests/menu/test_updated_since_filter.py
git commit -m "feat: updated_since filter on menu/order list endpoints for desktop pull sync"
```

---

### Task 7: Desktop — pull sync loop

**Files:**
- Create: `desktop/src/main/sync.ts`
- Test: `desktop/src/main/sync.test.ts`

**Interfaces:**
- Consumes: `openLocalDb`/`initSchema` (Task 3); backend `GET /api/v1/menu/dishes?updated_since=` and `GET /api/v1/orders?updated_since=` (Task 6).
- Produces: `pullSync(db, apiBase, fetchImpl, token): Promise<void>` — called by Task 9's push+pull scheduler.

- [ ] **Step 1: Write the failing test**

```typescript
// desktop/src/main/sync.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { openLocalDb, initSchema } from "./db";
import { pullSync } from "./sync";
import type Database from "better-sqlite3";

let db: Database.Database;

beforeEach(() => {
  db = openLocalDb(":memory:");
  initSchema(db);
});

describe("pullSync", () => {
  it("upserts fetched dishes into local_menu and advances the cursor", async () => {
    const fakeFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { id: 42, name: "Chicken Biryani", updated_at: "2026-07-07T10:00:00Z" },
      ],
    });

    await pullSync(db, "http://api.test", fakeFetch as unknown as typeof fetch, "tok");

    const rows = db.prepare("SELECT * FROM local_menu").all() as Array<{
      dish_id: number;
      payload: string;
    }>;
    expect(rows).toHaveLength(1);
    expect(JSON.parse(rows[0].payload).name).toBe("Chicken Biryani");

    const state = db
      .prepare("SELECT * FROM sync_state WHERE entity = 'menu'")
      .get() as { last_cursor: string };
    expect(state.last_cursor).toBe("2026-07-07T10:00:00Z");

    expect(fakeFetch).toHaveBeenCalledWith(
      "http://api.test/api/v1/menu/dishes",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer tok" }),
      }),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/sync.test.ts`
Expected: FAIL — `Cannot find module './sync'`

- [ ] **Step 3: Write minimal implementation**

```typescript
// desktop/src/main/sync.ts
import type Database from "better-sqlite3";

interface DishPayload {
  id: number;
  updated_at: string;
  [key: string]: unknown;
}

function getCursor(db: Database.Database, entity: string): string | null {
  const row = db
    .prepare(`SELECT last_cursor FROM sync_state WHERE entity = ?`)
    .get(entity) as { last_cursor: string } | undefined;
  return row?.last_cursor ?? null;
}

function setCursor(db: Database.Database, entity: string, cursor: string): void {
  db.prepare(
    `INSERT INTO sync_state (entity, last_synced_at, last_cursor)
     VALUES (@entity, @now, @cursor)
     ON CONFLICT(entity) DO UPDATE SET last_synced_at = @now, last_cursor = @cursor`,
  ).run({ entity, now: new Date().toISOString(), cursor });
}

export async function pullSync(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
): Promise<void> {
  const cursor = getCursor(db, "menu");
  const url = new URL("/api/v1/menu/dishes", apiBase);
  if (cursor) url.searchParams.set("updated_since", cursor);

  const resp = await fetchImpl(url.toString(), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) return; // offline or server error — leave cache as-is, retried next tick

  const dishes = (await resp.json()) as DishPayload[];
  const upsert = db.prepare(
    `INSERT INTO local_menu (dish_id, payload, updated_at)
     VALUES (@dish_id, @payload, @updated_at)
     ON CONFLICT(dish_id) DO UPDATE SET payload = @payload, updated_at = @updated_at`,
  );
  let maxUpdatedAt = cursor;
  const tx = db.transaction((rows: DishPayload[]) => {
    for (const dish of rows) {
      upsert.run({
        dish_id: dish.id,
        payload: JSON.stringify(dish),
        updated_at: dish.updated_at,
      });
      if (!maxUpdatedAt || dish.updated_at > maxUpdatedAt) {
        maxUpdatedAt = dish.updated_at;
      }
    }
  });
  tx(dishes);

  if (maxUpdatedAt) setCursor(db, "menu", maxUpdatedAt);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/sync.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/
git commit -m "feat: pull sync loop for local menu cache"
```

---

### Task 8: Desktop — push sync loop (drain pending_ops with idempotency + backoff)

**Files:**
- Modify: `desktop/src/main/sync.ts` (add `pushSync`)
- Modify: `desktop/src/main/sync.test.ts`

**Interfaces:**
- Consumes: `readPendingOps`, `markOpStatus` (Task 4); backend `Idempotency-Key` handling (Task 5).
- Produces: `pushSync(db, apiBase, fetchImpl, token): Promise<void>` — called alongside `pullSync` by Task 9's scheduler.

- [ ] **Step 1: Write the failing test**

```typescript
// append to desktop/src/main/sync.test.ts
import { enqueueOp, readPendingOps } from "./pendingOps";
import { pushSync } from "./sync";

describe("pushSync", () => {
  it("replays a pending op with an Idempotency-Key header and marks it synced", async () => {
    const id = enqueueOp(db, {
      entity: "orders",
      entityId: 7,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/7/status",
      payload: { status: "preparing" },
    });
    const fakeFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });

    await pushSync(db, "http://api.test", fakeFetch as unknown as typeof fetch, "tok");

    expect(fakeFetch).toHaveBeenCalledWith(
      "http://api.test/api/v1/orders/7/status",
      expect.objectContaining({
        method: "PATCH",
        headers: expect.objectContaining({
          Authorization: "Bearer tok",
          "Idempotency-Key": id,
          "Content-Type": "application/json",
        }),
      }),
    );
    const rows = readPendingOps(db);
    expect(rows.find((r) => r.id === id)?.status).toBe("synced");
  });

  it("marks an op conflict (not retried) on a 409 response", async () => {
    const id = enqueueOp(db, {
      entity: "orders",
      entityId: 8,
      op: "update",
      method: "PATCH",
      path: "/api/v1/orders/8/status",
      payload: { status: "preparing" },
    });
    const fakeFetch = vi.fn().mockResolvedValue({ ok: false, status: 409 });

    await pushSync(db, "http://api.test", fakeFetch as unknown as typeof fetch, "tok");

    const rows = readPendingOps(db);
    expect(rows.find((r) => r.id === id)?.status).toBe("conflict");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/sync.test.ts`
Expected: FAIL — `pushSync is not a function`

- [ ] **Step 3: Write minimal implementation (append to `desktop/src/main/sync.ts`)**

```typescript
import { readPendingOps, markOpStatus, type PendingOp } from "./pendingOps";

export async function pushSync(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
): Promise<void> {
  const ops = readPendingOps(db).filter((op) => op.status === "pending");
  for (const op of ops) {
    await pushOne(db, apiBase, fetchImpl, token, op);
  }
}

async function pushOne(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
  op: PendingOp,
): Promise<void> {
  try {
    const resp = await fetchImpl(new URL(op.path, apiBase).toString(), {
      method: op.method,
      headers: {
        Authorization: `Bearer ${token}`,
        "Idempotency-Key": op.id,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(op.payload),
    });
    if (resp.status === 409) {
      markOpStatus(db, op.id, "conflict");
      return;
    }
    if (!resp.ok) {
      markOpStatus(db, op.id, "failed"); // retried next tick, see Task 9 scheduler
      return;
    }
    markOpStatus(db, op.id, "synced");
  } catch {
    markOpStatus(db, op.id, "failed"); // network error — offline, retried next tick
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/sync.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/
git commit -m "feat: push sync loop draining pending ops with idempotency keys"
```

---

### Task 9: Desktop — background scheduler wiring pull + push into the main process

**Files:**
- Modify: `desktop/src/main/main.ts`
- Create: `desktop/src/main/scheduler.ts`
- Test: `desktop/src/main/scheduler.test.ts`

**Interfaces:**
- Consumes: `pullSync`, `pushSync` (Tasks 7, 8).
- Produces: `startSyncScheduler(db, apiBase, fetchImpl, getToken, intervalMs): { stop(): void }` — wired into `main.ts`'s app-ready bootstrap; also the mechanism a later "sync on reconnect" step in Task 11 hooks into.

- [ ] **Step 1: Write the failing test**

```typescript
// desktop/src/main/scheduler.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { startSyncScheduler } from "./scheduler";

vi.mock("./sync", () => ({
  pullSync: vi.fn().mockResolvedValue(undefined),
  pushSync: vi.fn().mockResolvedValue(undefined),
}));

import { pullSync, pushSync } from "./sync";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("startSyncScheduler", () => {
  it("calls pushSync then pullSync on every tick", () => {
    const handle = startSyncScheduler(
      {} as never,
      "http://api.test",
      fetch,
      () => "tok",
      1000,
    );
    vi.advanceTimersByTime(3000);
    expect(pushSync).toHaveBeenCalledTimes(3);
    expect(pullSync).toHaveBeenCalledTimes(3);
    handle.stop();
    vi.advanceTimersByTime(3000);
    expect(pushSync).toHaveBeenCalledTimes(3); // no more calls after stop()
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/scheduler.test.ts`
Expected: FAIL — `Cannot find module './scheduler'`

- [ ] **Step 3: Write minimal implementation**

```typescript
// desktop/src/main/scheduler.ts
import type Database from "better-sqlite3";
import { pullSync, pushSync } from "./sync";

export function startSyncScheduler(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  getToken: () => string,
  intervalMs: number,
): { stop(): void } {
  const timer = setInterval(async () => {
    const token = getToken();
    await pushSync(db, apiBase, fetchImpl, token);
    await pullSync(db, apiBase, fetchImpl, token);
  }, intervalMs);
  return {
    stop() {
      clearInterval(timer);
    },
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/scheduler.test.ts`
Expected: PASS

- [ ] **Step 5: Wire it into `main.ts`'s bootstrap**

```typescript
// desktop/src/main/main.ts — inside the `if (require.main === module)` block, after createMainWindow:
import { openLocalDb, initSchema } from "./db";
import { startSyncScheduler } from "./scheduler";

// ... inside app.whenReady().then(() => { ... }):
const db = openLocalDb(path.join(app.getPath("userData"), "pos-cache.sqlite"));
initSchema(db);
startSyncScheduler(
  db,
  process.env.POS_API_BASE ?? "https://api.fullpos.example",
  fetch,
  () => process.env.POS_AUTH_TOKEN ?? "", // replaced by real auth-token storage in Task 10
  15000,
);
```

- [ ] **Step 6: Commit**

```bash
git add desktop/
git commit -m "feat: wire pull/push sync scheduler into Electron main process"
```

---

### Task 10: Renderer IPC bridge — route apiClient through Electron when present, fetch otherwise

**Files:**
- Modify: `desktop/src/main/preload.ts`
- Modify: `desktop/src/main/main.ts` (register `ipcMain.handle`)
- Modify: `frontend/src/lib/apiClient.ts`
- Modify: `frontend/src/lib/apiClient.test.ts`

**Interfaces:**
- Produces: `window.posBridge.request(method, path, body): Promise<{status: number, body: unknown}>` (renderer-visible); `apiClient`'s existing exported shape (`get`/`post`/etc.) is unchanged — only its internal `request()` gains a branch.

- [ ] **Step 1: Write the failing frontend test**

```typescript
// append to frontend/src/lib/apiClient.test.ts
describe("apiClient inside Electron shell", () => {
  const originalWindow = globalThis.window;

  afterEach(() => {
    // @ts-expect-error test cleanup
    globalThis.window = originalWindow;
  });

  it("routes GET requests through window.posBridge when present", async () => {
    const posBridgeRequest = vi.fn().mockResolvedValue({
      status: 200,
      body: { id: 1, name: "Test Rider" },
    });
    // @ts-expect-error augmenting window for this test only
    globalThis.window.posBridge = { request: posBridgeRequest };

    const result = await apiClient.get("/api/v1/riders/1");

    expect(posBridgeRequest).toHaveBeenCalledWith("GET", "/api/v1/riders/1", undefined);
    expect(result).toEqual({ id: 1, name: "Test Rider" });
    // @ts-expect-error test cleanup
    delete globalThis.window.posBridge;
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/apiClient.test.ts`
Expected: FAIL — `posBridgeRequest` never called (apiClient always uses `fetch`)

- [ ] **Step 3: Modify `frontend/src/lib/apiClient.ts`'s `request()` function**

```typescript
async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  isForm = false,
): Promise<T> {
  const bridge = (globalThis as typeof globalThis & {
    window?: { posBridge?: { request: (m: string, p: string, b: unknown) => Promise<{ status: number; body: unknown }> } };
  }).window?.posBridge;

  if (bridge) {
    const { status, body: responseBody } = await bridge.request(method, path, body);
    if (status >= 400) {
      const detail =
        typeof (responseBody as { detail?: unknown })?.detail === "string"
          ? (responseBody as { detail: string }).detail
          : JSON.stringify(responseBody);
      throw new ApiError(status, detail);
    }
    return responseBody as T;
  }

  // ... existing fetch-based implementation, unchanged below this point ...
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
    if (resp.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/apiClient.test.ts`
Expected: PASS

- [ ] **Step 5: Implement the main-process side of the bridge**

```typescript
// desktop/src/main/preload.ts
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("posBridge", {
  request: (method: string, path: string, body: unknown) =>
    ipcRenderer.invoke("pos-api-request", { method, path, body }),
});
```

```typescript
// desktop/src/main/main.ts — register the handler inside app.whenReady().then(() => { ... }):
import { ipcMain } from "electron";
import { enqueueOp } from "./pendingOps";

ipcMain.handle(
  "pos-api-request",
  async (_event, { method, path, body }: { method: string; path: string; body: unknown }) => {
    const apiBase = process.env.POS_API_BASE ?? "https://api.fullpos.example";
    const token = process.env.POS_AUTH_TOKEN ?? "";
    try {
      const resp = await fetch(new URL(path, apiBase).toString(), {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      const responseBody = resp.status === 204 ? undefined : await resp.json();
      return { status: resp.status, body: responseBody };
    } catch {
      // Offline: queue mutating requests, let GETs fail (renderer already has a
      // local cache read-through added in Task 11's conflict/cache-read step).
      if (method !== "GET") {
        enqueueOp(db, {
          entity: path.split("/")[3] ?? "unknown",
          entityId: null,
          op: method === "POST" ? "create" : "update",
          method,
          path,
          payload: body,
        });
        return { status: 202, body: { queued: true } };
      }
      return { status: 503, body: { detail: "offline, no cache available" } };
    }
  },
);
```

(`db` here refers to the same `Database.Database` instance created in Task 9's bootstrap step — move its declaration above both the scheduler call and this handler registration so both share the one instance.)

- [ ] **Step 6: Run the full frontend test suite to confirm nothing else broke**

Run: `cd frontend && npm test -- --run`
Expected: all existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add desktop/ frontend/src/lib/apiClient.ts frontend/src/lib/apiClient.test.ts
git commit -m "feat: route apiClient through Electron IPC bridge when running in the desktop shell"
```

---

### Task 11: Conflict surfacing UI

**Files:**
- Create: `frontend/src/components/SyncConflictBanner.tsx`
- Create: `frontend/src/components/SyncConflictBanner.test.tsx`
- Modify: `desktop/src/main/preload.ts` (expose `listConflicts`)
- Modify: `desktop/src/main/main.ts` (register `ipcMain.handle("pos-list-conflicts", ...)`)

**Interfaces:**
- Consumes: `pending_ops` rows with `status = 'conflict'` (Task 4/8).
- Produces: `<SyncConflictBanner />` React component — rendered once at the app shell root (wiring into the existing top-level layout, e.g. `AppShell.tsx`, is a one-line addition left for whoever integrates this into the real shell layout; not shown here since it doesn't need its own test).

- [ ] **Step 1: Write the failing component test**

```typescript
// frontend/src/components/SyncConflictBanner.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { SyncConflictBanner } from "./SyncConflictBanner";

afterEach(() => {
  // @ts-expect-error test cleanup
  delete globalThis.window.posBridge;
});

describe("SyncConflictBanner", () => {
  it("shows nothing when there are no conflicts", async () => {
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = {
      listConflicts: vi.fn().mockResolvedValue([]),
    };
    render(<SyncConflictBanner />);
    expect(await screen.findByTestId("sync-conflict-banner")).toHaveTextContent("");
  });

  it("shows a count when conflicts exist", async () => {
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = {
      listConflicts: vi.fn().mockResolvedValue([
        { id: "a", entity: "orders", path: "/api/v1/orders/8/status" },
      ]),
    };
    render(<SyncConflictBanner />);
    expect(
      await screen.findByText(/1 change couldn't sync/i),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/SyncConflictBanner.test.tsx`
Expected: FAIL — `Cannot find module './SyncConflictBanner'`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/SyncConflictBanner.tsx
import { useEffect, useState } from "react";

interface ConflictOp {
  id: string;
  entity: string;
  path: string;
}

export function SyncConflictBanner() {
  const [conflicts, setConflicts] = useState<ConflictOp[]>([]);

  useEffect(() => {
    const bridge = (
      window as unknown as { posBridge?: { listConflicts: () => Promise<ConflictOp[]> } }
    ).posBridge;
    if (!bridge) return;
    bridge.listConflicts().then(setConflicts);
  }, []);

  if (conflicts.length === 0) {
    return <div data-testid="sync-conflict-banner" />;
  }

  return (
    <div data-testid="sync-conflict-banner" role="alert">
      {conflicts.length} change{conflicts.length === 1 ? "" : "s"} couldn't sync — needs
      review
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/SyncConflictBanner.test.tsx`
Expected: PASS

- [ ] **Step 5: Add the main-process handler it depends on**

```typescript
// desktop/src/main/preload.ts — add alongside the existing `request` export:
listConflicts: () => ipcRenderer.invoke("pos-list-conflicts"),
```

```typescript
// desktop/src/main/main.ts — register alongside the pos-api-request handler:
ipcMain.handle("pos-list-conflicts", () => {
  return db
    .prepare(`SELECT id, entity, path FROM pending_ops WHERE status = 'conflict'`)
    .all();
});
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/SyncConflictBanner.tsx frontend/src/components/SyncConflictBanner.test.tsx desktop/src/main/
git commit -m "feat: surface unsynced conflict ops in a dashboard banner"
```

---

### Task 12: Native hardware access boundary (stubs for Phase B/F)

**Files:**
- Create: `desktop/src/main/native/printer.ts`
- Create: `desktop/src/main/native/printer.test.ts`
- Create: `desktop/src/main/native/usb.ts`
- Create: `desktop/src/main/native/usb.test.ts`

**Interfaces:**
- Produces: `PrinterPort` interface + `NotImplementedPrinter` (throws `"printer not implemented — see Phase B spec"` on `print()`), and `UsbPort` interface + `NotImplementedUsb` — the exact interface names Phase B's KDS print-job delivery and Phase F's hardware SDK implement against.

- [ ] **Step 1: Write the failing tests**

```typescript
// desktop/src/main/native/printer.test.ts
import { describe, it, expect } from "vitest";
import { NotImplementedPrinter } from "./printer";

describe("NotImplementedPrinter", () => {
  it("rejects print() until Phase B implements a real driver", async () => {
    const printer = new NotImplementedPrinter();
    await expect(printer.print({ stationId: 1, payload: "test ticket" })).rejects.toThrow(
      "printer not implemented — see Phase B spec",
    );
  });
});
```

```typescript
// desktop/src/main/native/usb.test.ts
import { describe, it, expect } from "vitest";
import { NotImplementedUsb } from "./usb";

describe("NotImplementedUsb", () => {
  it("rejects listDevices() until a later phase implements it", async () => {
    const usb = new NotImplementedUsb();
    await expect(usb.listDevices()).rejects.toThrow(
      "usb not implemented — see hardware SDK phase",
    );
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd desktop && npx vitest run src/main/native/printer.test.ts src/main/native/usb.test.ts`
Expected: FAIL — modules don't exist

- [ ] **Step 3: Write minimal implementations**

```typescript
// desktop/src/main/native/printer.ts
export interface PrintJob {
  stationId: number;
  payload: string;
}

export interface PrinterPort {
  print(job: PrintJob): Promise<void>;
}

export class NotImplementedPrinter implements PrinterPort {
  async print(_job: PrintJob): Promise<void> {
    throw new Error("printer not implemented — see Phase B spec");
  }
}
```

```typescript
// desktop/src/main/native/usb.ts
export interface UsbDevice {
  vendorId: number;
  productId: number;
}

export interface UsbPort {
  listDevices(): Promise<UsbDevice[]>;
}

export class NotImplementedUsb implements UsbPort {
  async listDevices(): Promise<UsbDevice[]> {
    throw new Error("usb not implemented — see hardware SDK phase");
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd desktop && npx vitest run src/main/native/printer.test.ts src/main/native/usb.test.ts`
Expected: PASS

- [ ] **Step 5: Run the full desktop test suite**

Run: `cd desktop && npx vitest run`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add desktop/src/main/native
git commit -m "feat: native printer/USB port boundary (stubs for Phase B and hardware SDK)"
```

---

## Self-Review Notes

- **Spec coverage:** §2 shell architecture → Tasks 1, 2, 10. §3 local data model → Task 3. §4 sync engine (push/pull/idempotency/conflict/retry) → Tasks 4, 7, 8, 9, 11. §5 server-side additions → Tasks 5, 6. §6 native hardware boundary → Task 12. §7 packaging → Task 2. §9 testing strategy → unit/integration tests embedded per task; E2E (Playwright-in-Electron) and manual Wi-Fi-kill UAT from spec §9 are deliberately **not** separate tasks here — they're validation activities to run once Tasks 1–12 are merged, not new production code, and depend on a real Windows machine + signed build the task-writer doesn't have access to in this environment. Flagging this as an explicit gap: add a follow-up manual QA pass before shipping the first `.exe` to a restaurant.
- **Placeholder scan:** no TBD/TODO left; the one deliberately-deferred item (E2E/manual UAT) is called out above rather than hidden.
- **Type consistency:** `PendingOp`/`NewPendingOp`/`PendingOpStatus` (Task 4) reused as-is in Tasks 8, 9, 11; `pullSync`/`pushSync` signatures (Tasks 7, 8) match the scheduler's calls (Task 9); `posBridge.request`/`posBridge.listConflicts` shapes match between preload (Task 10, 11), main-process handlers, and the frontend test mocks.
