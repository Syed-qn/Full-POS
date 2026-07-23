import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { SideDrawer } from "../components/SideDrawer";
import { toast } from "../components/Toaster";
import {
  createStaff,
  getClockStatus,
  getHours,
  getSales,
  getTipsByStaff,
  listMistakes,
  listStaff,
} from "../lib/staffApi";
import type { StaffCreateIn, StaffMember } from "../lib/types";
import s from "./StaffScreen.module.css";

function todayYMD() {
  return new Date().toISOString().slice(0, 10);
}
function monthStartYMD() {
  return todayYMD().slice(0, 8) + "01";
}

// Staff is scoped to waiters for now — the only role a manager adds here.
const NEW_STAFF_ROLE = "waiter" as const;

export function StaffScreen() {
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState<StaffMember | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function openAdd() {
    setName("");
    setPhone("");
    setPin("");
    setShowAdd(true);
  }

  // This screen is waiter-only, but the API returns every role — keep just waiters.
  const waiters = staff.filter((m) => m.role === NEW_STAFF_ROLE);

  async function reload() {
    setLoadError(null);
    try {
      setStaff(await listStaff());
    } catch (e) {
      setStaff([]);
      setLoadError(e instanceof Error ? e.message : "Could not load waiters.");
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
      setShowAdd(false);
      toast(`Waiter added: ${created.name}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not add waiter.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={s.root}>
      <PageHeader
        title="Waiter Management"
        subtitle="Add waiters and see your team"
        right={<Button type="button" size="md" onClick={openAdd}>+ Add waiter</Button>}
      />

      <section className={s.card}>
        <h3 className={s.cardTitle}>Waiters{loaded && waiters.length > 0 ? ` (${waiters.length})` : ""}</h3>

        {!loaded && <p className={s.loading}>Loading waiters…</p>}
        {loadError && (
          <ErrorState
            title="Could not load waiters"
            description={loadError}
            action={
              <Button type="button" onClick={() => void reload()}>
                Retry
              </Button>
            }
          />
        )}
        {loaded && !loadError && waiters.length === 0 && (
          <EmptyState title="No waiters yet" description="Add a waiter above to get started." />
        )}

        {loaded && waiters.length > 0 && (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Phone</th>
                  <th className={s.actionsCol}>View</th>
                </tr>
              </thead>
              <tbody>
                {waiters.map((m) => (
                  <tr key={m.id}>
                    <td className={s.nameCell}>{m.name}</td>
                    <td className={s.mono}>{m.phone ?? "—"}</td>
                    <td className={s.actionsCol}>
                      <button
                        type="button"
                        className={s.viewBtn}
                        aria-label={`View ${m.name}`}
                        title="View details"
                        onClick={() => setSelected(m)}
                      >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                          <path
                            d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"
                            stroke="currentColor"
                            strokeWidth="1.8"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                          <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <SideDrawer
        open={selected !== null}
        title={selected ? selected.name : "Waiter"}
        onClose={() => setSelected(null)}
      >
        {selected && <WaiterDetail waiter={selected} />}
      </SideDrawer>

      {showAdd &&
        createPortal(
          <div className={s.overlay} onClick={submitting ? undefined : () => setShowAdd(false)}>
            <div className={s.modal} onClick={(e) => e.stopPropagation()}>
              <div className={s.modalHead}>
                <h3 className={s.cardTitle}>New waiter</h3>
                <button
                  type="button"
                  className={s.close}
                  aria-label="Close"
                  disabled={submitting}
                  onClick={() => setShowAdd(false)}
                >
                  ×
                </button>
              </div>
              <div className={s.modalBody}>
                <label className={s.field}>
                  <span>Name</span>
                  <input
                    aria-label="Name"
                    autoFocus
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label className={s.field}>
                  <span>Phone</span>
                  <input aria-label="Phone" value={phone} onChange={(e) => setPhone(e.target.value)} />
                </label>
                <label className={s.field}>
                  <span>PIN</span>
                  <input
                    aria-label="New staff PIN"
                    type="password"
                    value={pin}
                    onChange={(e) => setPin(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void submit();
                    }}
                  />
                </label>
              </div>
              <div className={s.modalFoot}>
                <Button type="button" variant="ghost" disabled={submitting} onClick={() => setShowAdd(false)}>
                  Cancel
                </Button>
                <Button type="button" disabled={submitting} onClick={() => void submit()}>
                  {submitting ? "Adding…" : "Add waiter"}
                </Button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

const CLOCK_LABEL: Record<string, string> = {
  clocked_in: "On shift",
  on_break: "On break",
  clocked_out: "Off",
};

type Mistake = { id: number; staff_id: number; mistake_type: string; amount_aed: string };

/** Manager/owner view of a waiter: profile, today's shift & sales, tips this
 *  month, and any recorded mistakes. Everything is best-effort — a failing
 *  endpoint just shows "—" rather than breaking the drawer. */
function WaiterDetail({ waiter }: { waiter: StaffMember }) {
  const [clock, setClock] = useState<string | null>(null);
  const [hoursToday, setHoursToday] = useState<number | null>(null);
  const [salesToday, setSalesToday] = useState<string | null>(null);
  const [tipsMonth, setTipsMonth] = useState<string | null>(null);
  const [mistakes, setMistakes] = useState<Mistake[] | null>(null);

  useEffect(() => {
    let alive = true;
    const today = todayYMD();
    getClockStatus(waiter.id).then((r) => alive && setClock(r.status)).catch(() => {});
    getHours(waiter.id, today).then((r) => alive && setHoursToday(r.hours)).catch(() => {});
    getSales(waiter.id, today).then((r) => alive && setSalesToday(r.sales_aed)).catch(() => {});
    getTipsByStaff(monthStartYMD(), today)
      .then((m) => alive && setTipsMonth(m?.[String(waiter.id)] ?? "0.00"))
      .catch(() => {});
    listMistakes(waiter.id)
      .then((rows) => alive && setMistakes(rows as Mistake[]))
      .catch(() => alive && setMistakes([]));
    return () => {
      alive = false;
    };
  }, [waiter.id]);

  return (
    <div className={s.detail}>
      <section className={s.detailBlock}>
        <h4 className={s.detailHead}>Profile</h4>
        <dl className={s.detailList}>
          <div className={s.detailRow}>
            <dt>Role</dt>
            <dd className={s.cap}>{waiter.role}</dd>
          </div>
          <div className={s.detailRow}>
            <dt>Phone</dt>
            <dd className={s.mono}>{waiter.phone ?? "—"}</dd>
          </div>
          <div className={s.detailRow}>
            <dt>Status</dt>
            <dd>{waiter.is_active === false ? "Inactive" : "Active"}</dd>
          </div>
          <div className={s.detailRow}>
            <dt>Training mode</dt>
            <dd>{waiter.training_mode ? "On" : "Off"}</dd>
          </div>
        </dl>
      </section>

      <section className={s.detailBlock}>
        <h4 className={s.detailHead}>Today</h4>
        <dl className={s.detailList}>
          <div className={s.detailRow}>
            <dt>Shift</dt>
            <dd>{clock ? (CLOCK_LABEL[clock] ?? clock) : "—"}</dd>
          </div>
          <div className={s.detailRow}>
            <dt>Hours</dt>
            <dd className={s.mono}>{hoursToday != null ? hoursToday.toFixed(2) : "—"}</dd>
          </div>
          <div className={s.detailRow}>
            <dt>Sales</dt>
            <dd className={s.mono}>{salesToday != null ? `AED ${salesToday}` : "—"}</dd>
          </div>
        </dl>
      </section>

      <section className={s.detailBlock}>
        <h4 className={s.detailHead}>This month</h4>
        <dl className={s.detailList}>
          <div className={s.detailRow}>
            <dt>Tips</dt>
            <dd className={s.mono}>{tipsMonth != null ? `AED ${tipsMonth}` : "—"}</dd>
          </div>
        </dl>
      </section>

      <section className={s.detailBlock}>
        <h4 className={s.detailHead}>Mistakes</h4>
        {mistakes === null ? (
          <p className={s.detailEmpty}>Loading…</p>
        ) : mistakes.length === 0 ? (
          <p className={s.detailEmpty}>None recorded.</p>
        ) : (
          <ul className={s.mistakeList}>
            {mistakes.map((mk) => (
              <li key={mk.id} className={s.mistakeRow}>
                <span className={s.cap}>{mk.mistake_type.replace(/_/g, " ")}</span>
                <span className={s.mono}>AED {mk.amount_aed}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
