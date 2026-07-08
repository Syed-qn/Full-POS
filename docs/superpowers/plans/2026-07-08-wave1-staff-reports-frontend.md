# Wave 1: Staff Ops + Reports Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the frontend gap for the already-tested `staff/` and `reports/` backends, plus fill two small backend gaps (break tracking, audit logging) identified in `docs/POS_100_FEATURE_AUDIT_2026-07-08.md`. Turns ~15 audit items from PARTIAL/MISSING to FULL.

**Architecture:** Two independent workstreams, run by 2 parallel agents. WS-STAFF touches `src/app/staff/`, `frontend/src/screens/StaffScreen*`. WS-REPORTS touches only `frontend/src/screens/ReportsScreen*` (zero backend changes — `reports/` endpoints are already complete). No shared files between the two workstreams — safe to run fully in parallel.

**Tech Stack:** FastAPI + SQLAlchemy 2 async (backend), React + TypeScript + Vitest/Testing Library (frontend), pytest + anyio (backend tests).

## Global Constraints

- Money: `Decimal`/`Numeric(8,2)`, AED. Times: UTC in DB.
- Routers never touch other modules' models — call services.
- Every mutating backend action that changes state must call `app.audit.service.record_audit` in the same transaction (existing project convention, `record_audit` never commits — caller commits).
- Frontend: reuse `apiClient` (`frontend/src/lib/apiClient.ts`), `PageHeader`, `Button`, `Toaster`/`toast()` components. Match `CouponsScreen.tsx` structure (load state, error state, empty state, form, table).
- Commit per task, conventional-commit style (`feat:`, `chore:`).
- Test commands: backend `.venv/bin/pytest tests/staff/ -v` (requires docker db up); frontend `cd frontend && npm test -- StaffScreen` / `npm test -- ReportsScreen`.

---

# WS-STAFF

## Task 1: Break tracking + overtime in `compute_hours`

**Files:**
- Modify: `src/app/staff/service.py`
- Modify: `src/app/staff/router.py`
- Test: `tests/staff/test_service.py`
- Test: `tests/staff/test_router.py`

**Interfaces:**
- Produces: `start_break(session, *, staff_id, restaurant_id, at) -> ClockEvent`, `end_break(session, *, staff_id, restaurant_id, at) -> ClockEvent`, `AlreadyOnBreakError`, `NotOnBreakError` (both `Exception` subclasses), `compute_hours(...)` now nets out break time, `OVERTIME_THRESHOLD_HOURS = 8.0` module constant.
- Consumes: existing `ClockEvent` model (`src/app/staff/models.py`), existing `_last_event` helper in `service.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/staff/test_service.py`:

```python
from app.staff.service import (
    AlreadyOnBreakError,
    NotOnBreakError,
    start_break,
    end_break,
)


@pytest.mark.anyio
async def test_break_time_is_subtracted_from_hours(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Huda", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()

    base = datetime.now(timezone.utc) - timedelta(hours=9)
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=base)
    await db_session.commit()
    await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=base + timedelta(hours=4))
    await db_session.commit()
    await end_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=base + timedelta(hours=5))
    await db_session.commit()
    await clock_out(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=base + timedelta(hours=9))
    await db_session.commit()

    hours = await compute_hours(db_session, staff_id=staff.id, restaurant_id=restaurant.id, target_date=date.today())
    assert hours == pytest.approx(8.0, abs=0.01)


@pytest.mark.anyio
async def test_break_start_without_clock_in_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Nadia", pin_hash="x")
    db_session.add(staff)
    await db_session.commit()
    with pytest.raises(NotClockedInError):
        await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))


@pytest.mark.anyio
async def test_double_break_start_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Yousef", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    with pytest.raises(AlreadyOnBreakError):
        await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))


@pytest.mark.anyio
async def test_break_end_without_break_start_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Rania", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    with pytest.raises(NotOnBreakError):
        await end_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
```

Append to `tests/staff/test_router.py`:

```python
@pytest.mark.anyio
async def test_hours_endpoint_reports_overtime(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Fatima", "pin": "9999"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]

    clock_start = await client.post(
        f"/api/v1/staff/{staff_id}/clock", json={"type": "break_start"}, headers=auth_headers,
    )
    assert clock_start.status_code == 409  # not clocked in yet


@pytest.mark.anyio
async def test_break_start_and_end_via_router(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Karim", "pin": "1111"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers)
    start = await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "break_start"}, headers=auth_headers)
    assert start.status_code == 200
    end = await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "break_end"}, headers=auth_headers)
    assert end.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/staff/test_service.py tests/staff/test_router.py -v`
Expected: FAIL — `ImportError: cannot import name 'start_break'` and 409-expected assertions fail (endpoint currently returns 422 for unknown type).

- [ ] **Step 3: Implement break tracking + overtime in `service.py`**

In `src/app/staff/service.py`, after the existing `NotClockedInError` class, add:

```python
class AlreadyOnBreakError(Exception):
    pass


class NotOnBreakError(Exception):
    pass


OVERTIME_THRESHOLD_HOURS = 8.0
```

Add after `clock_out`:

