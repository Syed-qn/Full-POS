import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import { clockStaff, createShift, createStaff, getHours, getTipPool, listShifts, listStaff } from "../lib/staffApi";
import type { Shift, ShiftCreateIn, StaffCreateIn, StaffMember } from "../lib/types";
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

  const [tipPoolStart, setTipPoolStart] = useState("");
  const [tipPoolEnd, setTipPoolEnd] = useState("");
  const [tipPool, setTipPool] = useState<Record<string, string> | null>(null);

  const [shiftStaffId, setShiftStaffId] = useState("");
  const [shiftStart, setShiftStart] = useState("");
  const [shiftEnd, setShiftEnd] = useState("");
  const [creatingShift, setCreatingShift] = useState(false);
  const [weekStart, setWeekStart] = useState("");
  const [shifts, setShifts] = useState<Shift[] | null>(null);

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

  return (
    <div className={s.root}>
      <PageHeader title="Staff" subtitle="Manage staff, PIN login, and time clock" />

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

      <section className={s.card}>
        <h3 className={s.cardTitle}>Shift schedule</h3>
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
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
