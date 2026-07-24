import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { logout } from "../lib/auth";
import { useRestaurantName } from "../lib/brand";
import { appProductName, isDesktopShell } from "../lib/desktopEnv";
import { fetchConversations } from "../lib/conversationsApi";
import { listCustomers } from "../lib/customerApi";
import { listIngredients } from "../lib/inventoryApi";
import { canAccess, filterNavItems, getSessionRole } from "../lib/navAccess";
import { fetchOrders } from "../lib/ordersApi";
import { fetchRiders } from "../lib/ridersApi";
import { listTickets } from "../lib/ticketsApi";
import { useOpenTicketsCountQuery } from "../lib/queries/dashboard";
import s from "./NavSidebar.module.css";

type NavItem = { to: string; label: string; icon: string };
type NavGroup = { id: string; label: string; items: NavItem[] };

/** Routes that are live today. Everything else in the nav renders inert with a
 *  "Soon" pill until it ships. */
const LIVE_ROUTES = new Set<string>([
  "/", // Live Ops
  "/floor", // Floor Plan
  "/orders", // Orders
  "/kds", // Kitchen
  "/conversations", // Chats
  "/marketing", // Promotion
  "/rider-management", // Rider Management
  "/menu", // Menu
  "/customer-management", // Customer Management
  "/settings", // Settings
  "/waiter-management", // Waiter Management
  "/coupons", // Coupons
  "/tickets", // Complaints
  "/forecast", // Forecast
]);

/** Spec main navigation order: daily ops first, then the WhatsApp channel,
 *  then the manager/admin surface, then the long tail. */
const GROUPS: NavGroup[] = [
  {
    id: "daily",
    label: "Daily",
    items: [
      { to: "/", label: "Live Ops", icon: "⌂" },
      { to: "/floor", label: "Floor Plan", icon: "▦" },
      { to: "/new-order", label: "New Order", icon: "+" },
      { to: "/orders", label: "Orders", icon: "☰" },
      { to: "/kds", label: "Kitchen", icon: "▣" },
      { to: "/menu", label: "Menu", icon: "◇" },
    ],
  },
  {
    id: "whatsapp",
    /** The WhatsApp channel: chats, promotion, and the customer-facing
     *  complaint + coupon flows that run over WhatsApp. */
    label: "WhatsApp",
    items: [
      { to: "/conversations", label: "Chats", icon: "◎" },
      { to: "/marketing", label: "Promotion", icon: "✦" },
      { to: "/tickets", label: "Complaints", icon: "!" },
      { to: "/coupons", label: "Coupons", icon: "%" },
    ],
  },
  {
    id: "users",
    /** People the restaurant manages: customers, delivery riders, floor waiters. */
    label: "User Management",
    items: [
      { to: "/customer-management", label: "Customer Management", icon: "○" },
      { to: "/rider-management", label: "Rider Management", icon: "›" },
      { to: "/waiter-management", label: "Waiter Management", icon: "◎" },
    ],
  },
  {
    id: "manage",
    /** Owner/manager admin surface (R5). Label stays Manage for floor roles that see partial list. */
    label: "Manage",
    items: [
      { to: "/inventory", label: "Inventory", icon: "▦" },
      { to: "/reports", label: "Reports", icon: "≡" },
      { to: "/ai", label: "AI Insights", icon: "◆" },
      { to: "/branches", label: "Branches", icon: "▣" },
      { to: "/channels", label: "Channels", icon: "⇄" },
      { to: "/reliability", label: "Reliability", icon: "⟳" },
    ],
  },
  {
    id: "more",
    label: "More",
    items: [
      { to: "/payments", label: "Payments", icon: "¤" },
      { to: "/compliance", label: "Compliance", icon: "§" },
      { to: "/analytics", label: "Analytics", icon: "▴" },
      { to: "/forecast", label: "Forecast", icon: "◈" },
    ],
  },
];

const PREFETCH: Record<string, { queryKey: readonly unknown[]; queryFn: () => Promise<unknown> }> = {
  "/orders": {
    queryKey: ["orders", "list", { previewBatch: true, page: 1, limit: 20 }],
    queryFn: () => fetchOrders({ limit: 20, offset: 0 }),
  },
  "/customer-management": {
    queryKey: ["customers", "list", 1, ""],
    queryFn: () => listCustomers({ limit: 20, offset: 0 }),
  },
  "/rider-management": {
    queryKey: ["riders", "list"],
    queryFn: fetchRiders,
  },
  "/inventory": {
    queryKey: ["inventory", "ingredients"],
    queryFn: listIngredients,
  },
  "/conversations": {
    queryKey: ["conversations", "list"],
    queryFn: fetchConversations,
  },
  "/tickets": {
    queryKey: ["tickets", "list", ""],
    queryFn: () => listTickets(undefined, undefined),
  },
};

