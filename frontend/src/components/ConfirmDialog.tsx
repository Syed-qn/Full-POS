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
  onConfirm,
  onCancel,
}: Props) {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Focus the confirm button (last in the footer) so Enter confirms.
    modalRef.current?.querySelector<HTMLButtonElement>(".confirmBtn")?.focus();
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
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            className="confirmBtn"
            variant={danger ? "danger" : "primary"}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
