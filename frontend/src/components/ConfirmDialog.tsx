import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Button } from "./Button";
import s from "./ConfirmDialog.module.css";

interface Props {
  /** Heading shown at the top of the dialog. */
  title: string;
  /** Body text explaining what is about to happen. */
  message: string;
  /** Optional custom content (e.g. a picker) rendered between message and buttons. */
  children?: ReactNode;
  /** Label for the confirming action button (default "Confirm"). */
  confirmLabel?: string;
  /** Label for the dismissing button (default "Cancel"). */
  cancelLabel?: string;
  /** Render the confirm button in the danger (red) style. */
  danger?: boolean;
  /** Disable the confirm button + show busy text while an action runs. */
  busy?: boolean;
  /** Disable confirm WITHOUT the busy label — for dialogs gated on a typed
   *  confirmation phrase, where "Working…" would be a lie. */
  confirmDisabled?: boolean;
  /** Button size. Defaults to "lg" so every existing caller is unchanged; pass
   *  "md" on admin screens where the lg buttons dwarf the dialog. */
  size?: "md" | "lg";
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Small, accessible confirmation modal — a styled replacement for window.confirm().
 * Overlay click and Escape both cancel; the confirm button is auto-focused.
 */
export function ConfirmDialog({
  title,
  message,
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  busy = false,
  confirmDisabled = false,
  size = "lg",
  onConfirm,
  onCancel,
}: Props) {
  const modalRef = useRef<HTMLDivElement>(null);

  // ON MOUNT ONLY. Callers pass inline arrows for onCancel, so a dependency on
  // it makes this re-run after every render — including the render caused by
  // typing. It would then re-select the field, and the next character would
  // replace everything typed so far, leaving the input stuck on one letter.
  useEffect(() => {
    // A dialog carrying a form focuses its FIRST FIELD, not the confirm button.
    // Otherwise a prefilled input (the suggested table label, say) looks
    // read-only: you type and nothing happens because the button has focus.
    // With no field, focus the confirm button (last in the footer) so Enter
    // confirms, which is what a plain yes/no dialog wants.
    const firstField = modalRef.current?.querySelector<HTMLElement>(
      "input:not([type=hidden]), select, textarea",
    );
    if (firstField) {
      firstField.focus();
      if (firstField instanceof HTMLInputElement && firstField.type === "text") {
        // Select it so the suggestion can be typed straight over.
        firstField.select();
      }
    } else {
      modalRef.current?.querySelector<HTMLButtonElement>(".confirmBtn")?.focus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Escape needs the CURRENT busy/onCancel, so it stays its own effect.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div className={s.overlay} onClick={() => !busy && onCancel()}>
      <div
        ref={modalRef}
        className={s.modal}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className={s.title}>{title}</h2>
        <p className={s.message}>{message}</p>
        {children}
        <div className={s.footer}>
          <Button size={size} variant="ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            className="confirmBtn"
            size={size}
            variant={danger ? "danger" : "primary"}
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
          >
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
