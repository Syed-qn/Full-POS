import { useRef, useState, useEffect } from "react";
import { Button } from "./Button";
import { addRider, updateRider } from "../lib/ridersApi";
import type { RiderOut } from "../lib/types";
import s from "./DishEditModal.module.css";

interface Props {
  /** Existing rider to edit, or undefined to add a new one. */
  rider?: RiderOut;
  onClose: () => void;
  /** Called with the created/updated rider so the parent can sync its list. */
  onSaved: (rider: RiderOut) => void;
}

export function RiderAddModal({ rider, onClose, onSaved }: Props) {
  const isEdit = rider !== undefined;
  const [name, setName] = useState(rider?.name ?? "");
  const [phone, setPhone] = useState(rider?.phone ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  const canSave = name.trim() !== "" && phone.trim() !== "" && !busy;

  async function onSave() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      const saved = isEdit
        ? await updateRider(rider!.id, { name: name.trim(), phone: phone.trim() })
        : await addRider({ name: name.trim(), phone: phone.trim() });
      onSaved(saved);
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save rider.";
      setError(
        msg.includes("409") || msg.toLowerCase().includes("duplicate")
          ? "Phone already registered."
          : msg,
      );
      setBusy(false);
    }
  }

  return (
    <div className={s.overlay} onClick={onClose}>
      <div className={s.modal} onClick={(e) => e.stopPropagation()}>
        <div className={s.header}>
          <h2 className={s.title}>{isEdit ? `Edit ${rider!.name}` : "Add rider"}</h2>
          <button className={s.close} onClick={onClose} aria-label="Close">×</button>
        </div>

        {error && <div className={s.error}>{error}</div>}

        <div className={s.body}>
          <label className={s.field}>
            <span className={s.label}>Full name</span>
            <input
              ref={nameRef}
              className={s.input}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Imran Khan"
            />
          </label>
          <label className={s.field}>
            <span className={s.label}>WhatsApp phone</span>
            <input
              className={s.input}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+971 50 123 4567"
              onKeyDown={(e) => { if (e.key === "Enter") onSave(); }}
            />
          </label>
        </div>

        <div className={s.footer}>
          <div className={s.footerRight}>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={onSave} disabled={!canSave}>
              {busy ? "Saving…" : isEdit ? "Save changes" : "Add rider"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
