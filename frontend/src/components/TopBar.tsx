import { useEffect, useState } from "react";
import {
  APP_THEME_ICON,
  APP_THEME_LABEL,
  cycleAppTheme,
  nextAppTheme,
  useAppTheme,
} from "../lib/appTheme";
import { isDesktopShell } from "../lib/desktopEnv";
import { isTrainingMode } from "../lib/navAccess";
import { AlertCenter, type AlertItem } from "./AlertCenter";
import s from "./TopBar.module.css";

export function TopBar({
  offline = false,
  pendingCount = 0,
  alerts = [],
}: {
  offline?: boolean;
  /** Desktop local queue depth (shown when > 0). */
  pendingCount?: number;
  alerts?: AlertItem[];
}) {
  const [now, setNow] = useState(() => new Date());
  const [alertsOpen, setAlertsOpen] = useState(false);
  const theme = useAppTheme();
  const nextTheme = nextAppTheme();
  const desktop = isDesktopShell();
  const alertCount = alerts.filter((a) => a.level !== "info").length;
  const training = isTrainingMode();

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className={s.bar} data-training={training ? "true" : "false"}>
      <div className={s.left}>
        {/* Page title lives in each screen's PageHeader — no duplicate breadcrumb here. */}
        {desktop && <span className={s.pill}>Local app</span>}
        {/* The staff-name · role chip lived here, but the sidebar header
            already shows both, so it was the same fact twice on one screen. */}
        {training && (
          <span
            className={s.trainingBadge}
            title="Training mode — orders excluded from real sales KPIs"
            role="status"
          >
            Training
          </span>
        )}
        {offline && (
          <span
            className={s.offlineBadge}
            title="Device offline — limited operations"
            role="status"
            aria-live="polite"
          >
            Offline
          </span>
        )}
        {!offline && pendingCount > 0 && (
          <span
            className={s.pendingBadge}
            title="Queued writes waiting to sync"
            data-testid="topbar-pending"
            role="status"
          >
            {pendingCount} pending
          </span>
        )}
      </div>
      <div className={s.right}>
        <button
          type="button"
          className={s.alertBtn}
          onClick={cycleAppTheme}
          title={`Theme: ${APP_THEME_LABEL[theme]} — switch to ${APP_THEME_LABEL[nextTheme]}`}
          aria-label={`Theme ${APP_THEME_LABEL[theme]}, switch to ${APP_THEME_LABEL[nextTheme]}`}
          data-testid="dashboard-theme"
        >
          <span aria-hidden="true" style={{ fontSize: 20, lineHeight: 1 }}>
            {APP_THEME_ICON[theme]}
          </span>
        </button>
        <div className={s.alertWrap}>
          <button
            type="button"
            className={s.alertBtn}
            onClick={() => setAlertsOpen((o) => !o)}
            aria-label={
              alertCount > 0
                ? `Alert center, ${alertCount} active`
                : "Alert center"
            }
            aria-expanded={alertsOpen}
            aria-haspopup="dialog"
            aria-controls={alertsOpen ? "alert-center-panel" : undefined}
          >
            <span aria-hidden="true" style={{ fontSize: 20, lineHeight: 1 }}>🔔</span>
            {alertCount > 0 && (
              <span className={s.alertCount} aria-hidden="true">
                {alertCount}
              </span>
            )}
          </button>
          {alertsOpen && (
            <AlertCenter
              alerts={alerts}
              onClose={() => setAlertsOpen(false)}
            />
          )}
        </div>
        <time
          className={s.date}
          dateTime={now.toISOString()}
          aria-label={now.toLocaleDateString([], {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric",
          })}
        >
          {now.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}
        </time>
        <time
          className={s.time}
          dateTime={now.toISOString()}
          aria-label={now.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })}
        >
          {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </time>
      </div>
    </header>
  );
}
