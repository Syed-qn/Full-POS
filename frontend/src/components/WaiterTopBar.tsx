import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { logout } from "../lib/auth";
import { useRestaurantName } from "../lib/brand";
import { getSessionRole, getStaffSession, isCashierRole } from "../lib/navAccess";
import { cyclePosTheme, usePosTheme } from "../lib/posTheme";
import { ReadyAlertsBell } from "./ReadyAlertsBell";
import { ViewBillDialog } from "./ViewBillDialog";
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
export type WaiterSection =
  | "dining"
  | "takeaway"
  | "whatsapp"
  | "delivery"
  | "online"
  | "kitchen"
  | "viewbill";

function clockLabel(d: Date): string {
  return d.toLocaleTimeString("en-US", {
    hour12: true,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
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
  // View Bill opens a lookup dialog in place — it doesn't navigate anywhere.
  const [billOpen, setBillOpen] = useState(false);
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
            onClick={() => navigate("/cashier/new-order?type=takeaway")}
          >
            Take Away
          </button>
        )}
        {showTakeaway && (
          <button
            type="button"
            className={`${s.tab} ${active === "delivery" ? s.tabActive : ""}`}
            aria-current={active === "delivery" ? "page" : undefined}
            data-testid="cashier-delivery-tab"
            onClick={() => navigate("/cashier/new-order?type=delivery")}
          >
            Home Delivery
          </button>
        )}
        {showTakeaway && (
          <button
            type="button"
            className={`${s.tab} ${active === "whatsapp" ? s.tabActive : ""}`}
            aria-current={active === "whatsapp" ? "page" : undefined}
            data-testid="cashier-whatsapp-tab"
            onClick={() => navigate("/cashier/whatsapp")}
          >
            WhatsApp
          </button>
        )}
        {showTakeaway && (
          <button
            type="button"
            className={`${s.tab} ${billOpen ? s.tabActive : ""}`}
            aria-haspopup="dialog"
            aria-expanded={billOpen}
            data-testid="cashier-viewbill-tab"
            onClick={() => setBillOpen(true)}
          >
            View Bill
          </button>
        )}
      </nav>

      {billOpen && <ViewBillDialog onClose={() => setBillOpen(false)} />}

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
        <ReadyAlertsBell />
        <span className={s.clock}>{clockLabel(now)}</span>
        <button
          type="button"
          className={s.themeBtn}
          title={`${staff?.name ?? "Waiter"} — sign out`}
          data-testid="waiter-signout"
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
        >
          ⏻ Sign out
        </button>
      </div>
    </header>
  );
}
