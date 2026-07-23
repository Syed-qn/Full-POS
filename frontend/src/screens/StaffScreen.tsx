import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import { createStaff, listStaff } from "../lib/staffApi";
import type { StaffCreateIn, StaffMember } from "../lib/types";
import s from "./StaffScreen.module.css";

// Staff is scoped to waiters for now — the only role a manager adds here.
const NEW_STAFF_ROLE = "waiter" as const;

export function StaffScreen() {
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showAdd, setShowAdd] = useState(false);
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
                </tr>
              </thead>
              <tbody>
                {waiters.map((m) => (
                  <tr key={m.id}>
                    <td className={s.nameCell}>{m.name}</td>
                    <td className={s.mono}>{m.phone ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

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
