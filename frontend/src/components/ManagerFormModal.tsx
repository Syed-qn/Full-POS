import { useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { createManager, updateManager } from "../lib/staffApi";
import type { StaffMember } from "../lib/types";
import s from "./DishEditModal.module.css";

interface Props {
  /** Existing manager to edit, or undefined to add a new one. */
  manager?: StaffMember;
  onClose: () => void;
  /** Called with the manager's name once the server has accepted the change, so
   *  the parent can refresh its list and say what happened. */
  onSaved: (name: string) => void;
}

/**
 * Add or edit a manager login.
 *
 * Both live in a dialog rather than on the page: adding happens a handful of
 * times, and editing used to swap the row for three inputs, which shifted every
 * row below it and gave a PIN field the same weight as a name. One form for
 * both keeps the validation rules in a single place.
 */
export function ManagerFormModal({ manager, onClose, onSaved }: Props) {
  const isEdit = manager !== undefined;
  const [name, setName] = useState(manager?.name ?? "");
  const [phone, setPhone] = useState(manager?.phone ?? "");
  // Always starts blank on edit: a prefilled PIN box implies the current PIN is
  // readable, and it is not — blank means "keep it".
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // Escape closes. The overlay handles a click outside, but a keyboard user who
  // opened this by accident would otherwise have to tab to Cancel.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // On add, a PIN is required. On edit it is optional, but if one is typed it
  // still has to be a real PIN — a 2-digit PIN must be rejected, not saved.
  const pinOk = isEdit ? pin === "" || pin.trim().length >= 4 : pin.trim().length >= 4;
  const canSave = name.trim() !== "" && pinOk && !busy;

  async function onSave() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    const n = name.trim();
    try {
      if (isEdit) {
        // Send only what actually changed, so an untouched field can never
        // overwrite a value someone else edited in the meantime.
        const body: { name?: string; phone?: string | null; pin?: string } = {};
        if (n !== manager!.name) body.name = n;
        if (phone.trim() !== (manager!.phone ?? "")) body.phone = phone.trim() || null;
        if (pin.trim()) body.pin = pin.trim();
        if (Object.keys(body).length === 0) {
          onClose();
          return;
        }
        await updateManager(manager!.id, body);
      } else {
        await createManager({ name: n, phone: phone.trim() || null, pin: pin.trim() });
      }
      onSaved(n);
      onClose();
    } catch (err: unknown) {
      // Stay open and keep what was typed: re-entering the name and PIN because
      // the phone was a duplicate is the kind of thing that loses a PIN.
      setError(err instanceof Error ? err.message : "Failed to save manager.");
      setBusy(false);
    }
  }

  const title = isEdit ? `Edit ${manager!.name}` : "Add a manager";

  return (
    <div className={s.overlay} onClick={onClose}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={s.header}>
          <h2 className={s.title}>{title}</h2>
          <button className={s.close} onClick={onClose} aria-label="Close">
            ×
          </button>
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
              placeholder="e.g. Asfer Ali"
              aria-label="Manager name"
              disabled={busy}
              data-testid="manager-form-name"
            />
          </label>
          <label className={s.field}>
            <span className={s.label}>Phone (optional)</span>
            <input
              className={s.input}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+971 50 123 4567"
              aria-label="Manager phone"
              disabled={busy}
              data-testid="manager-form-phone"
            />
          </label>
          <label className={s.field}>
            <span className={s.label}>{isEdit ? "New PIN" : "PIN"}</span>
            <input
              className={s.input}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
              placeholder={isEdit ? "Leave blank to keep current PIN" : "At least 4 digits"}
              inputMode="numeric"
              aria-label={isEdit ? "New PIN" : "Manager PIN"}
              disabled={busy}
              data-testid="manager-form-pin"
              onKeyDown={(e) => {
                if (e.key === "Enter") void onSave();
              }}
            />
            <span className={s.hint}>
              {isEdit
                ? "Setting a PIN replaces the old one immediately."
                : "They can sign in immediately with this PIN."}
            </span>
          </label>
        </div>

        <div className={s.footer}>
          <div className={s.footerRight}>
            <Button size="md" variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="md"
              onClick={onSave}
              disabled={!canSave}
              data-testid="manager-form-submit"
            >
              {busy ? "Saving…" : isEdit ? "Save changes" : "Add manager"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