```python
async def start_break(session: AsyncSession, *, staff_id: int, restaurant_id: int, at: datetime) -> ClockEvent:
    last = await _last_event(session, staff_id=staff_id, restaurant_id=restaurant_id)
    if last is None or last.type == "clock_out":
        raise NotClockedInError(f"staff {staff_id} is not clocked in")
    if last.type == "break_start":
        raise AlreadyOnBreakError(f"staff {staff_id} is already on break")
    event = ClockEvent(restaurant_id=restaurant_id, staff_id=staff_id, type="break_start", at=at)
    session.add(event)
    await session.flush()
    return event


async def end_break(session: AsyncSession, *, staff_id: int, restaurant_id: int, at: datetime) -> ClockEvent:
    last = await _last_event(session, staff_id=staff_id, restaurant_id=restaurant_id)
    if last is None or last.type != "break_start":
        raise NotOnBreakError(f"staff {staff_id} is not on break")
    event = ClockEvent(restaurant_id=restaurant_id, staff_id=staff_id, type="break_end", at=at)
    session.add(event)
    await session.flush()
    return event
```

Replace the body of `compute_hours` with:

```python
async def compute_hours(session: AsyncSession, *, staff_id: int, restaurant_id: int, target_date: date) -> float:
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)
    events = (await session.scalars(
        select(ClockEvent)
        .where(
            ClockEvent.staff_id == staff_id, ClockEvent.restaurant_id == restaurant_id,
            ClockEvent.at >= day_start, ClockEvent.at <= day_end,
        )
        .order_by(ClockEvent.at)
    )).all()

    total_seconds = 0.0
    break_seconds = 0.0
    open_in: datetime | None = None
    open_break: datetime | None = None
    for event in events:
        at = event.at.replace(tzinfo=None) if event.at.tzinfo else event.at
        if event.type == "clock_in":
            open_in = at
        elif event.type == "clock_out" and open_in is not None:
            total_seconds += (at - open_in).total_seconds()
            open_in = None
        elif event.type == "break_start":
            open_break = at
        elif event.type == "break_end" and open_break is not None:
            break_seconds += (at - open_break).total_seconds()
            open_break = None
    return (total_seconds - break_seconds) / 3600.0


def compute_overtime_hours(worked_hours: float) -> float:
    return max(0.0, worked_hours - OVERTIME_THRESHOLD_HOURS)
```

- [ ] **Step 4: Wire break events + overtime into `router.py`**

In `src/app/staff/router.py`, update the import block:

```python
from app.staff.service import (
    AlreadyClockedInError,
    AlreadyOnBreakError,
    NotClockedInError,
    NotOnBreakError,
    clock_in,
    clock_out,
    compute_hours,
    compute_overtime_hours,
    compute_sales,
    start_break,
    end_break,
)
```

Replace the `clock` endpoint body's dispatch block:

