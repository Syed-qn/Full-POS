import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ManagerFormModal } from "../components/ManagerFormModal";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import { deleteManager, listManagers } from "../lib/staffApi";
import type { StaffMember } from "../lib/types";
import s from "./ManagerManagementScreen.module.css";

/**
 * Owner-only "Manager Management" — create, read, update, and remove manager
 * logins. Managers sign in with their staff id + PIN. Removing a manager
 * deactivates the login (history is preserved). Backend enforces owner-only via
 * require_role("owner"); this screen is also owner-gated in nav.
 */
export function ManagerManagementScreen() {
  const [managers, setManagers] = useState<StaffMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // One dialog serves both: null = closed, {} = add, {manager} = edit.
  const [form, setForm] = useState<{ manager?: StaffMember } | null>(null);
  const [removing, setRemoving] = useState<StaffMember | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    try {
      setManagers(await listManagers());
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load managers", "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed", "error");
    } finally {
      setBusy(false);
    }
  }

  // Name, sign-in number and phone: those are the three things an owner has in
  // front of them when they come looking for one manager in a long list.
  const q = query.trim().toLowerCase();
  const shown = q
    ? managers.filter((m) =>
        [m.name, m.staff_code == null ? "" : String(m.staff_code), m.phone ?? ""].some((f) =>
          f.toLowerCase().includes(q),
        ),
      )
    : managers;

  function removeManager(m: StaffMember) {
    setRemoving(null);
    void run(async () => {
      await deleteManager(m.id);
      toast(`Manager "${m.name}" removed.`);
    });
  }

  return (
    <div className={s.screen}>
      <PageHeader
        title="Manager Management"
        subtitle="Create and manage manager logins. Managers sign in with their ID and PIN. Owner only."
        right={
          <Button
            size="md"
            disabled={busy}
            onClick={() => setForm({})}
            data-testid="manager-add-open"
          >
            + Add manager
          </Button>
        }
      />

      <section className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h3 className={s.cardTitle}>Managers</h3>
          </div>
          {/* Shown whenever there is anything to filter. It stays put as the
              list grows, so the control does not appear from nowhere at the
              moment a sixth manager is added. */}
          {managers.length > 0 && (
            <input
              className={s.search}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by name, No. or phone"
              aria-label="Filter managers"
              data-testid="manager-filter"
            />
          )}
        </div>

        {loading ? (
          /* The real table's shell with shimmer bars in the cells, rather than
             a "Loading…" line — the header and column widths are already known,
             so the page does not jump when the rows land. */
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Sign-in No.</th>
                  <th>Phone</th>
                  <th className={s.actionsCol}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 3 }).map((_, r) => (
                  <tr key={r}>
                    {[46, 20, 34, 60].map((w, c) => (
                      <td key={c} className={c === 3 ? s.actionsCol : undefined}>
                        <span className={s.sk} style={{ width: `${w}%` }} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : managers.length === 0 ? (
          <p className={s.muted}>No managers yet. Use “Add manager” above.</p>
        ) : shown.length === 0 ? (
          <p className={s.muted}>No manager matches “{query.trim()}”.</p>
        ) : (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th>Name</th>
                  {/* The sign-in number, not the internal id — showing the id is
                      what led staff to type another branch's number. */}
                  <th>Sign-in No.</th>
                  <th>Phone</th>
                  <th className={s.actionsCol}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((m) => (
                  <tr key={m.id}>
                    <td>
                      <span className={s.nameCell}>
                        <span className={s.avatar} aria-hidden>👤</span>
                        <span className={s.rowName}>{m.name}</span>
                      </span>
                    </td>
                    <td className={s.codeCell}>{m.staff_code ?? "—"}</td>
                    <td className={s.codeCell}>{m.phone ?? "—"}</td>
                    <td className={s.actionsCol}>
                      <span className={s.rowActions}>
                        <button
                          type="button"
                          className={s.linkBtn}
                          disabled={busy}
                          onClick={() => setForm({ manager: m })}
                          data-testid={`manager-edit-${m.id}`}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className={s.linkBtnDanger}
                          disabled={busy}
                          onClick={() => setRemoving(m)}
                          data-testid={`manager-delete-${m.id}`}
                        >
                          Remove
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {removing && (
        <ConfirmDialog
          title={`Remove ${removing.name}?`}
          message="They will no longer be able to sign in. Their past orders and shifts are kept."
          confirmLabel="Remove manager"
          danger
          size="md"
          busy={busy}
          onConfirm={() => removeManager(removing)}
          onCancel={() => setRemoving(null)}
        />
      )}

      {form && (
        <ManagerFormModal
          // Remount per manager, so opening Edit on a second row never shows
          // the first one's values held in the form's own state.
          key={form.manager?.id ?? "new"}
          manager={form.manager}
          onClose={() => setForm(null)}
          onSaved={(n) => {
            void load();
            toast(form.manager ? `Manager "${n}" updated.` : `Manager "${n}" added.`);
          }}
        />
      )}
    </div>
  );
}

