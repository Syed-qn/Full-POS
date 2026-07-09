import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  acknowledgeAlert,
  clockStaff,
  closeShift,
  createShift,
  createStaff,
  fetchAlerts,
  fetchAttendance,
  fetchPerformance,
  getClockStatus,
  getHours,
  getTipPool,
  getTipsByStaff,
  listApprovals,
  listMistakes,
  listShifts,
  listStaff,
  openShift,
  recordMistake,
  setTrainingMode,
  staffLogin,
  submitManagerPin,
} from "../lib/staffApi";
import type { Shift, ShiftCreateIn, StaffCreateIn, StaffMember } from "../lib/types";
import s from "./StaffScreen.module.css";

function todayYMD() {
  return new Date().toISOString().slice(0, 10);
}

export function StaffScreen() {
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [clockStatuses, setClockStatuses] = useState<Record<number, "clocked_out" | "clocked_in" | "on_break">>({});
  const [hours, setHours] = useState<Record<number, number>>({});

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [role, setRole] = useState("staff");
  const [submitting, setSubmitting] = useState(false);

  const [loginStaffId, setLoginStaffId] = useState("");
  const [loginPin, setLoginPin] = useState("");
  const [loginResult, setLoginResult] = useState<string | null>(null);

  const [tipPoolStart, setTipPoolStart] = useState("");
  const [tipPoolEnd, setTipPoolEnd] = useState("");
  const [tipPool, setTipPool] = useState<Record<string, string> | null>(null);
  const [tipsByStaff, setTipsByStaff] = useState<Record<string, string> | null>(null);

  const [shiftStaffId, setShiftStaffId] = useState("");
  const [shiftStart, setShiftStart] = useState("");
  const [shiftEnd, setShiftEnd] = useState("");
  const [creatingShift, setCreatingShift] = useState(false);
  const [weekStart, setWeekStart] = useState("");
  const [shifts, setShifts] = useState<Shift[] | null>(null);

  const [mgrPin, setMgrPin] = useState("");
  const [mgrAction, setMgrAction] = useState("discount");
  const [approvals, setApprovals] = useState<Array<{ id: number; action_type: string; status: string; amount_aed?: string | null }>>([]);

  const [mistakeStaffId, setMistakeStaffId] = useState("");
  const [mistakeType, setMistakeType] = useState("wrong_item");
  const [mistakeAmt, setMistakeAmt] = useState("0");
  const [mistakes, setMistakes] = useState<Array<{ id: number; staff_id: number; mistake_type: string; amount_aed: string }>>([]);

  const [attendanceDate, setAttendanceDate] = useState(todayYMD());
  const [attendance, setAttendance] = useState<Array<Record<string, unknown>> | null>(null);
  const [perfStart, setPerfStart] = useState(todayYMD());
  const [perfEnd, setPerfEnd] = useState(todayYMD());
  const [performance, setPerformance] = useState<Array<Record<string, unknown>> | null>(null);
  const [alerts, setAlerts] = useState<Array<{ id: number; alert_type: string; severity: string; acknowledged: boolean }>>([]);

  async function loadClockStatuses(members: StaffMember[]) {
    const results = await Promise.all(
      members.map(async (m) => {
        try {
          const { status: clockStatus } = await getClockStatus(m.id);
          const normalized =
            clockStatus === "clocked_in" || clockStatus === "on_break" ? clockStatus : "clocked_out";
          return [m.id, normalized] as const;
        } catch {
          return [m.id, "clocked_out"] as const;
        }
      }),
    );
    setClockStatuses((prev) => {
      const next = { ...prev };
      for (const [id, status] of results) next[id] = status;
      return next;
    });
  }

  async function reload() {
    setLoadError(null);
    try {
      const rows = await listStaff();
      setStaff(rows);
      void loadClockStatuses(rows);
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
    const status = clockStatuses[member.id] ?? "clocked_out";
    const eventType = status === "clocked_in" ? "clock_out" : status === "on_break" ? "break_end" : "clock_in";
    const nextStatus = eventType === "clock_out" ? "clocked_out" : eventType === "break_end" ? "clocked_in" : "clocked_in";
    try {
      await clockStaff(member.id, eventType);
      setClockStatuses((prev) => ({ ...prev, [member.id]: nextStatus }));
      const today = new Date().toISOString().slice(0, 10);
      const h = await getHours(member.id, today);
      setHours((prev) => ({ ...prev, [member.id]: h.hours }));
      const label = eventType === "clock_out" ? "clocked out" : eventType === "break_end" ? "back from break" : "clocked in";
      toast(`${member.name} ${label}.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update clock status.", "error");
    }
  }

  async function startBreak(member: StaffMember) {
    try {
      await clockStaff(member.id, "break_start");
      setClockStatuses((prev) => ({ ...prev, [member.id]: "on_break" }));
      toast(`${member.name} on break.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not start break.", "error");
    }
  }

  async function toggleTraining(member: StaffMember) {
    try {
      const next = await setTrainingMode(member.id, !member.training_mode);
      setStaff((prev) => prev.map((m) => (m.id === member.id ? next : m)));
      toast(`${member.name} training mode ${next.training_mode ? "ON" : "OFF"}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Training mode failed.", "error");
    }
  }

  async function doLogin() {
    if (!loginStaffId || !loginPin) {
      toast("Staff + PIN required.", "error");
      return;
    }
    try {
      const res = await staffLogin(Number(loginStaffId), loginPin);
      setLoginResult(`${res.name} (${res.role}) — token issued${res.training_mode ? " · training" : ""}`);
      toast("Staff PIN login OK");
    } catch (e) {
      setLoginResult(null);
      toast(e instanceof Error ? e.message : "Login failed", "error");
    }
  }

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
      return;
    }
    try {
      const byStaff = await getTipsByStaff(tipPoolStart, tipPoolEnd);
      // Guard: only map string amounts (ignore malformed payloads)
      if (byStaff && typeof byStaff === "object" && !Array.isArray(byStaff)) {
        setTipsByStaff(byStaff);
      }
    } catch {
      setTipsByStaff(null);
    }
  }

  async function submitShift() {
    if (!shiftStaffId || !shiftStart || !shiftEnd) {
      toast("Staff member, start, and end are required.", "error");
      return;
    }
    setCreatingShift(true);
    const body: ShiftCreateIn = {
      staff_id: Number(shiftStaffId),
      scheduled_start: shiftStart,
      scheduled_end: shiftEnd,
    };
    try {
      await createShift(body);
      setShiftStaffId("");
      setShiftStart("");
      setShiftEnd("");
      toast("Shift created.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create shift.", "error");
    } finally {
      setCreatingShift(false);
    }
  }

  async function loadShifts() {
    if (!weekStart) {
      toast("Pick a week start date.", "error");
      return;
    }
    try {
      const rows = await listShifts(weekStart);
      setShifts(rows);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load shifts.", "error");
    }
  }

  async function doOpenShift(id: number) {
    try {
      const sh = await openShift(id);
      setShifts((prev) => prev?.map((x) => (x.id === id ? sh : x)) ?? null);
      toast("Shift opened + clocked in");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Open shift failed", "error");
    }
  }

  async function doCloseShift(id: number) {
    try {
      const sh = await closeShift(id);
      setShifts((prev) => prev?.map((x) => (x.id === id ? sh : x)) ?? null);
      toast("Shift closed");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Close shift failed", "error");
    }
  }

  async function doManagerPin() {
    if (!mgrPin) {
      toast("Enter manager PIN", "error");
      return;
    }
    try {
      await submitManagerPin({ pin: mgrPin, action_type: mgrAction, amount_aed: "0" });
      toast("Manager PIN approved");
      setMgrPin("");
      const rows = await listApprovals();
      setApprovals(rows);
    } catch (e) {
      toast(e instanceof Error ? e.message : "PIN rejected", "error");
    }
  }

  async function loadApprovals() {
    try {
      setApprovals(await listApprovals());
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load approvals", "error");
    }
  }

  async function submitMistake() {
    if (!mistakeStaffId) {
      toast("Pick staff", "error");
      return;
    }
    try {
      await recordMistake({
        staff_id: Number(mistakeStaffId),
        mistake_type: mistakeType,
        amount_aed: mistakeAmt || "0",
      });
      toast("Mistake recorded");
      setMistakes(await listMistakes());
    } catch (e) {
      toast(e instanceof Error ? e.message : "Mistake failed", "error");
    }
  }

  async function loadAttendance() {
    try {
      const res = await fetchAttendance(attendanceDate);
      setAttendance(res.rows);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Attendance failed", "error");
    }
  }

  async function loadPerformance() {
    try {
      const res = await fetchPerformance(perfStart, perfEnd);
      setPerformance(res.rows);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Performance failed", "error");
    }
  }

  async function loadAlerts() {
    try {
      setAlerts(await fetchAlerts(false));
    } catch (e) {
      toast(e instanceof Error ? e.message : "Alerts failed", "error");
    }
  }

  async function ackAlert(id: number) {
    try {
      await acknowledgeAlert(id);
      setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)));
      toast("Alert acknowledged");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Ack failed", "error");
    }
  }

  return (
    <div className={s.root}>
      <PageHeader title="Staff" subtitle="PIN login, RBAC, time clock, approvals, attendance & performance" />

      <section className={s.card}>
        <h3 className={s.cardTitle}>New staff member</h3>
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
            <input aria-label="New staff PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} />
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

      <section className={s.card}>
        <h3 className={s.cardTitle}>Staff PIN login</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Staff</span>
            <select aria-label="Login staff" value={loginStaffId} onChange={(e) => setLoginStaffId(e.target.value)}>
              <option value="">Select…</option>
              {staff.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </label>
          <label className={s.field}>
            <span>PIN</span>
            <input aria-label="Login PIN" type="password" value={loginPin} onChange={(e) => setLoginPin(e.target.value)} />
          </label>
        </div>
        <Button type="button" onClick={() => void doLogin()}>Login with PIN</Button>
        {loginResult && <p>{loginResult}</p>}
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
              <th>Training</th>
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
                <td>{m.training_mode ? "ON" : "off"}</td>
                <td style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Button type="button" variant="ghost" onClick={() => void toggleClock(m)}>
                    {clockStatuses[m.id] === "clocked_in"
                      ? "Clock out"
                      : clockStatuses[m.id] === "on_break"
                        ? "End break"
                        : "Clock in"}
                  </Button>
                  {clockStatuses[m.id] === "clocked_in" && (
                    <Button type="button" variant="ghost" onClick={() => void startBreak(m)}>
                      Start break
                    </Button>
                  )}
                  <Button type="button" variant="ghost" onClick={() => void toggleTraining(m)}>
                    {m.training_mode ? "Exit training" : "Training mode"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <section className={s.card}>
        <h3 className={s.cardTitle}>Manager approval (PIN)</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Action</span>
            <select value={mgrAction} onChange={(e) => setMgrAction(e.target.value)}>
              <option value="discount">Discount</option>
              <option value="void">Void</option>
              <option value="refund">Refund</option>
              <option value="manager_override">Override</option>
            </select>
          </label>
          <label className={s.field}>
            <span>Manager PIN</span>
            <input type="password" aria-label="Manager PIN" value={mgrPin} onChange={(e) => setMgrPin(e.target.value)} />
          </label>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Button type="button" onClick={() => void doManagerPin()}>Submit PIN approval</Button>
          <Button type="button" variant="ghost" onClick={() => void loadApprovals()}>Load approvals</Button>
        </div>
        {approvals.length > 0 && (
          <ul>
            {approvals.map((a) => (
              <li key={a.id}>#{a.id} {a.action_type} · {a.status} · {a.amount_aed ?? "—"}</li>
            ))}
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Tip pool & tips by staff</h3>
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
          <div>
            <strong>Even pool</strong>
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
          </div>
        )}
        {tipsByStaff && (
          <div>
            <strong>Attributed tips</strong>
            <ul>
              {Object.entries(tipsByStaff).map(([staffId, amount]) => {
                const member = staff.find((m) => String(m.id) === staffId);
                return (
                  <li key={staffId}>
                    {member?.name ?? `Staff #${staffId}`}: AED {amount}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Shift schedule (open / close)</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Staff member</span>
            <select
              aria-label="Shift staff member"
              value={shiftStaffId}
              onChange={(e) => setShiftStaffId(e.target.value)}
            >
              <option value="">Select…</option>
              {staff.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          <label className={s.field}>
            <span>Start</span>
            <input
              aria-label="Shift start"
              type="datetime-local"
              value={shiftStart}
              onChange={(e) => setShiftStart(e.target.value)}
            />
          </label>
          <label className={s.field}>
            <span>End</span>
            <input
              aria-label="Shift end"
              type="datetime-local"
              value={shiftEnd}
              onChange={(e) => setShiftEnd(e.target.value)}
            />
          </label>
        </div>
        <Button type="button" disabled={creatingShift} onClick={() => void submitShift()}>
          {creatingShift ? "Creating…" : "Create shift"}
        </Button>

        <div className={s.form}>
          <label className={s.field}>
            <span>Week start</span>
            <input aria-label="Week start" type="date" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} />
          </label>
        </div>
        <Button type="button" variant="ghost" onClick={() => void loadShifts()}>
          Load shifts
        </Button>
        {shifts && (
          <ul>
            {shifts.map((shift) => {
              const member = staff.find((m) => m.id === shift.staff_id);
              return (
                <li key={shift.id}>
                  {member?.name ?? `Staff #${shift.staff_id}`}: {shift.scheduled_start}–{shift.scheduled_end}
                  {" · "}{shift.status ?? "scheduled"}
                  {" "}
                  {shift.status !== "open" && shift.status !== "closed" && (
                    <Button type="button" variant="ghost" onClick={() => void doOpenShift(shift.id)}>Open</Button>
                  )}
                  {shift.status === "open" && (
                    <Button type="button" variant="ghost" onClick={() => void doCloseShift(shift.id)}>Close</Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Mistake tracking</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Staff</span>
            <select value={mistakeStaffId} onChange={(e) => setMistakeStaffId(e.target.value)}>
              <option value="">Select…</option>
              {staff.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </label>
          <label className={s.field}>
            <span>Type</span>
            <select value={mistakeType} onChange={(e) => setMistakeType(e.target.value)}>
              <option value="wrong_item">Wrong item</option>
              <option value="void">Void</option>
              <option value="spill">Spill</option>
              <option value="comp">Comp</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className={s.field}>
            <span>Amount AED</span>
            <input value={mistakeAmt} onChange={(e) => setMistakeAmt(e.target.value)} />
          </label>
        </div>
        <Button type="button" onClick={() => void submitMistake()}>Record mistake</Button>
        {mistakes.length > 0 && (
          <ul>
            {mistakes.map((m) => (
              <li key={m.id}>#{m.id} staff {m.staff_id} · {m.mistake_type} · AED {m.amount_aed}</li>
            ))}
          </ul>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Attendance (schedule vs actual)</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>Date</span>
            <input type="date" value={attendanceDate} onChange={(e) => setAttendanceDate(e.target.value)} />
          </label>
        </div>
        <Button type="button" variant="ghost" onClick={() => void loadAttendance()}>Load attendance</Button>
        {attendance && (
          <table className={s.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Scheduled</th>
                <th>Worked</th>
                <th>Variance</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {attendance.map((r) => (
                <tr key={String(r.staff_id)}>
                  <td>{String(r.name)}</td>
                  <td>{String(r.scheduled_hours)}</td>
                  <td>{String(r.worked_hours)}</td>
                  <td>{String(r.variance_hours)}</td>
                  <td>{String(r.attendance_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Staff performance report</h3>
        <div className={s.form}>
          <label className={s.field}>
            <span>From</span>
            <input type="date" value={perfStart} onChange={(e) => setPerfStart(e.target.value)} />
          </label>
          <label className={s.field}>
            <span>To</span>
            <input type="date" value={perfEnd} onChange={(e) => setPerfEnd(e.target.value)} />
          </label>
        </div>
        <Button type="button" variant="ghost" onClick={() => void loadPerformance()}>Load performance</Button>
        {performance && (
          <table className={s.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Hours</th>
                <th>OT</th>
                <th>Sales</th>
                <th>Tips</th>
                <th>Mistakes</th>
                <th>AED/hr</th>
              </tr>
            </thead>
            <tbody>
              {performance.map((r) => (
                <tr key={String(r.staff_id)}>
                  <td>{String(r.name)}</td>
                  <td>{String(r.hours)}</td>
                  <td>{String(r.overtime_hours)}</td>
                  <td>{String(r.sales_aed)}</td>
                  <td>{String(r.tips_aed)}</td>
                  <td>{String(r.mistake_count)}</td>
                  <td>{String(r.sales_per_hour_aed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className={s.card}>
        <h3 className={s.cardTitle}>Suspicious activity alerts</h3>
        <Button type="button" variant="ghost" onClick={() => void loadAlerts()}>Load alerts</Button>
        {alerts.length > 0 && (
          <ul>
            {alerts.map((a) => (
              <li key={a.id}>
                [{a.severity}] {a.alert_type}
                {a.acknowledged ? " ✓" : (
                  <Button type="button" variant="ghost" onClick={() => void ackAlert(a.id)}>Ack</Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