export function NavSidebar({ unread = 0 }: { unread?: number }) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const role = useMemo(() => getSessionRole(), [location.pathname]);
  // Only fetch the open-tickets badge for roles that can open /tickets — otherwise
  // the manager-only endpoint 401s and the global auth interceptor logs the
  // (valid) staff session straight back out to /login.
  const { data: openTickets = 0 } = useOpenTicketsCountQuery(canAccess("/tickets", role));
  const visibleGroups = useMemo(
    () =>
      GROUPS.map((g) => {
        const items = filterNavItems(g.items, role);
        // R5: owner/manager see Manage as "Admin" for clarity.
        const label =
          g.id === "manage" && (role == null || role === "owner" || role === "manager")
            ? "Admin"
            : g.label;
        return { ...g, label, items };
      }).filter((g) => g.items.length > 0),
    [role],
  );
  const restaurantName = useRestaurantName();
  const [collapsed, setCollapsed] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});

  function toggleGroup(id: string) {
    setCollapsedGroups((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  const desktop = useMemo(() => isDesktopShell(), []);

  function prefetchRoute(to: string) {
    if (!canAccess(to, role)) return;
    const entry = PREFETCH[to];
    if (!entry) return;
    void queryClient.prefetchQuery(entry);
  }

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <nav
      className={`${s.nav} ${collapsed ? s.collapsed : ""}`}
      aria-label="Main"
      data-collapsed={collapsed ? "true" : "false"}
      data-role={role ?? "full"}
    >
      <div className={s.logo}>
        <span className={s.logoMark}>POS</span>
        {!collapsed && (
          <div className={s.logoText}>
            {/* The RESTAURANT name, same source as the waiter/cashier top bar,
                so the chrome never shows two different brands. Falls back to
                the product name only until /me answers. */}
            <strong>{restaurantName || appProductName()}</strong>
            <span>{desktop ? "Desktop" : role ? role : "Manager"}</span>
          </div>
        )}
      </div>

      <button
        type="button"
        className={s.collapseBtn}
        onClick={() => setCollapsed((c) => !c)}
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        aria-expanded={!collapsed}
      >
        {collapsed ? "›" : "‹"}
      </button>

      <div className={s.scroll}>
        {visibleGroups.map((group) => {
          const groupOpen = !collapsedGroups[group.id];
          return (
            <div key={group.id} className={s.group}>
              {!collapsed && (
                <button
                  type="button"
                  className={s.groupHead}
                  onClick={() => toggleGroup(group.id)}
                  aria-expanded={groupOpen}
                  aria-controls={`nav-group-${group.id}`}
                >
                  <span>{group.label}</span>
                  <span className={s.chev} aria-hidden="true">
                    {groupOpen ? "▾" : "▸"}
                  </span>
                </button>
              )}
              {(collapsed || groupOpen) && (
                <div className={s.groupBody} id={`nav-group-${group.id}`} role="group" aria-label={group.label}>
                  {group.items.map((it) => {
                    // Not-yet-shipped screens render as an inert row with a "Soon"
                    // pill instead of a navigable link.
                    if (!LIVE_ROUTES.has(it.to)) {
                      return (
                        <span
                          key={it.to}
                          className={`${s.item} ${s.itemDisabled}`}
                          title={`${it.label} — coming soon`}
                          aria-label={`${it.label}, coming soon`}
                          aria-disabled="true"
                        >
                          <span className={s.icon} aria-hidden="true">
                            {it.icon}
                          </span>
                          {!collapsed && <span className={s.label}>{it.label}</span>}
                          {!collapsed && (
                            <span className={s.soon} aria-hidden="true">
                              Soon
                            </span>
                          )}
                        </span>
                      );
                    }
                    // Collapsed = icon-only; title + aria-label keep an accessible name.
                    const a11yName =
                      it.to === "/conversations" && unread > 0
                        ? `${it.label}, ${unread} unread`
                        : it.to === "/tickets" && openTickets > 0
                          ? `${it.label}, ${openTickets} open`
                          : it.label;
                    return (
                      <NavLink
                        key={it.to}
                        to={it.to}
                        end={it.to === "/"}
                        title={a11yName}
                        aria-label={a11yName}
                        className={({ isActive }) => `${s.item} ${isActive ? s.active : ""}`}
                        onMouseEnter={() => prefetchRoute(it.to)}
                      >
                        <span className={s.icon} aria-hidden="true">
                          {it.icon}
                        </span>
                        {!collapsed && <span className={s.label}>{it.label}</span>}
                        {!collapsed && it.to === "/conversations" && unread > 0 && (
                          <span className={s.badge} aria-hidden="true">
                            {unread}
                          </span>
                        )}
                        {!collapsed && it.to === "/tickets" && openTickets > 0 && (
                          <span className={s.badge} aria-hidden="true">
                            {openTickets}
                          </span>
                        )}
                      </NavLink>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Settings + Sign out are pinned to the bottom, below the nav list. */}
      {canAccess("/settings", role) && (
        <NavLink
          to="/settings"
          title="Settings"
          aria-label="Settings"
          className={({ isActive }) => `${s.item} ${s.footItem} ${isActive ? s.active : ""}`}
          onMouseEnter={() => prefetchRoute("/settings")}
        >
          <span className={s.icon} aria-hidden="true">
            ⚙
          </span>
          {!collapsed && <span className={s.label}>Settings</span>}
        </NavLink>
      )}

      <button
        type="button"
        className={`${s.item} ${s.logout}`}
        onClick={handleLogout}
        title="Sign out"
        aria-label="Sign out"
      >
        <span className={s.icon} aria-hidden="true">
          ⎋
        </span>
        {!collapsed && <span className={s.label}>Sign out</span>}
      </button>
    </nav>
  );
}
