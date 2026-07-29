import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { SideDrawer } from "../components/SideDrawer";
import { toast } from "../components/Toaster";
import {
  clockStaff,
  createStaff,
  deleteStaff,
  getClockStatus,
  getHours,
  getSales,
  getTipsByStaff,
  listMistakes,
  listStaff,
  setTrainingMode,
  updateStaff,
} from "../lib/staffApi";
import type { StaffCreateIn, StaffMember } from "../lib/types";
import s from "./StaffScreen.module.css";

function todayYMD() {
  return new Date().toISOString().slice(0, 10);
}
function monthStartYMD() {
  return todayYMD().slice(0, 8) + "01";
}

/** Operational roles managed from this screen (not managers — those are owner-only). */
export type ManagedStaffRole = "waiter" | "cashier" | "kitchen";

const ROLE_COPY: Record<
  ManagedStaffRole,
  { title: string; singular: string; plural: string; addLabel: string }
> = {
  waiter: {
    title: "Waiter Management",
    singular: "waiter",
    plural: "Waiters",
    addLabel: "+ Add waiter",
  },
  cashier: {
    title: "Cashier Management",
    singular: "cashier",
    plural: "Cashiers",
    addLabel: "+ Add cashier",
  },
  // "Kitchen Management" was already taken by /kitchens, which configures KDS
  // STATIONS — that screen is now "Kitchen Setup". This one is the sign-ins.
  //
  // "kitchen login", not "cook": one kitchen shares one sign-in on the board
  // that hangs over the pass. It is a terminal that a shift signs into, not a
  // person, and naming it after a person invites one per cook.
  kitchen: {
    title: "Kitchen Management",
    singular: "kitchen login",
    plural: "Kitchen logins",
    addLabel: "+ Add kitchen login",
  },
};

