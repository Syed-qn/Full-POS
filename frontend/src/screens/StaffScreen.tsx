import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  clockStaff,
  createStaff,
  getClockStatus,
  getHours,
  listStaff,
  setTrainingMode,
  staffLogin,
} from "../lib/staffApi";
import type { StaffCreateIn, StaffMember } from "../lib/types";
import s from "./StaffScreen.module.css";

// Staff is scoped to waiters for now — the only role a manager adds here.
const NEW_STAFF_ROLE = "waiter" as const;

export function StaffScreen() {
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [clockStatuses, setClockStatuses] = useState<Record<number, "clocked_out" | "clocked_in" | "on_break">>({});
  const [hours, setHours] = useState<Record<number, number>>({});

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [loginStaffId, setLoginStaffId] = useState("");
  const [loginPin, setLoginPin] = useState("");
  const [loginResult, setLoginResult] = useState<string | null>(null);

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
    const body: StaffCreateIn = { name, pin, role: NEW_STAFF_ROLE, ...(phone ? { phone } : {}) };
    try {
      const created = await createStaff(body);
      setName("");
      setPhone("");
      setPin("");
      setStaff((prev) => [created, ...prev]);
      toast(`Waiter added: ${created.name}`);
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

  return (
    <div className={s.root}>
      <PageHeader title="Waiter Management" subtitle="Add waiters, PIN login and time clock" />

      <section className={s.card}>
        <h3 className={s.cardTitle}>New waiter</h3>
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
        </div>
        <Button type="button" disabled={submitting} onClick={() => void submit()}>
          {submitting ? "Adding…" : "Add waiter"}
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

      <section className={s.card}>
        <h3 className={s.cardTitle}>Team{loaded && staff.length > 0 ? ` (${staff.length})` : ""}</h3>

        {!loaded && <p className={s.loading}>Loading staff…</p>}
        {loadError && (
          <ErrorState
            title="Could not load staff"
            description={loadError}
            action={
              <Button type="button" onClick={() => void reload()}>
                Retry
              </Button>
            }
          />
        )}
        {loaded && !loadError && staff.length === 0 && (
          <EmptyState title="No staff yet" description="Add a waiter above to enable PIN login and the time clock." />
        )}

        {loaded && staff.length > 0 && (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Role</th>
                  <th>Phone</th>
                  <th>Hours today</th>
                  <th>Status</th>
                  <th className={s.actionsCol} />
                </tr>
              </thead>
              <tbody>
                {staff.map((m) => {
                  const status = clockStatuses[m.id] ?? "clocked_out";
                  return (
                    <tr key={m.id}>
                      <td className={s.nameCell}>{m.name}</td>
                      <td>
                        <span className={s.rolePill}>{m.role}</span>
                      </td>
                      <td className={s.mono}>{m.phone ?? "—"}</td>
                      <td className={s.mono}>{hours[m.id] !== undefined ? hours[m.id].toFixed(2) : "—"}</td>
                      <td>
                        <span
                          className={`${s.statusPill} ${
                            status === "clocked_in"
                              ? s.statusOn
                              : status === "on_break"
                                ? s.statusBreak
                                : s.statusOff
                          }`}
                        >
                          {status === "clocked_in" ? "On shift" : status === "on_break" ? "On break" : "Off"}
                        </span>
                        {m.training_mode && <span className={s.trainingPill}>Training</span>}
                      </td>
                      <td className={s.actionsCol}>
                        <div className={s.rowActions}>
                          <Button type="button" variant="ghost" onClick={() => void toggleClock(m)}>
                            {status === "clocked_in" ? "Clock out" : status === "on_break" ? "End break" : "Clock in"}
                          </Button>
                          {status === "clocked_in" && (
                            <Button type="button" variant="ghost" onClick={() => void startBreak(m)}>
                              Break
                            </Button>
                          )}
                          <Button type="button" variant="ghost" onClick={() => void toggleTraining(m)}>
                            {m.training_mode ? "Exit training" : "Training"}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
