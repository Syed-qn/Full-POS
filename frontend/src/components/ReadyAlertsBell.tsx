import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { alertLine, useReadyAlerts } from "../lib/useReadyAlerts";
import s from "./ReadyAlertsBell.module.css";

function hhmm(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true });
}

/**
 * Top-bar "dish ready" bell for waiters and cashiers. Shows an unread badge and
 * a dropdown of recently-plated orders the current staff created (creator-only
 * routing is enforced server-side). The toast + chime fire from the hook; this
 * is the persistent glanceable surface.
 */
export function ReadyAlertsBell() {
  const navigate = useNavigate();
  const { enabled, alerts, unread, markAllSeen } = useReadyAlerts();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!enabled) return null;

  function toggle() {
    setOpen((v) => {
      const next = !v;
      if (next) markAllSeen();
      return next;
    });
  }

  return (
    <div className={s.wrap} ref={wrapRef}>
      <button
        type="button"
        className={s.bell}
        onClick={toggle}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={unread > 0 ? `${unread} orders ready` : "Order ready alerts"}
        title="Order ready alerts"
        data-testid="ready-bell"
      >
        🔔
        {unread > 0 && (
          <span className={s.badge} data-testid="ready-bell-badge">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className={s.panel} role="dialog" aria-label="Order ready alerts">
          <div className={s.head}>Ready</div>
          {alerts.length === 0 ? (
            <p className={s.empty}>No ready orders yet.</p>
          ) : (
            <ul className={s.list}>
              {alerts.map((a) => (
                <li key={`${a.order_id}-${a.ready_at}`}>
                  <button
                    type="button"
                    className={s.item}
                    onClick={() => {
                      setOpen(false);
                      navigate(`/orders/${a.order_id}`);
                    }}
                    data-testid={`ready-alert-${a.order_id}`}
                  >
                    <span className={s.itemLine}>{alertLine(a)}</span>
                    <span className={s.itemMeta}>
                      {a.order_number} · {hhmm(a.ready_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
