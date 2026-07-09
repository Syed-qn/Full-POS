import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { logout } from "../lib/auth";
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

/** Spec main navigation order: daily first, manager/admin below. */
const GROUPS: NavGroup[] = [
  {
    id: "daily",
    label: "Daily",
    items: [
      { to: "/", label: "Live Ops", icon: "⌂" },
      { to: "/floor", label: "Floor Plan", icon: "▦" },
      { to: "/orders", label: "Orders", icon: "☰" },
      { to: "/new-order", label: "New Order", icon: "+" },
      { to: "/kds", label: "Kitchen", icon: "▣" },
      { to: "/payments", label: "Payments", icon: "¤" },
      { to: "/riders", label: "Riders", icon: "›" },
      { to: "/conversations", label: "Chats", icon: "◎" },
    ],
  },
  {
    id: "manage",
    label: "Manage",
    items: [
      { to: "/menu", label: "Menu", icon: "◇" },
      { to: "/inventory", label: "Inventory", icon: "▦" },
      { to: "/customers", label: "Customers", icon: "○" },
      { to: "/staff", label: "Staff", icon: "◎" },
      { to: "/marketing", label: "Marketing", icon: "✦" },
      { to: "/reports", label: "Reports", icon: "≡" },
      { to: "/ai", label: "AI Insights", icon: "◆" },
      { to: "/branches", label: "Branches", icon: "▣" },
      { to: "/channels", label: "Channels", icon: "⇄" },
      { to: "/reliability", label: "Reliability", icon: "⟳" },
      { to: "/settings", label: "Settings", icon: "⚙" },
    ],
  },
  {
    id: "more",
    label: "More",
    items: [
      { to: "/tickets", label: "Complaints", icon: "!" },
      { to: "/coupons", label: "Coupons", icon: "%" },
      { to: "/compliance", label: "Compliance", icon: "§" },
      { to: "/analytics", label: "Analytics", icon: "▴" },
      { to: "/predictions", label: "Forecast", icon: "◈" },
    ],
  },
];

const PREFETCH: Record<string, { queryKey: readonly unknown[]; queryFn: () => Promise<unknown> }> = {
  "/orders": {
    queryKey: ["orders", "list", { previewBatch: true, page: 1, limit: 20 }],
    queryFn: () => fetchOrders({ limit: 20, offset: 0 }),
  },
  "/customers": {
    queryKey: ["customers", "list", 1, ""],
    queryFn: () => listCustomers({ limit: 20, offset: 0 }),
  },
  "/riders": {
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

function groupContaining(path: string): string | null {
  for (const g of GROUPS) {
    for (const it of g.items) {
      if (it.to === path || (it.to !== "/" && path.startsWith(it.to))) return g.id;
    }
  }
  return path === "/" ? "daily" : null;
}

export function NavSidebar({ unread = 0 }: { unread?: number }) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { data: openTickets = 0 } = useOpenTicketsCountQuery();
  const role = useMemo(() => getSessionRole(), [location.pathname]);
  const visibleGroups = useMemo(
    () =>
      GROUPS.map((g) => ({ ...g, items: filterNavItems(g.items, role) })).filter(
        (g) => g.items.length > 0,
      ),
    [role],
  );
  const activeGroup = groupContaining(location.pathname);
  const [collapsed, setCollapsed] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const g of GROUPS) {
      init[g.id] = g.id === "daily" || g.id === activeGroup;
    }
    return init;
  });

  const desktop = useMemo(() => isDesktopShell(), []);

  function toggleGroup(id: string) {
    setOpenGroups((prev) => ({ ...prev, [id]: !prev[id] }));
  }

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
            <strong>{appProductName()}</strong>
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
        {collapsed ? "»" : "«"}
      </button>

      <div className={s.scroll}>
        {visibleGroups.map((group) => {
          const open = collapsed || (openGroups[group.id] ?? false);
          return (
            <div key={group.id} className={s.group}>
              {!collapsed && (
                <button
                  type="button"
                  className={s.groupHead}
                  onClick={() => toggleGroup(group.id)}
                  aria-expanded={open}
                  aria-controls={`nav-group-${group.id}`}
                >
                  <span>{group.label}</span>
                  <span className={s.chev} aria-hidden="true">
                    {open ? "▾" : "▸"}
                  </span>
                </button>
              )}
              {open && (
                <div className={s.groupBody} id={`nav-group-${group.id}`} role="group" aria-label={group.label}>
                  {group.items.map((it) => {
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
