import { useEffect, useId, useRef, useState } from "react";
import { Button } from "./Button";
import s from "./ApprovalPinModal.module.css";

export type ApprovalPinModalProps = {
  open: boolean;
  actionLabel: string;
  recordLabel?: string;
  reasonRequired?: boolean;
  onCancel: () => void;
  onApprove: (payload: { pin: string; reason: string }) => void | Promise<void>;
};

/**
 * Manager PIN gate for void, refund, discount override, stock adjustment, etc.
 */
export function ApprovalPinModal({
  open,
  actionLabel,
  recordLabel,
  reasonRequired = false,
  onCancel,
  onApprove,
}: ApprovalPinModalProps) {
  const [pin, setPin] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasonRef = useRef<HTMLInputElement>(null);
  const firstPadRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const errorId = useId();

  // Reset + focus when the dialog opens (not on every busy toggle).
  useEffect(() => {
    if (!open) return;
    setPin("");
    setReason("");
    setError(null);
    setBusy(false);

    const t = window.setTimeout(() => {
      if (reasonRequired) reasonRef.current?.focus();
      else firstPadRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(t);
  }, [open, reasonRequired]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) {
        e.stopPropagation();
        onCancel();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel, busy]);

  if (!open) return null;

  async function submit() {
    setError(null);
    if (pin.length < 4) {
      setError("Enter a manager PIN (at least 4 digits).");
      return;
    }
    if (reasonRequired && !reason.trim()) {
      setError("Reason is required for this action.");
      return;
    }
    setBusy(true);
    try {
      await onApprove({ pin, reason: reason.trim() });
      setPin("");
      setReason("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setBusy(false);
    }
  }

  function appendDigit(d: string) {
    setPin((p) => (p.length >= 8 ? p : p + d));
  }

  const padKeys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "C", "0", "⌫"] as const;

  function padLabel(key: (typeof padKeys)[number]): string {
    if (key === "C") return "Clear PIN";
    if (key === "⌫") return "Backspace";
    return `Digit ${key}`;
  }

  return (
    <div className={s.backdrop} role="presentation" onClick={onCancel}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={error ? errorId : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id={titleId} className={s.title}>
          Manager approval
        </h2>
        <p className={s.action}>
          Action: <strong>{actionLabel}</strong>
        </p>
        {recordLabel && (
          <p className={s.record}>
            Record: <span className="mono">{recordLabel}</span>
          </p>
        )}

        {reasonRequired && (
          <label className={s.field}>
            <span>Reason</span>
            <input
              ref={reasonRef}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why is this needed?"
              autoComplete="off"
              aria-required="true"
            />
          </label>
        )}

        <div className={s.pinDisplay} aria-live="polite" aria-label="PIN entry">
          {pin ? "•".repeat(pin.length) : "Enter PIN"}
        </div>

        <div className={s.pad} role="group" aria-label="PIN pad">
          {padKeys.map((key, index) => (
            <button
              key={key}
              type="button"
              className={s.padKey}
              aria-label={padLabel(key)}
              ref={index === 0 ? firstPadRef : undefined}
              disabled={busy}
              onClick={() => {
                if (key === "C") setPin("");
                else if (key === "⌫") setPin((p) => p.slice(0, -1));
                else appendDigit(key);
              }}
            >
              {key}
            </button>
          ))}
        </div>

        {error && (
          <p id={errorId} className={s.error} role="alert">
            {error}
          </p>
        )}

        <div className={s.actions}>
          <Button type="button" variant="ghost" size="lg" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            size="touch"
            onClick={() => void submit()}
            disabled={busy}
          >
            {busy ? "Checking…" : "Approve"}
          </Button>
        </div>
      </div>
    </div>
  );
}
