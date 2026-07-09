import { useEffect, useRef } from "react";
import s from "./AlertCenter.module.css";

export type AlertItem = {
  id: string;
  level: "info" | "warning" | "critical";
  title: string;
  detail?: string;
  href?: string;
};

export function AlertCenter({
  alerts,
  onClose,
}: {
  alerts: AlertItem[];
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Light focus management: land on close so keyboard users can dismiss immediately.
    closeRef.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      // Light focus trap: Tab cycles within the panel when it has focusables.
      if (e.key !== "Tab" || !panelRef.current) return;
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      ref={panelRef}
      id="alert-center-panel"
      className={s.panel}
      role="dialog"
      aria-modal="true"
      aria-label="Alert center"
    >
      <div className={s.head}>
        <strong id="alert-center-title">Alerts</strong>
        <button
          ref={closeRef}
          type="button"
          className={s.close}
          onClick={onClose}
          aria-label="Close alerts"
        >
          ×
        </button>
      </div>
      {alerts.length === 0 ? (
        <p className={s.empty}>No active alerts</p>
      ) : (
        <ul className={s.list} aria-labelledby="alert-center-title">
          {alerts.map((a) => (
            <li key={a.id} className={`${s.item} ${s[a.level]}`}>
              <div className={s.title}>{a.title}</div>
              {a.detail && <div className={s.detail}>{a.detail}</div>}
            </li>
          ))}
        </ul>
      )}
      <p className={s.hint}>Late orders · low stock · sync · printer · channels</p>
    </div>
  );
}
