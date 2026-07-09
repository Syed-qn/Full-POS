import { Link } from "react-router-dom";
import { useOfflineStatus } from "../lib/useOfflineStatus";
import s from "./OfflineLimitsBanner.module.css";

/** Core ops surfaces that declare offline capability limits (Phase 5A). */
export type OfflineSurface =
  | "new-order"
  | "orders"
  | "kds"
  | "live-ops"
  | "checkout"
  | "payments";

type Limits = { works: string[]; blocked: string[] };

const SURFACE_LIMITS: Record<OfflineSurface, Limits> = {
  "new-order": {
    works: ["Browse cart layout", "Local draft edits on this device"],
    blocked: ["Customer lookup", "Cloud order submit", "Live fee tiers refresh"],
  },
  orders: {
    works: ["Last loaded order cards", "Open already-fetched detail"],
    blocked: ["List refresh", "Status changes to cloud", "Search against server"],
  },
  kds: {
    works: ["Visible tickets on screen", "Local queue (desktop shell)"],
    blocked: ["Ticket refresh", "Bump/recall cloud sync", "Printer health poll"],
  },
  "live-ops": {
    works: ["Last known board snapshot"],
    blocked: ["Live SLA refresh", "Fleet map updates", "Dispatch reassignment"],
  },
  checkout: {
    works: ["View bill if already loaded", "Cash queue on desktop shell"],
    blocked: ["Card / online / wallet / payment links", "Gift card redeem to cloud"],
  },
  payments: {
    works: ["View last drawer snapshot if loaded"],
    blocked: ["Till charge to cloud", "Payment links", "Reconciliation", "Billing settings save"],
  },
};

export function OfflineLimitsBanner({
  surface,
  forceOffline,
}: {
  surface: OfflineSurface;
  /** Test / story override — when set, skips live status for visibility. */
  forceOffline?: boolean;
}) {
  const status = useOfflineStatus();
  const offline = forceOffline ?? status.offline;

  if (!offline) return null;

  const limits = SURFACE_LIMITS[surface];
  const pendingLabel =
    status.pendingCount > 0
      ? `${status.pendingCount} change${status.pendingCount === 1 ? "" : "s"} queued for sync`
      : status.isDesktop
        ? "Local queue ready when you reconnect"
        : "Reconnect to resume cloud ops";

  return (
    <div
      className={s.banner}
      role="status"
      aria-live="polite"
      data-testid="offline-limits-banner"
      data-surface={surface}
    >
      <div className={s.head}>
        <span className={s.badge}>Offline</span>
        <span className={s.title}>Limited operations on this screen</span>
        <span className={s.pending}>{pendingLabel}</span>
      </div>
      <div className={s.cols}>
        <div className={s.col}>
          <div className={s.colLabel}>Still works</div>
          <ul className={s.list}>
            {limits.works.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div className={s.col}>
          <div className={`${s.colLabel} ${s.colLabelBlocked}`}>Blocked until online</div>
          <ul className={s.list}>
            {limits.blocked.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
      <div className={s.foot}>
        <Link to="/reliability" className={s.link}>
          Reliability · queue & conflicts
        </Link>
      </div>
    </div>
  );
}
