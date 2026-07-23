import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { logout } from "../lib/auth";
import { useRestaurantName } from "../lib/brand";
import { getSessionRole, getStaffSession, isCashierRole } from "../lib/navAccess";
import { cyclePosTheme, usePosTheme } from "../lib/posTheme";
import s from "./WaiterTopBar.module.css";

const THEME_LABEL: Record<string, string> = {
  dark: "🌙 Dark",
  light: "☀️ Light",
  blue: "🌊 Blue",
};

/**
 * Sections a waiter can be in. Only dine-in is exposed today — Take Away,
 * Home Delivery, Online and Kitchen are deliberately hidden: floor staff work
 * tables, while the other channels belong to the cashier terminal and the KDS.
 * The union is kept wider than the UI so re-enabling a section is a one-liner.
 */
export type WaiterSection = "dining" | "takeaway" | "delivery" | "online" | "kitchen";

function clockLabel(d: Date): string {
  return d.toLocaleTimeString("en-US", {
    hour12: true,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function initials(name?: string | null): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "WT";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Shared dark header for the waiter surfaces (floor + order screen).
 * Waiters run chrome-free, so this strip is their only global navigation.
 */
export function WaiterTopBar({ active }: { active: WaiterSection }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  // Return the "Dining" tab to the floor of the current namespace.
  const floorPath = pathname.startsWith("/cashier")
    ? "/cashier/floor"
    : pathname.startsWith("/waiter")
      ? "/waiter/floor"
      : "/floor";
  // Take Away is a cashier till (no table); waiters work dine-in only.
  const showTakeaway = isCashierRole();
  const [now, setNow] = useState(() => new Date());
  const brand = useRestaurantName();
  const staff = getStaffSession();
  const theme = usePosTheme();

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className={s.topBar} data-testid="waiter-top-bar">
      <div className={s.brand}>
        {/* Same blue POS mark as the manager sidebar — one identity across the
            whole app instead of a separate emoji badge per surface. */}
        <span className={s.brandMark}>POS</span>
        <span className={s.brandText}>
          {/* No placeholder: there is exactly one restaurant name and it comes
              from /me. A generic "RESTAURANT" fallback only ever showed while
              the request was in flight, and read as the name changing. */}
          <strong className={s.brandName}>{brand}</strong>
          {/* Which role is signed in, mirroring the sidebar's sub-line. */}
          <span className={s.brandRole}>{staff?.role ?? getSessionRole() ?? ""}</span>
        </span>
      </div>

      <nav className={s.tabs} aria-label="Sections">
        <button
          type="button"
          className={`${s.tab} ${active === "dining" ? s.tabActive : ""}`}
          aria-current={active === "dining" ? "page" : undefined}
          onClick={() => navigate(floorPath)}
        >
          Dining
        </button>
        {showTakeaway && (
          <button
            type="button"
            className={`${s.tab} ${active === "takeaway" ? s.tabActive : ""}`}
            aria-current={active === "takeaway" ? "page" : undefined}
            data-testid="cashier-takeaway-tab"
            onClick={() => navigate("/cashier/takeaway")}
          >
            Take Away
          </button>
        )}
      </nav>

      <div className={s.topRight}>
        <button
          type="button"
          className={s.themeBtn}
          title="Switch theme (dark → light → blue)"
          data-testid="waiter-theme"
          onClick={cyclePosTheme}
        >
          {THEME_LABEL[theme]}
        </button>
        <span className={s.online}>● ONLINE</span>
        <span className={s.clock}>{clockLabel(now)}</span>
        <button
          type="button"
          className={s.avatar}
          title={`${staff?.name ?? "Waiter"} — sign out`}
          data-testid="waiter-signout"
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
        >
          {initials(staff?.name)}
        </button>
      </div>
    </header>
  );
}
