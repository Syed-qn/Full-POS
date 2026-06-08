import { useEffect, useRef, useState } from "react";
import { RiderCard } from "../components/RiderCard";
import { addRider, deleteRider, fetchRiders, setRiderStatus } from "../lib/ridersApi";
import type { RiderOut, RiderStatus } from "../lib/types";
import s from "./RidersScreen.module.css";

export function RidersScreen() {
  const [riders, setRiders] = useState<RiderOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formPhone, setFormPhone] = useState("");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchRiders()
      .then(setRiders)
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    if (showForm) nameRef.current?.focus();
  }, [showForm]);

  async function onStatusChange(id: number, status: RiderStatus) {
    const updated = await setRiderStatus(id, status);
    setRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  async function onDelete(id: number) {
    if (!confirm("Remove this rider? This cannot be undone.")) return;
    await deleteRider(id);
    setRiders((rs) => rs.filter((r) => r.id !== id));
  }

  async function onAddRider(e: React.FormEvent) {
    e.preventDefault();
    setFormError("");
    const name = formName.trim();
    const phone = formPhone.trim();
    if (!name || !phone) {
      setFormError("Name and phone are required.");
      return;
    }
    setSaving(true);
    try {
      const created = await addRider({ name, phone });
      setRiders((rs) => [...rs, created]);
      setFormName("");
      setFormPhone("");
      setShowForm(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to add rider.";
      setFormError(msg.includes("409") || msg.toLowerCase().includes("duplicate") ? "Phone already registered." : msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={s.root}>
      <div className={s.header}>
        <h2 className={s.title}>Riders</h2>
        <button className={s.addBtn} onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancel" : "+ Add Rider"}
        </button>
      </div>

      {showForm && (
        <form className={s.form} onSubmit={onAddRider}>
          <div className={s.formRow}>
            <input
              ref={nameRef}
              className={s.input}
              placeholder="Full name"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
            />
            <input
              className={s.input}
              placeholder="WhatsApp phone (+971…)"
              value={formPhone}
              onChange={(e) => setFormPhone(e.target.value)}
            />
            <button className={s.saveBtn} type="submit" disabled={saving}>
              {saving ? "Adding…" : "Add"}
            </button>
          </div>
          {formError && <span className={s.formError}>{formError}</span>}
        </form>
      )}

      {loaded && riders.length === 0 && !showForm && (
        <div className={s.empty}>No riders yet — click "+ Add Rider" to register your first rider.</div>
      )}

      <div className={s.grid}>
        {riders.map((r) => (
          <RiderCard key={r.id} rider={r} onStatusChange={onStatusChange} onDelete={onDelete} />
        ))}
      </div>
    </div>
  );
}
