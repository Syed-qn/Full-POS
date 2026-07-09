import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiClient } from "../lib/apiClient";
import { isDesktopShell } from "../lib/desktopEnv";
import { getSessionRole, getStaffSession, isTrainingMode } from "../lib/navAccess";
import type { RestaurantOut } from "../lib/types";
import { AlertCenter, type AlertItem } from "./AlertCenter";
import s from "./TopBar.module.css";

const TITLES: Record<string, string> = {
  "/": "Live Ops",
  "/floor": "Floor Plan",
  "/orders": "Orders",
  "/new-order": "New Order",
  "/kds": "Kitchen Display",
  "/menu": "Menu",
  "/inventory": "Inventory",
  "/branches": "Branches",
  "/riders": "Riders",
  "/conversations": "Chats",
  "/channels": "Channels",
  "/customers": "Customers",
  "/staff": "Staff",
  "/tickets": "Complaints",
  "/payments": "Payments",
  "/coupons": "Coupons",
  "/compliance": "Compliance",
  "/reports": "Reports",
  "/ai": "AI Insights",
  "/analytics": "Analytics",
  "/marketing": "Marketing",
  "/reliability": "Reliability",
  "/settings": "Settings",
  "/predictions": "Demand Forecast",
  "/rider-app": "Rider App",
};

function titleFor(path: string): string {
  if (TITLES[path]) return TITLES[path];
  if (path.match(/^\/orders\/[^/]+\/pay$/)) return "Checkout";
  if (path.match(/^\/orders\/[^/]+$/)) return "Order Detail";
  const hit = Object.keys(TITLES)
    .filter((k) => k !== "/" && path.startsWith(k))
    .sort((a, b) => b.length - a.length)[0];
  return hit ? TITLES[hit] : "Full POS";
}

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
  const loc = useLocation();
  const [name, setName] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [alertsOpen, setAlertsOpen] = useState(false);
  const desktop = isDesktopShell();
  const alertCount = alerts.filter((a) => a.level !== "info").length;
  const role = getSessionRole();
  const staffMeta = getStaffSession();
  const training = isTrainingMode();

  useEffect(() => {
    apiClient
      .get<RestaurantOut>("/api/v1/me")
      .then((r) => setName(r.name))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className={s.bar} data-training={training ? "true" : "false"}>
      <div className={s.left}>
        <h1 className={s.pageTitle}>{titleFor(loc.pathname)}</h1>
        <span className={s.sep}>/</span>
        <span className={s.store} title="Restaurant / branch">
          {name ?? "…"}
        </span>
        {desktop && <span className={s.pill}>Local app</span>}
        {role && (
          <span className={s.pill} title="Active staff role">
            {staffMeta?.name ? `${staffMeta.name} · ${role}` : role}
          </span>
        )}
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
          className={s.staffBtn}
          disabled
          title="Staff PIN switch not available in this phase — sign out and use Login → Staff PIN"
          aria-label="Switch staff with PIN (not available yet)"
        >
          Staff
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
            Alerts
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
        <Link
          to="/reliability"
          className={s.reliabilityLink}
          title="System reliability"
          aria-label="System reliability status"
        >
          Status
        </Link>
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
