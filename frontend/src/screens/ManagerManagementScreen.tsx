import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  createManager,
  deleteManager,
  listManagers,
  updateManager,
} from "../lib/staffApi";
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
  const [editingId, setEditingId] = useState<number | null>(null);

  // New-manager form.
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");

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

  function addManager() {
    const n = name.trim();
    if (n === "" || pin.trim().length < 4) {
      toast("Enter a name and a PIN of at least 4 digits.", "error");
      return;
    }
    void run(async () => {
      await createManager({ name: n, phone: phone.trim() || null, pin: pin.trim() });
      setName("");
      setPhone("");
      setPin("");
      toast(`Manager "${n}" added.`);
    });
  }

  function saveEdit(m: StaffMember, next: { name: string; phone: string; pin: string }) {
    setEditingId(null);
    const body: { name?: string; phone?: string | null; pin?: string } = {};
    if (next.name.trim() && next.name.trim() !== m.name) body.name = next.name.trim();
    if (next.phone.trim() !== (m.phone ?? "")) body.phone = next.phone.trim() || null;
    if (next.pin.trim()) {
      if (next.pin.trim().length < 4) {
        toast("PIN must be at least 4 digits.", "error");
        return;
      }
      body.pin = next.pin.trim();
    }
    if (Object.keys(body).length === 0) return;
    void run(async () => {
      await updateManager(m.id, body);
      toast(`Manager "${m.name}" updated.`);
    });
  }

  function removeManager(m: StaffMember) {
    if (!window.confirm(`Remove manager "${m.name}"? They will no longer be able to sign in.`))
      return;
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
      />

      <section className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h3 className={s.cardTitle}>Add a manager</h3>
            <span className={s.cardSub}>They can sign in immediately with the PIN you set</span>
          </div>
        </div>
        <div className={s.addRow}>
          <input
            className={s.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Full name"
            aria-label="Manager name"
            disabled={busy}
            data-testid="manager-new-name"
          />
          <input
            className={s.input}
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="Phone (optional)"
            aria-label="Manager phone"
            disabled={busy}
            data-testid="manager-new-phone"
          />
          <input
            className={s.inputPin}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
            placeholder="PIN"
            inputMode="numeric"
            aria-label="Manager PIN"
            disabled={busy}
            data-testid="manager-new-pin"
          />
          <Button disabled={busy || name.trim() === "" || pin.trim().length < 4} onClick={addManager}>
            Add manager
          </Button>
        </div>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h3 className={s.cardTitle}>Managers</h3>
            <span className={s.cardSub}>{managers.length} active</span>
          </div>
        </div>

        {loading ? (
          <p className={s.muted}>Loading…</p>
        ) : managers.length === 0 ? (
          <p className={s.muted}>No managers yet. Add one above.</p>
        ) : (
          <div className={s.list}>
            {managers.map((m) =>
              editingId === m.id ? (
                <ManagerEditRow key={m.id} manager={m} busy={busy} onSave={saveEdit} onCancel={() => setEditingId(null)} />
              ) : (
                <div className={s.row} key={m.id}>
                  <span className={s.avatar} aria-hidden>👤</span>
                  <div className={s.rowMain}>
                    <span className={s.rowName}>{m.name}</span>
                    <span className={s.rowMeta}>
                      {/* The sign-in number, not the internal id — showing the id
                          is what led staff to type another branch's number. */}
                      No. {m.staff_code ?? "—"}
                      {m.phone ? ` · ${m.phone}` : ""}
                    </span>
                  </div>
                  <div className={s.rowActions}>
                    <button
                      type="button"
                      className={s.linkBtn}
                      disabled={busy}
                      onClick={() => setEditingId(m.id)}
                      data-testid={`manager-edit-${m.id}`}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className={s.linkBtnDanger}
                      disabled={busy}
                      onClick={() => removeManager(m)}
                      data-testid={`manager-delete-${m.id}`}
                    >
                      Remove
                    </button>
                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function ManagerEditRow({
  manager,
  busy,
  onSave,
  onCancel,
}: {
  manager: StaffMember;
  busy: boolean;
  onSave: (m: StaffMember, next: { name: string; phone: string; pin: string }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(manager.name);
  const [phone, setPhone] = useState(manager.phone ?? "");
  const [pin, setPin] = useState("");
  return (
    <div className={`${s.row} ${s.rowEditing}`}>
      <span className={s.avatar} aria-hidden>👤</span>
      <div className={s.editFields}>
        <input
          className={s.input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="Name"
          disabled={busy}
        />
        <input
          className={s.input}
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="Phone"
          aria-label="Phone"
          disabled={busy}
        />
        <input
          className={s.inputPin}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
          placeholder="New PIN (blank = keep)"
          inputMode="numeric"
          aria-label="New PIN"
          disabled={busy}
        />
      </div>
      <div className={s.rowActions}>
        <button
          type="button"
          className={s.linkBtn}
          disabled={busy}
          onClick={() => onSave(manager, { name, phone, pin })}
          data-testid={`manager-save-${manager.id}`}
        >
          Save
        </button>
        <button type="button" className={s.linkBtnMuted} disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
