import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { setToken } from "../lib/auth";
import { getRoleHomePath, setStaffSession } from "../lib/navAccess";
import { staffLogin } from "../lib/staffApi";
import { ApiError } from "../lib/apiClient";
import { Button } from "./Button";
import s from "./StaffSwitchModal.module.css";

export type StaffSwitchModalProps = {
  open: boolean;
  onClose: () => void;
  /** When true, navigate to the new role home after successful switch. Default true. */
  navigateToHome?: boolean;
};

/**
 * In-shell staff PIN switch (R6): re-authenticate as another staff member
 * without full logout. Uses POST /api/v1/staff/login.
 */
export function StaffSwitchModal({
  open,
  onClose,
  navigateToHome = true,
}: StaffSwitchModalProps) {
  const navigate = useNavigate();
  const [staffId, setStaffId] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const staffIdRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const errorId = useId();

  useEffect(() => {
    if (!open) return;
    setStaffId("");
    setPin("");
    setError(null);
    setBusy(false);
    const t = window.setTimeout(() => staffIdRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, busy]);

  if (!open) return null;

  function pinPress(key: string) {
    setError(null);
    if (key === "clear") {
      setPin("");
      return;
    }
    if (key === "back") {
      setPin((p) => p.slice(0, -1));
      return;
    }
    setPin((p) => (p.length >= 8 ? p : p + key));
  }

  async function submit() {
    const id = Number(staffId.trim());
    if (!Number.isFinite(id) || id <= 0) {
      setError("Enter your staff ID number");
      return;
    }
    if (pin.length < 4) {
      setError("PIN must be at least 4 digits");
      return;
    }
    if (!navigator.onLine) {
      setError("Offline — reconnect to switch staff.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await staffLogin(id, pin);
      setToken(res.access_token);
      setStaffSession({
        role: res.role,
        training_mode: Boolean(res.training_mode),
        name: res.name,
        staff_id: res.staff_id,
      });
      onClose();
      if (navigateToHome) {
        navigate(getRoleHomePath(res.role), { replace: true });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Invalid staff ID or PIN");
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  const pinDisplay = "•".repeat(pin.length) || "Enter PIN";

  return (
    <div
      className={s.backdrop}
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={error ? errorId : undefined}
        data-testid="staff-switch-modal"
      >
        <h2 id={titleId} className={s.title}>
          Switch staff
        </h2>
        <p className={s.hint}>Enter staff ID and PIN — lands on that role’s home screen.</p>

        <label className={s.field}>
          Staff ID
          <input
            ref={staffIdRef}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            value={staffId}
            onChange={(e) => {
              setStaffId(e.target.value.replace(/\D/g, "").slice(0, 8));
              setError(null);
            }}
            aria-label="Staff ID"
            disabled={busy}
          />
        </label>

        <div className={s.pinDisplay} aria-live="polite" aria-label="PIN entry">
          {pinDisplay}
        </div>

        <div className={s.pad} role="group" aria-label="PIN pad">
          {["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"].map((key) => (
            <button
              key={key}
              type="button"
              className={s.padKey}
              disabled={busy}
              aria-label={
                key === "clear" ? "Clear" : key === "back" ? "Backspace" : `Digit ${key}`
              }
              onClick={() => pinPress(key)}
            >
              {key === "clear" ? "C" : key === "back" ? "⌫" : key}
            </button>
          ))}
        </div>

        {error && (
          <p id={errorId} className={s.error} role="alert">
            {error}
          </p>
        )}

        <div className={s.actions}>
          <Button type="button" variant="ghost" size="lg" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            size="lg"
            disabled={busy}
            onClick={() => void submit()}
            data-testid="staff-switch-submit"
          >
            {busy ? "Switching…" : "Switch"}
          </Button>
        </div>
      </div>
    </div>
  );
}