export function StaffScreen({ managedRole = "waiter" }: { managedRole?: ManagedStaffRole }) {
  const copy = ROLE_COPY[managedRole];
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [editTarget, setEditTarget] = useState<StaffMember | null>(null);
  const [selected, setSelected] = useState<StaffMember | null>(null);
  const [clockStatuses, setClockStatuses] = useState<Record<number, "clocked_out" | "clocked_in" | "on_break">>({});
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function openAdd() {
    setName("");
    setPhone("");
    setPin("");
    setEditTarget(null);
    setShowAdd(true);
  }

  function openEdit(m: StaffMember) {
    setName(m.name);
    setPhone(m.phone ?? "");
    setPin(""); // blank = keep current PIN
    setShowAdd(false);
    setEditTarget(m);
  }

  function closeModal() {
    setShowAdd(false);
    setEditTarget(null);
  }

  const modalOpen = showAdd || editTarget !== null;

  async function removeMember(m: StaffMember) {
    if (
      !window.confirm(
        `Remove ${copy.singular} "${m.name}"? They will no longer be able to sign in.`,
      )
    )
      return;
    try {
      await deleteStaff(m.id);
      setStaff((prev) => prev.filter((x) => x.id !== m.id));
      toast(
        `${copy.singular[0].toUpperCase()}${copy.singular.slice(1)} removed: ${m.name}`,
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : `Could not remove ${copy.singular}.`, "error");
    }
  }

  // API returns every role — keep only the managed role for this screen.
  const members = staff.filter((m) => m.role === managedRole);

  async function loadClockStatuses(members: StaffMember[]) {
    const results = await Promise.all(
      members.map(async (m) => {
        try {
          const { status } = await getClockStatus(m.id);
          const norm = status === "clocked_in" || status === "on_break" ? status : "clocked_out";
          return [m.id, norm] as const;
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
      void loadClockStatuses(rows.filter((m) => m.role === managedRole));
    } catch (e) {
      setStaff([]);
      setLoadError(e instanceof Error ? e.message : `Could not load ${copy.plural.toLowerCase()}.`);
    } finally {
      setLoaded(true);
    }
  }

  async function toggleShift(m: StaffMember) {
    const status = clockStatuses[m.id] ?? "clocked_out";
    const on = status === "clocked_in" || status === "on_break";
    try {
      await clockStaff(m.id, on ? "clock_out" : "clock_in");
      setClockStatuses((prev) => ({ ...prev, [m.id]: on ? "clocked_out" : "clocked_in" }));
      toast(`${m.name} clocked ${on ? "out" : "in"}.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update shift.", "error");
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- initial load only
  }, []);

  async function toggleTraining(m: StaffMember) {
    try {
      const next = await setTrainingMode(m.id, !m.training_mode);
      setStaff((prev) => prev.map((x) => (x.id === m.id ? next : x)));
      toast(`${m.name} training mode ${next.training_mode ? "on" : "off"}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update training mode.", "error");
    }
  }

  async function submit() {
    if (!name.trim()) {
      toast("Name is required.", "error");
      return;
    }
    // Add requires a PIN; edit keeps the current PIN when the box is left blank.
    if (!editTarget && !pin.trim()) {
      toast("PIN is required.", "error");
      return;
    }
    if (pin.trim() && pin.trim().length < 4) {
      toast("PIN must be at least 4 digits.", "error");
      return;
    }
    setSubmitting(true);
    try {
      if (editTarget) {
        const body: { name?: string; phone?: string | null; pin?: string } = {
          name: name.trim(),
          phone: phone.trim() || null,
        };
        if (pin.trim()) body.pin = pin.trim();
        const updated = await updateStaff(editTarget.id, body);
        setStaff((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
        closeModal();
        toast(
          `${copy.singular[0].toUpperCase()}${copy.singular.slice(1)} updated: ${updated.name}`,
        );
      } else {
        const body: StaffCreateIn = {
          name,
          pin,
          role: managedRole,
          ...(phone ? { phone } : {}),
        };
        const created = await createStaff(body);
        setStaff((prev) => [created, ...prev]);
        closeModal();
        toast(
          `${copy.singular[0].toUpperCase()}${copy.singular.slice(1)} added: ${created.name}`,
        );
      }
      setName("");
      setPhone("");
      setPin("");
    } catch (e) {
      toast(
        e instanceof Error
          ? e.message
          : `Could not ${editTarget ? "update" : "add"} ${copy.singular}.`,
        "error",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const roleCap = copy.singular[0].toUpperCase() + copy.singular.slice(1);

  return (
    <div className={s.root}>
      <PageHeader
        title={copy.title}
        subtitle={`Add ${copy.plural.toLowerCase()} and see your team`}
        right={
          <Button type="button" size="md" onClick={openAdd}>
            {copy.addLabel}
          </Button>
        }
      />

      <section className={s.card}>
        <h3 className={s.cardTitle}>
          {copy.plural}
          {loaded && members.length > 0 ? ` (${members.length})` : ""}
        </h3>

        {!loaded && (
          <div
            className={s.tableWrap}
            aria-busy="true"
            aria-label={`Loading ${copy.plural.toLowerCase()}`}
          >
            <table className={s.table}>
              <thead>
                <tr>
                  <th>No.</th>
                  <th>Name</th>
                  <th>Phone</th>
                  <th>Status</th>
                  <th>Shift</th>
                  <th>Training</th>
                  <th className={s.actionsCol}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 4 }).map((_, r) => (
                  <tr key={r}>
                    {[12, 38, 30, 30, 22, 22, 18].map((w, c) => (
                      <td key={c} className={c === 6 ? s.actionsCol : undefined}>
                        <span className={s.sk} style={{ width: `${w}%` }} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {loadError && (
          <ErrorState
            title={`Could not load ${copy.plural.toLowerCase()}`}
            description={loadError}
            action={
              <Button type="button" onClick={() => void reload()}>
                Retry
              </Button>
            }
          />
        )}
        {loaded && !loadError && members.length === 0 && (
          <EmptyState
            title={`No ${copy.plural.toLowerCase()} yet`}
            description={`Add a ${copy.singular} above to get started.`}
          />
        )}

        {loaded && members.length > 0 && (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>No.</th>
                  <th>Name</th>
                  <th>Phone</th>
                  <th>Status</th>
                  <th>Shift</th>
                  <th>Training</th>
                  <th className={s.actionsCol}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.id}>
                    {/* The branch-local sign-in number. The internal id is
                        deliberately not shown — staff typing it was how sign-in
                        used to cross into another restaurant. */}
                    <td className={s.mono}>{m.staff_code ?? "—"}</td>
                    <td className={s.nameCell}>
                      <button
                        type="button"
                        className={s.nameBtn}
                        onClick={() => setSelected(m)}
                        title="View details"
                        data-testid={`${managedRole}-view-${m.id}`}
                      >
                        {m.name}
                      </button>
                    </td>
                    <td className={s.mono}>{m.phone ?? "—"}</td>
                    <td>
                      <span
                        className={`${s.statusPill} ${m.is_active === false ? s.statusOff : s.statusOn}`}
                      >
                        {m.is_active === false ? "Inactive" : "Active"}
                      </span>
                    </td>
                    <td>
                      {(() => {
                        const onShift =
                          clockStatuses[m.id] === "clocked_in" || clockStatuses[m.id] === "on_break";
                        return (
                          <button
                            type="button"
                            role="switch"
                            aria-checked={onShift}
                            aria-label={`Shift for ${m.name}`}
                            className={`${s.switch} ${onShift ? s.switchOn : ""}`}
                            onClick={() => void toggleShift(m)}
                          >
                            <span className={s.switchKnob} />
                          </button>
                        );
                      })()}
                    </td>
                    <td>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={!!m.training_mode}
                        aria-label={`Training mode for ${m.name}`}
                        className={`${s.switch} ${m.training_mode ? s.switchOn : ""}`}
                        onClick={() => void toggleTraining(m)}
                      >
                        <span className={s.switchKnob} />
                      </button>
                    </td>
                    <td className={s.actionsCol}>
                      <div className={s.rowActions}>
                        <button
                          type="button"
                          className={s.linkBtn}
                          onClick={() => openEdit(m)}
                          data-testid={`${managedRole}-edit-${m.id}`}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className={s.linkBtnDanger}
                          onClick={() => void removeMember(m)}
                          data-testid={`${managedRole}-delete-${m.id}`}
                        >
                          Remove
                        </button>
                      </div>
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
        title={selected ? selected.name : roleCap}
        onClose={() => setSelected(null)}
      >
        {selected && <StaffDetail member={selected} roleLabel={roleCap} />}
      </SideDrawer>

      {modalOpen &&
        createPortal(
          <div className={s.overlay} onClick={submitting ? undefined : closeModal}>
            <div className={s.modal} onClick={(e) => e.stopPropagation()}>
              <div className={s.modalHead}>
                <h3 className={s.cardTitle}>
                  {editTarget ? `Edit ${copy.singular}` : `New ${copy.singular}`}
                </h3>
                <button
                  type="button"
                  className={s.close}
                  aria-label="Close"
                  disabled={submitting}
                  onClick={closeModal}
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
                  <span>{editTarget ? "New PIN (blank = keep)" : "PIN"}</span>
                  <input
                    aria-label={editTarget ? "New PIN" : "New staff PIN"}
                    type="password"
                    value={pin}
                    onChange={(e) => setPin(e.target.value)}
                    placeholder={editTarget ? "Leave blank to keep current" : ""}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void submit();
                    }}
                  />
                </label>
              </div>
              <div className={s.modalFoot}>
                <Button type="button" variant="ghost" disabled={submitting} onClick={closeModal}>
                  Cancel
                </Button>
                <Button type="button" disabled={submitting} onClick={() => void submit()}>
                  {submitting
                    ? editTarget
                      ? "Saving…"
                      : "Adding…"
                    : editTarget
                      ? "Save changes"
                      : `Add ${copy.singular}`}
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

/** Manager/owner view of a staff member: profile, today's shift & sales, tips
 *  this month, and any recorded mistakes. Best-effort — a failing endpoint
 *  just shows "—" rather than breaking the drawer. */
function StaffDetail({
  member,
  roleLabel,
}: {
  member: StaffMember;
  roleLabel: string;
}) {
  const [clock, setClock] = useState<string | null>(null);
  const [hoursToday, setHoursToday] = useState<number | null>(null);
  const [salesToday, setSalesToday] = useState<string | null>(null);
  const [tipsMonth, setTipsMonth] = useState<string | null>(null);
  const [mistakes, setMistakes] = useState<Mistake[] | null>(null);

  useEffect(() => {
    let alive = true;
    const today = todayYMD();
    getClockStatus(member.id).then((r) => alive && setClock(r.status)).catch(() => {});
    getHours(member.id, today).then((r) => alive && setHoursToday(r.hours)).catch(() => {});
    getSales(member.id, today).then((r) => alive && setSalesToday(r.sales_aed)).catch(() => {});
    getTipsByStaff(monthStartYMD(), today)
      .then((m) => alive && setTipsMonth(m?.[String(member.id)] ?? "0.00"))
      .catch(() => {});
    listMistakes(member.id)
      .then((rows) => alive && setMistakes(rows as Mistake[]))
      .catch(() => alive && setMistakes([]));
    return () => {
      alive = false;
    };
  }, [member.id]);

  return (
    <div className={s.detail}>
      <section className={s.detailBlock}>
        <h4 className={s.detailHead}>Profile</h4>
        <dl className={s.detailList}>
          <div className={s.detailRow}>
            <dt>Role</dt>
            <dd className={s.cap}>{roleLabel}</dd>
          </div>
          <div className={s.detailRow}>
            <dt>Phone</dt>
            <dd className={s.mono}>{member.phone ?? "—"}</dd>
          </div>
          <div className={s.detailRow}>
            <dt>Status</dt>
            <dd>{member.is_active === false ? "Inactive" : "Active"}</dd>
          </div>
          <div className={s.detailRow}>
            <dt>Training mode</dt>
            <dd>{member.training_mode ? "On" : "Off"}</dd>
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