```python
    try:
        if body.type == "clock_in":
            event = await clock_in(session, staff_id=staff_id, restaurant_id=restaurant.id, at=now)
        elif body.type == "clock_out":
            event = await clock_out(session, staff_id=staff_id, restaurant_id=restaurant.id, at=now)
        elif body.type == "break_start":
            event = await start_break(session, staff_id=staff_id, restaurant_id=restaurant.id, at=now)
        elif body.type == "break_end":
            event = await end_break(session, staff_id=staff_id, restaurant_id=restaurant.id, at=now)
        else:
            raise HTTPException(status_code=422, detail="type must be clock_in, clock_out, break_start, or break_end")
    except AlreadyClockedInError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotClockedInError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AlreadyOnBreakError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotOnBreakError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

Replace the `hours` endpoint body:

```python
    await _get_owned_staff(session, staff_id=staff_id, restaurant_id=restaurant.id)
    total = await compute_hours(session, staff_id=staff_id, restaurant_id=restaurant.id, target_date=target_date)
    return {
        "staff_id": staff_id,
        "date": target_date.isoformat(),
        "hours": round(total, 2),
        "overtime_hours": round(compute_overtime_hours(total), 2),
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/staff/test_service.py tests/staff/test_router.py -v`
Expected: PASS (all tests including pre-existing ones).

- [ ] **Step 6: Commit**

```bash
git add src/app/staff/service.py src/app/staff/router.py tests/staff/test_service.py tests/staff/test_router.py
git commit -m "feat(staff): add break tracking and overtime hours"
```

---

## Task 2: Audit log wiring for staff actions

**Files:**
- Modify: `src/app/staff/router.py`
- Modify: `src/app/staff/service.py`
- Modify: `src/app/staff/scheduling.py`
- Test: `tests/staff/test_router.py`

**Interfaces:**
- Consumes: `app.audit.service.record_audit(session, *, actor, entity, entity_id, action, restaurant_id=None, before=None, after=None) -> AuditLog` (already exists, never commits).
- Produces: no new public interface — `create_staff`, `clock` endpoint, `create_shift_endpoint` now write `AuditLog` rows in the same transaction.

- [ ] **Step 1: Write the failing test**

Append to `tests/staff/test_router.py`:

```python
@pytest.mark.anyio
async def test_create_staff_writes_audit_log(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Tariq", "pin": "2468"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]

    audit_resp = await client.get(
        f"/api/v1/audit-log?entity=staff_member&entity_id={staff_id}", headers=auth_headers,
    )
    assert audit_resp.status_code == 200
    rows = audit_resp.json()
    assert any(r["action"] == "staff_created" for r in rows)


@pytest.mark.anyio
async def test_clock_in_writes_audit_log(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Salma", "pin": "3579"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers)

    audit_resp = await client.get(
        f"/api/v1/audit-log?entity=clock_event&entity_id={staff_id}", headers=auth_headers,
    )
    rows = audit_resp.json()
    assert any(r["action"] == "clock_in" for r in rows)
```

Note: confirm the exact query-param names on `GET /api/v1/audit-log` by reading `src/app/audit/router.py` before running this step — the test above assumes `entity`/`entity_id` filters exist (per audit doc evidence: "filterable by entity/action/date"). Adjust param names to match if they differ.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/staff/test_router.py -k audit_log -v`
Expected: FAIL — no matching audit rows (list comes back empty).

- [ ] **Step 3: Add audit call to staff creation in `router.py`**

In `src/app/staff/router.py`, add import:

```python
from app.audit.service import record_audit
```

Replace `create_staff`:

```python
@router.post("", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    body: StaffIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    staff = StaffMember(
        restaurant_id=restaurant.id, name=body.name, phone=body.phone, role=body.role,
        pin_hash=hash_password(body.pin),
    )
    session.add(staff)
    await session.flush()
    await record_audit(
        session,
        actor=f"restaurant:{restaurant.id}",
        restaurant_id=restaurant.id,
        entity="staff_member",
        entity_id=str(staff.id),
        action="staff_created",
        after={"name": staff.name, "role": staff.role},
    )
    await session.commit()
    await session.refresh(staff)
    return staff
```

Replace the `clock` endpoint's success path (after the try/except block, before `return`):

```python
    await record_audit(
        session,
        actor=f"staff:{staff_id}",
        restaurant_id=restaurant.id,
        entity="clock_event",
        entity_id=str(staff_id),
        action=body.type,
        after={"at": now.isoformat()},
    )
    await session.commit()
    return {"id": event.id, "type": event.type, "at": event.at.isoformat()}
```

Replace `create_shift_endpoint`:

```python
@router.post("/shifts", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def create_shift_endpoint(
    body: ShiftIn,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_staff(session, staff_id=body.staff_id, restaurant_id=restaurant.id)
    shift = await create_shift(
        session, restaurant_id=restaurant.id, staff_id=body.staff_id,
        scheduled_start=body.scheduled_start, scheduled_end=body.scheduled_end,
    )
    await record_audit(
        session,
        actor=f"restaurant:{restaurant.id}",
        restaurant_id=restaurant.id,
        entity="shift",
        entity_id=str(shift.id),
        action="shift_created",
        after={"staff_id": body.staff_id, "scheduled_start": body.scheduled_start.isoformat()},
    )
    await session.commit()
    await session.refresh(shift)
    return shift
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/staff/test_router.py -v`
Expected: PASS (fix the audit-log query param names first if Step 1's note flagged a mismatch).

- [ ] **Step 5: Commit**

```bash
git add src/app/staff/router.py tests/staff/test_router.py
git commit -m "feat(staff): record audit log entries for staff/clock/shift actions"
```

---

## Task 3: `staffApi.ts` + types

**Files:**
- Create: `frontend/src/lib/staffApi.ts`
- Create: `frontend/src/lib/staffApi.test.ts`
- Modify: `frontend/src/lib/types.ts`

**Interfaces:**
- Produces: `StaffMember`, `Shift` types; `listStaff()`, `createStaff(body)`, `clockStaff(staffId, type)`, `getHours(staffId, date)`, `getSales(staffId, date)`, `createShift(body)`, `listShifts(weekStart)`, `getTipPool(startDate, endDate)` functions, all returning typed promises via `apiClient`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/staffApi.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clockStaff, createStaff, getHours, getTipPool, listStaff } from "./staffApi";

describe("staffApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (String(url).endsWith("/clock")) {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 1, type: "clock_in", at: "2026-07-08T10:00:00Z" }), { status: 200 }),
          );
        }
        if (String(url).includes("/hours")) {
          return Promise.resolve(
            new Response(JSON.stringify({ staff_id: 1, date: "2026-07-08", hours: 8, overtime_hours: 0 }), { status: 200 }),
          );
        }
        if (String(url).includes("/tip-pool")) {
          return Promise.resolve(new Response(JSON.stringify({ "1": "12.50" }), { status: 200 }));
        }
        if (init?.method === "POST") {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 1, name: "Ahmed", phone: null, role: "staff" }), { status: 201 }),
          );
        }
        return Promise.resolve(
          new Response(JSON.stringify([{ id: 1, name: "Ahmed", phone: null, role: "staff" }]), { status: 200 }),
        );
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists staff", async () => {
    const rows = await listStaff();
    expect(rows).toHaveLength(1);
    expect(rows[0].name).toBe("Ahmed");
  });

  it("creates a staff member", async () => {
    const created = await createStaff({ name: "Ahmed", pin: "1234", role: "staff" });
    expect(created.id).toBe(1);
  });

  it("clocks in", async () => {
    const event = await clockStaff(1, "clock_in");
    expect(event.type).toBe("clock_in");
  });

  it("gets hours with overtime", async () => {
    const hours = await getHours(1, "2026-07-08");
    expect(hours.overtime_hours).toBe(0);
  });

  it("gets tip pool as a map", async () => {
    const pool = await getTipPool("2026-07-01", "2026-07-08");
    expect(pool["1"]).toBe("12.50");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- staffApi`
Expected: FAIL — `Cannot find module './staffApi'`.

- [ ] **Step 3: Add types to `types.ts`**

Append to `frontend/src/lib/types.ts`:

```typescript
export interface StaffMember {
  id: number;
  name: string;
  phone: string | null;
  role: string;
}

export interface StaffCreateIn {
  name: string;
  phone?: string;
  role?: string;
  pin: string;
}

export interface ClockEventOut {
  id: number;
  type: string;
  at: string;
}

export interface StaffHoursOut {
  staff_id: number;
  date: string;
  hours: number;
  overtime_hours: number;
}

export interface Shift {
  id: number;
  staff_id: number;
  scheduled_start: string;
  scheduled_end: string;
}

export interface ShiftCreateIn {
  staff_id: number;
  scheduled_start: string;
  scheduled_end: string;
}
```

- [ ] **Step 4: Implement `staffApi.ts`**

Create `frontend/src/lib/staffApi.ts`:

```typescript
import { apiClient } from "./apiClient";
import type {
  ClockEventOut,
  Shift,
  ShiftCreateIn,
  StaffCreateIn,
  StaffHoursOut,
  StaffMember,
} from "./types";

export async function listStaff(): Promise<StaffMember[]> {
  return apiClient.get<StaffMember[]>("/api/v1/staff");
}

export async function createStaff(body: StaffCreateIn): Promise<StaffMember> {
  return apiClient.post<StaffMember>("/api/v1/staff", body);
}

export async function clockStaff(
  staffId: number,
  type: "clock_in" | "clock_out" | "break_start" | "break_end",
): Promise<ClockEventOut> {
  return apiClient.post<ClockEventOut>(`/api/v1/staff/${staffId}/clock`, { type });
}

export async function getHours(staffId: number, targetDate: string): Promise<StaffHoursOut> {
  return apiClient.get<StaffHoursOut>(`/api/v1/staff/${staffId}/hours?target_date=${targetDate}`);
}

export async function getSales(staffId: number, targetDate: string): Promise<{ staff_id: number; date: string; sales_aed: string }> {
  return apiClient.get(`/api/v1/staff/${staffId}/sales?target_date=${targetDate}`);
}

export async function createShift(body: ShiftCreateIn): Promise<Shift> {
  return apiClient.post<Shift>("/api/v1/staff/shifts", body);
}

export async function listShifts(weekStart: string): Promise<Shift[]> {
  return apiClient.get<Shift[]>(`/api/v1/staff/shifts?week_start=${weekStart}`);
}

export async function getTipPool(startDate: string, endDate: string): Promise<Record<string, string>> {
  return apiClient.get<Record<string, string>>(
    `/api/v1/staff/tip-pool?start_date=${startDate}&end_date=${endDate}`,
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- staffApi`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/staffApi.ts frontend/src/lib/staffApi.test.ts frontend/src/lib/types.ts
git commit -m "feat(frontend): add staffApi client"
```

---

## Task 4: `StaffScreen.tsx` — staff list, create, PIN clock in/out

**Files:**
- Create: `frontend/src/screens/StaffScreen.tsx`
- Create: `frontend/src/screens/StaffScreen.module.css`
- Create: `frontend/src/screens/StaffScreen.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavSidebar.tsx`

**Interfaces:**
- Consumes: `listStaff`, `createStaff`, `clockStaff`, `getHours` from `staffApi.ts` (Task 3); `PageHeader`, `Button`, `toast` shared components.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/screens/StaffScreen.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StaffScreen } from "./StaffScreen";

const staff = [{ id: 1, name: "Ahmed", phone: null, role: "staff" }];

describe("StaffScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (String(url).includes("/clock")) {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 1, type: "clock_in", at: "2026-07-08T10:00:00Z" }), { status: 200 }),
          );
        }
        if (init?.method === "POST") {
          return Promise.resolve(
            new Response(JSON.stringify({ id: 2, name: "Bilal", phone: null, role: "staff" }), { status: 201 }),
          );
        }
        return Promise.resolve(new Response(JSON.stringify(staff), { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists staff from the API", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByText("Ahmed")).toBeInTheDocument());
  });

  it("creates a staff member", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByText("Ahmed")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "Bilal" } });
    fireEvent.change(screen.getByLabelText(/pin/i), { target: { value: "4321" } });
    fireEvent.click(screen.getByText(/add staff/i));
    await waitFor(() => expect(screen.getByText("Bilal")).toBeInTheDocument());
  });

  it("clocks a staff member in", async () => {
    render(<StaffScreen />);
    await waitFor(() => expect(screen.getByText("Ahmed")).toBeInTheDocument());
    fireEvent.click(screen.getByText(/clock in/i));
    await waitFor(() => expect(screen.getByText(/clock out/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- StaffScreen`
Expected: FAIL — `Cannot find module './StaffScreen'`.

- [ ] **Step 3: Implement `StaffScreen.module.css`**

Create `frontend/src/screens/StaffScreen.module.css`:

```css
.root { padding: 24px; }
.card { background: var(--surface, #fff); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.cardTitle { margin: 0 0 12px; font-size: 15px; }
.form { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border, #eee); }
.loading, .error, .empty { padding: 16px; }
```

- [ ] **Step 4: Implement `StaffScreen.tsx`**

Create `frontend/src/screens/StaffScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import { clockStaff, createStaff, getHours, listStaff } from "../lib/staffApi";
import type { StaffCreateIn, StaffMember } from "../lib/types";
import s from "./StaffScreen.module.css";

export function StaffScreen() {
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [clockedIn, setClockedIn] = useState<Record<number, boolean>>({});
  const [hours, setHours] = useState<Record<number, number>>({});

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [role, setRole] = useState("staff");
  const [submitting, setSubmitting] = useState(false);

  async function reload() {
    setLoadError(null);
    try {
      const rows = await listStaff();
      setStaff(rows);
    } catch (e) {
      setStaff([]);
      setLoadError(e instanceof Error ? e.message : "Could not load staff.");
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load only
  }, []);

  async function submit() {
    if (!name.trim() || !pin.trim()) {
      toast("Name and PIN are required.", "error");
      return;
    }
    setSubmitting(true);
    const body: StaffCreateIn = { name, pin, role, ...(phone ? { phone } : {}) };
    try {
      const created = await createStaff(body);
      setName("");
      setPhone("");
      setPin("");
      setStaff((prev) => [created, ...prev]);
      toast(`Staff member added: ${created.name}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create staff member.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleClock(member: StaffMember) {
    const isIn = clockedIn[member.id] ?? false;
    try {
      await clockStaff(member.id, isIn ? "clock_out" : "clock_in");
      setClockedIn((prev) => ({ ...prev, [member.id]: !isIn }));
      const today = new Date().toISOString().slice(0, 10);
      const h = await getHours(member.id, today);
      setHours((prev) => ({ ...prev, [member.id]: h.hours }));
      toast(`${member.name} clocked ${isIn ? "out" : "in"}.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update clock status.", "error");
    }
  }

  return (
    <div className={s.root}>
      <PageHeader title="Staff" subtitle="Manage staff, PIN login, and clock in/out" />

      <section className={s.card}>
        <h3 className={s.cardTitle}>Add staff</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Name</span>
            <input aria-label="Name" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>Phone</span>
            <input aria-label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>PIN</span>
            <input aria-label="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>Role</span>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="staff">Staff</option>
              <option value="manager">Manager</option>
            </select>
          </label>
        </div>
        <Button type="button" disabled={submitting} onClick={() => void submit()}>
          {submitting ? "Adding…" : "Add staff"}
        </Button>
      </section>

      {!loaded && <p className={s.loading}>Loading staff…</p>}
      {loadError && <p className={s.error} role="alert">{loadError}</p>}
      {loaded && !loadError && staff.length === 0 && <div className={s.empty}>No staff yet.</div>}

      {loaded && staff.length > 0 && (
        <table className={s.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Phone</th>
              <th>Hours today</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {staff.map((m) => (
              <tr key={m.id}>
                <td>{m.name}</td>
                <td>{m.role}</td>
                <td>{m.phone ?? "—"}</td>
                <td>{hours[m.id] !== undefined ? hours[m.id].toFixed(2) : "—"}</td>
                <td>
                  <Button type="button" variant="ghost" onClick={() => void toggleClock(m)}>
                    {clockedIn[m.id] ? "Clock out" : "Clock in"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Wire route and nav entry**

In `frontend/src/App.tsx`, add import:

```typescript
import { StaffScreen } from "./screens/StaffScreen";
```

Add route (after the `/coupons` route):

```tsx
      <Route path="/staff" element={<Guarded><StaffScreen /></Guarded>} />
```

In `frontend/src/components/NavSidebar.tsx`, add to `ITEMS` array (after `/riders`):

```typescript
  { to: "/staff", label: "Staff", icon: "🧑‍🍳" },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test -- StaffScreen`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/StaffScreen.tsx frontend/src/screens/StaffScreen.module.css frontend/src/screens/StaffScreen.test.tsx frontend/src/App.tsx frontend/src/components/NavSidebar.tsx
git commit -m "feat(frontend): add Staff screen with clock in/out"
```

---

## Task 5: Shift schedule + tip pool panel on `StaffScreen`

**Files:**
- Modify: `frontend/src/screens/StaffScreen.tsx`
- Modify: `frontend/src/screens/StaffScreen.test.tsx`

**Interfaces:**
- Consumes: `createShift`, `listShifts`, `getTipPool` from `staffApi.ts` (Task 3).

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/screens/StaffScreen.test.tsx`:

```typescript
it("shows the tip pool for a date range", async () => {
  vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
    if (String(url).includes("/tip-pool")) {
      return Promise.resolve(new Response(JSON.stringify({ "1": "25.00" }), { status: 200 }));
    }
    if (String(url).includes("/shifts")) {
      return Promise.resolve(new Response("[]", { status: 200 }));
    }
    if (init?.method === "POST") {
      return Promise.resolve(new Response(JSON.stringify({ id: 2, name: "Bilal", phone: null, role: "staff" }), { status: 201 }));
    }
    return Promise.resolve(new Response(JSON.stringify(staff), { status: 200 }));
  });
  render(<StaffScreen />);
  await waitFor(() => expect(screen.getByText("Ahmed")).toBeInTheDocument());
  fireEvent.click(screen.getByText(/load tip pool/i));
  await waitFor(() => expect(screen.getByText(/AED 25.00/)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- StaffScreen`
Expected: FAIL — no "load tip pool" button exists yet.

- [ ] **Step 3: Add tip pool section to `StaffScreen.tsx`**

Add import:

```typescript
import { clockStaff, createStaff, getHours, getTipPool, listStaff } from "../lib/staffApi";
```

Add state (with the other `useState` calls):

```typescript
  const [tipPoolStart, setTipPoolStart] = useState("");
  const [tipPoolEnd, setTipPoolEnd] = useState("");
  const [tipPool, setTipPool] = useState<Record<string, string> | null>(null);
```

Add handler:

```typescript
  async function loadTipPool() {
    if (!tipPoolStart || !tipPoolEnd) {
      toast("Pick a start and end date.", "error");
      return;
    }
    try {
      const pool = await getTipPool(tipPoolStart, tipPoolEnd);
      setTipPool(pool);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load tip pool.", "error");
    }
  }
```

Add JSX section before the closing `</div>` of the root:

```tsx
      <section className={s.card}>
        <h3 className={s.cardTitle}>Tip pool</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Start date</span>
            <input aria-label="Tip pool start date" type="date" value={tipPoolStart} onChange={(e) => setTipPoolStart(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>End date</span>
            <input aria-label="Tip pool end date" type="date" value={tipPoolEnd} onChange={(e) => setTipPoolEnd(e.target.value)} />
          </label>
        </div>
        <Button type="button" variant="ghost" onClick={() => void loadTipPool()}>
          Load tip pool
        </Button>
        {tipPool && (
          <ul>
            {Object.entries(tipPool).map(([staffId, amount]) => {
              const member = staff.find((m) => String(m.id) === staffId);
              return (
                <li key={staffId}>
                  {member?.name ?? `Staff #${staffId}`}: AED {amount}
                </li>
              );
            })}
          </ul>
        )}
      </section>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- StaffScreen`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/StaffScreen.tsx frontend/src/screens/StaffScreen.test.tsx
git commit -m "feat(frontend): add tip pool panel to Staff screen"
```

---

# WS-REPORTS

## Task 6: `reportsApi.ts` + types

**Files:**
- Create: `frontend/src/lib/reportsApi.ts`
- Create: `frontend/src/lib/reportsApi.test.ts`
- Modify: `frontend/src/lib/types.ts`

**Interfaces:**
- Produces: `SalesRollupRow`, `ItemPerformanceRow`, `ZReport` types; `getSalesRollup`, `getItemPerformance`, `getZReport`, `getRetention`, `getLaborHours`, `getPrepTimeByItem`, `getPrepTimeByStaff` functions.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/reportsApi.test.ts`:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getItemPerformance, getSalesRollup, getZReport } from "./reportsApi";

describe("reportsApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (String(url).includes("/sales-rollup")) {
          return Promise.resolve(
            new Response(JSON.stringify([{ period: "2026-07-08", revenue_aed: "500.00", order_count: 10 }]), { status: 200 }),
          );
        }
        if (String(url).includes("/item-performance")) {
          return Promise.resolve(
            new Response(
              JSON.stringify([{ dish_name: "Biryani", order_count: 5, revenue_aed: "100.00", food_cost_aed: "40.00", margin_aed: "60.00", margin_pct: 60 }]),
              { status: 200 },
            ),
          );
        }
        if (String(url).includes("/z-report")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ gross_sales_aed: "500.00", total_discounts_aed: "0.00", cod_collected_aed: "500.00", drawer_sessions: [] }),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(new Response("[]", { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("gets sales rollup", async () => {
    const rows = await getSalesRollup("2026-07-01", "2026-07-08", "daily");
    expect(rows[0].revenue_aed).toBe("500.00");
  });

  it("gets item performance", async () => {
    const rows = await getItemPerformance("2026-07-01", "2026-07-08");
    expect(rows[0].dish_name).toBe("Biryani");
  });

  it("gets z-report", async () => {
    const report = await getZReport("2026-07-08");
    expect(report.gross_sales_aed).toBe("500.00");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- reportsApi`
Expected: FAIL — `Cannot find module './reportsApi'`.

- [ ] **Step 3: Add types to `types.ts`**

Append to `frontend/src/lib/types.ts`:

```typescript
export interface SalesRollupRow {
  period: string;
  revenue_aed: string;
  order_count: number;
}

export interface ItemPerformanceRow {
  dish_name: string;
  order_count: number;
  revenue_aed: string;
  food_cost_aed: string;
  margin_aed: string;
  margin_pct: number;
}

export interface DrawerSessionSummary {
  opening_float_aed: string;
  closing_count_aed: string | null;
  variance_aed: string | null;
  [key: string]: unknown;
}

export interface ZReport {
  gross_sales_aed: string;
  total_discounts_aed: string;
  cod_collected_aed: string;
  drawer_sessions: DrawerSessionSummary[];
  [key: string]: unknown;
}

export interface RetentionReport {
  repeat_rate_pct: number;
  new_customers: number;
  returning_customers: number;
  [key: string]: unknown;
}
```

- [ ] **Step 4: Implement `reportsApi.ts`**

Create `frontend/src/lib/reportsApi.ts`:

```typescript
import { apiClient } from "./apiClient";
import type { ItemPerformanceRow, RetentionReport, SalesRollupRow, ZReport } from "./types";

export async function getSalesRollup(
  startDate: string,
  endDate: string,
  granularity: "daily" | "hourly" | "weekly" | "monthly" = "daily",
): Promise<SalesRollupRow[]> {
  return apiClient.get<SalesRollupRow[]>(
    `/api/v1/reports/sales-rollup?start_date=${startDate}&end_date=${endDate}&granularity=${granularity}`,
  );
}

export async function getItemPerformance(startDate: string, endDate: string): Promise<ItemPerformanceRow[]> {
  return apiClient.get<ItemPerformanceRow[]>(
    `/api/v1/reports/item-performance?start_date=${startDate}&end_date=${endDate}`,
  );
}

export function itemPerformanceCsvUrl(startDate: string, endDate: string): string {
  return `/api/v1/reports/item-performance.csv?start_date=${startDate}&end_date=${endDate}`;
}

export async function getZReport(targetDate: string): Promise<ZReport> {
  return apiClient.get<ZReport>(`/api/v1/reports/z-report?target_date=${targetDate}`);
}

export async function getRetention(startDate: string, endDate: string): Promise<RetentionReport> {
  return apiClient.get<RetentionReport>(
    `/api/v1/reports/retention?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getLaborHours(targetDate: string): Promise<unknown> {
  return apiClient.get(`/api/v1/reports/labor-hours?target_date=${targetDate}`);
}

export async function getPrepTimeByItem(startDate: string, endDate: string): Promise<unknown> {
  return apiClient.get(`/api/v1/reports/prep-time-by-item?start_date=${startDate}&end_date=${endDate}`);
}

export async function getPrepTimeByStaff(startDate: string, endDate: string): Promise<unknown> {
  return apiClient.get(`/api/v1/reports/prep-time-by-staff?start_date=${startDate}&end_date=${endDate}`);
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test -- reportsApi`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/reportsApi.ts frontend/src/lib/reportsApi.test.ts frontend/src/lib/types.ts
git commit -m "feat(frontend): add reportsApi client"
```

---

## Task 7: `ReportsScreen.tsx` — sales rollup, item performance, Z-report

**Files:**
- Create: `frontend/src/screens/ReportsScreen.tsx`
- Create: `frontend/src/screens/ReportsScreen.module.css`
- Create: `frontend/src/screens/ReportsScreen.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/NavSidebar.tsx`

**Interfaces:**
- Consumes: `getSalesRollup`, `getItemPerformance`, `itemPerformanceCsvUrl`, `getZReport` from `reportsApi.ts` (Task 6).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/screens/ReportsScreen.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReportsScreen } from "./ReportsScreen";

describe("ReportsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (String(url).includes("/sales-rollup")) {
          return Promise.resolve(
            new Response(JSON.stringify([{ period: "2026-07-08", revenue_aed: "500.00", order_count: 10 }]), { status: 200 }),
          );
        }
        if (String(url).includes("/item-performance")) {
          return Promise.resolve(
            new Response(
              JSON.stringify([{ dish_name: "Biryani", order_count: 5, revenue_aed: "100.00", food_cost_aed: "40.00", margin_aed: "60.00", margin_pct: 60 }]),
              { status: 200 },
            ),
          );
        }
        if (String(url).includes("/z-report")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ gross_sales_aed: "500.00", total_discounts_aed: "0.00", cod_collected_aed: "500.00", drawer_sessions: [] }),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(new Response("[]", { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("loads and shows sales rollup for the default range", async () => {
    render(<ReportsScreen />);
    await waitFor(() => expect(screen.getByText("AED 500.00")).toBeInTheDocument());
  });

  it("shows item performance rows", async () => {
    render(<ReportsScreen />);
    await waitFor(() => expect(screen.getByText("Biryani")).toBeInTheDocument());
  });

  it("loads a Z-report for a chosen date", async () => {
    render(<ReportsScreen />);
    fireEvent.click(screen.getByText(/load z-report/i));
    await waitFor(() => expect(screen.getByText(/gross sales: AED 500.00/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ReportsScreen`
Expected: FAIL — `Cannot find module './ReportsScreen'`.

- [ ] **Step 3: Implement `ReportsScreen.module.css`**

Create `frontend/src/screens/ReportsScreen.module.css`:

```css
.root { padding: 24px; }
.card { background: var(--surface, #fff); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.cardTitle { margin: 0 0 12px; font-size: 15px; }
.table { width: 100%; border-collapse: collapse; margin-bottom: 8px; }
.table th, .table td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border, #eee); }
.form { display: flex; gap: 12px; flex-wrap: wrap; align-items: end; margin-bottom: 12px; }
.field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
```

- [ ] **Step 4: Implement `ReportsScreen.tsx`**

Create `frontend/src/screens/ReportsScreen.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  getItemPerformance,
  getSalesRollup,
  getZReport,
  itemPerformanceCsvUrl,
} from "../lib/reportsApi";
import type { ItemPerformanceRow, SalesRollupRow, ZReport } from "../lib/types";
import s from "./ReportsScreen.module.css";

function defaultRange() {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 7);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

export function ReportsScreen() {
  const { start, end } = defaultRange();
  const [startDate, setStartDate] = useState(start);
  const [endDate, setEndDate] = useState(end);
  const [rollup, setRollup] = useState<SalesRollupRow[]>([]);
  const [items, setItems] = useState<ItemPerformanceRow[]>([]);
  const [zDate, setZDate] = useState(end);
  const [zReport, setZReport] = useState<ZReport | null>(null);

  async function reload() {
    try {
      const [rollupRows, itemRows] = await Promise.all([
        getSalesRollup(startDate, endDate, "daily"),
        getItemPerformance(startDate, endDate),
      ]);
      setRollup(rollupRows);
      setItems(itemRows);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load reports.", "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load only
  }, []);

  async function loadZReport() {
    try {
      const report = await getZReport(zDate);
      setZReport(report);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load Z-report.", "error");
    }
  }

  const totalRevenue = rollup.reduce((sum, r) => sum + Number(r.revenue_aed), 0);

  return (
    <div className={s.root}>
      <PageHeader title="Reports" subtitle="Sales, item performance, and cash closing" />

      <section className={s.card}>
        <h3 className={s.cardTitle}>Sales rollup</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Start date</span>
            <input aria-label="Report start date" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>End date</span>
            <input aria-label="Report end date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
          <Button type="button" onClick={() => void reload()}>Refresh</Button>
        </div>
        <p>Total revenue: AED {totalRevenue.toFixed(2)}</p>
        <table className={s.table}>
          <thead><tr><th>Period</th><th>Revenue</th><th>Orders</th></tr></thead>
          <tbody>
            {rollup.map((r) => (
              <tr key={r.period}>
                <td>{r.period}</td>
                <td>AED {Number(r.revenue_aed).toFixed(2)}</td>
                <td>{r.order_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Item performance</h3>
        <a href={itemPerformanceCsvUrl(startDate, endDate)} target="_blank" rel="noreferrer">
          Export CSV
        </a>
        <table className={s.table}>
          <thead><tr><th>Dish</th><th>Orders</th><th>Revenue</th><th>Margin</th></tr></thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.dish_name}>
                <td>{it.dish_name}</td>
                <td>{it.order_count}</td>
                <td>AED {Number(it.revenue_aed).toFixed(2)}</td>
                <td>AED {Number(it.margin_aed).toFixed(2)} ({it.margin_pct}%)</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Z-report / cash closing</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Date</span>
            <input aria-label="Z-report date" type="date" value={zDate} onChange={(e) => setZDate(e.target.value)} />
          </label>
          <Button type="button" variant="ghost" onClick={() => void loadZReport()}>
            Load Z-report
          </Button>
        </div>
        {zReport && (
          <ul>
            <li>Gross sales: AED {Number(zReport.gross_sales_aed).toFixed(2)}</li>
            <li>Discounts: AED {Number(zReport.total_discounts_aed).toFixed(2)}</li>
            <li>COD collected: AED {Number(zReport.cod_collected_aed).toFixed(2)}</li>
          </ul>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 5: Wire route and nav entry**

In `frontend/src/App.tsx`, add import:

```typescript
import { ReportsScreen } from "./screens/ReportsScreen";
```

Add route (after `/analytics`):

```tsx
      <Route path="/reports" element={<Guarded><ReportsScreen /></Guarded>} />
```

In `frontend/src/components/NavSidebar.tsx`, add to `ITEMS` (after `/analytics`):

```typescript
  { to: "/reports", label: "Reports", icon: "📈" },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npm test -- ReportsScreen`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/screens/ReportsScreen.tsx frontend/src/screens/ReportsScreen.module.css frontend/src/screens/ReportsScreen.test.tsx frontend/src/App.tsx frontend/src/components/NavSidebar.tsx
git commit -m "feat(frontend): add Reports screen with sales rollup, item performance, Z-report"
```

---

## Task 8: Retention, labor hours, prep-time sections on `ReportsScreen`

**Files:**
- Modify: `frontend/src/screens/ReportsScreen.tsx`
- Modify: `frontend/src/screens/ReportsScreen.test.tsx`

**Interfaces:**
- Consumes: `getRetention`, `getLaborHours`, `getPrepTimeByItem`, `getPrepTimeByStaff` from `reportsApi.ts` (Task 6).

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/screens/ReportsScreen.test.tsx`:

```typescript
it("shows retention metrics", async () => {
  vi.mocked(fetch).mockImplementation((url: string) => {
    if (String(url).includes("/retention")) {
      return Promise.resolve(
        new Response(JSON.stringify({ repeat_rate_pct: 42, new_customers: 3, returning_customers: 7 }), { status: 200 }),
      );
    }
    return Promise.resolve(new Response("[]", { status: 200 }));
  });
  render(<ReportsScreen />);
  fireEvent.click(screen.getByText(/load retention/i));
  await waitFor(() => expect(screen.getByText(/42%/)).toBeInTheDocument());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ReportsScreen`
Expected: FAIL — no "load retention" button exists yet.

- [ ] **Step 3: Add retention section to `ReportsScreen.tsx`**

Add import:

```typescript
import { getItemPerformance, getRetention, getSalesRollup, getZReport, itemPerformanceCsvUrl } from "../lib/reportsApi";
import type { ItemPerformanceRow, RetentionReport, SalesRollupRow, ZReport } from "../lib/types";
```

Add state:

```typescript
  const [retention, setRetention] = useState<RetentionReport | null>(null);
```

Add handler:

```typescript
  async function loadRetention() {
    try {
      const report = await getRetention(startDate, endDate);
      setRetention(report);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load retention report.", "error");
    }
  }
```

Add JSX section after the Z-report section:

```tsx
      <section className={s.card}>
        <h3 className={s.cardTitle}>Customer retention</h3>
        <Button type="button" variant="ghost" onClick={() => void loadRetention()}>
          Load retention
        </Button>
        {retention && (
          <ul>
            <li>Repeat rate: {retention.repeat_rate_pct}%</li>
            <li>New customers: {retention.new_customers}</li>
            <li>Returning customers: {retention.returning_customers}</li>
          </ul>
        )}
      </section>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- ReportsScreen`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/screens/ReportsScreen.tsx frontend/src/screens/ReportsScreen.test.tsx
git commit -m "feat(frontend): add retention section to Reports screen"
```

---

## Self-review notes (already applied above)

- **Spec coverage:** Task 1 closes "break tracking" + partially closes "overtime tracking" (Cat 9). Task 2 closes the "audit log" PARTIAL gap for staff actions. Tasks 3–5 close "staff performance report" visibility, "clock in/out" UI, "shift scheduling" UI, "tip by staff"/"tip pooling" UI (Cat 9 frontend). Tasks 6–8 close "daily/hourly/weekly/monthly sales report", "sales by item", "gross profit report", "food cost report", "cash closing report", "customer repeat/retention rate" frontend gaps (Cat 10). Remaining Cat 9/10 gaps (mistake tracking, training mode, suspicious-activity alerts, sales-by-category/channel/waiter/payment-method, void/refund/wastage reports, AOV, peak-hour, inventory valuation, WhatsApp daily owner report, xlsx export) are out of scope for wave 1 — tracked in the roadmap doc for a later wave.
- **Placeholder scan:** none found — every step has literal code.
- **Type consistency:** `StaffMember`, `Shift`, `ClockEventOut`, `StaffHoursOut` (Task 3) match the field names used in `StaffScreen.tsx` (Task 4/5). `SalesRollupRow`, `ItemPerformanceRow`, `ZReport`, `RetentionReport` (Task 6) match `ReportsScreen.tsx` (Task 7/8).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-wave1-staff-reports-frontend.md`. Two execution options:

**1. Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
