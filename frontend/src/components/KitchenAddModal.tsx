import { useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import s from "./DishEditModal.module.css";

interface Props {
  /** Existing kitchen names, so a duplicate is caught before the round trip. */
  existingNames: string[];
  onClose: () => void;
  /** Called with the validated name; the parent owns the create call. */
  onSubmit: (name: string) => void;
  busy?: boolean;
}

/**
 * Add a kitchen board.
 *
 * In a dialog rather than a permanent row above the list: kitchens are created
 * a handful of times ever, while the list of them is what the page is for.
 */
export function KitchenAddModal({ existingNames, onClose, onSubmit, busy = false }: Props) {
  const [name, setName] = useState("");
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const trimmed = name.trim();
  // Caught here rather than on the server so the name stays on screen to edit,
  // and case-insensitively because "Juice" and "juice" are the same board.
  const duplicate = existingNames.some((n) => n.toLowerCase() === trimmed.toLowerCase());
  const canSave = trimmed !== "" && !duplicate && !busy;

  function submit() {
    if (!canSave) return;
    onSubmit(trimmed);
  }

  return (
    <div className={s.overlay} onClick={() => !busy && onClose()}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-label="Add a kitchen"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={s.header}>
          <h2 className={s.title}>Add a kitchen</h2>
          <button className={s.close} onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {duplicate && <div className={s.error}>A kitchen called “{trimmed}” already exists.</div>}

        <div className={s.body}>
          <label className={s.field}>
            <span className={s.label}>Kitchen name</span>
            <input
              ref={nameRef}
              className={s.input}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="For example Juice, Grill or Bakery"
              aria-label="New kitchen name"
              disabled={busy}
              data-testid="kitchen-new-name"
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
            />
            <span className={s.hint}>
              Each kitchen gets its own board. Route menu categories to it below.
            </span>
          </label>
        </div>

        <div className={s.footer}>
          <div className={s.footerRight}>
            <Button size="md" variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button size="md" onClick={submit} disabled={!canSave} data-testid="kitchen-add-submit">
              {busy ? "Adding…" : "Add kitchen"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
