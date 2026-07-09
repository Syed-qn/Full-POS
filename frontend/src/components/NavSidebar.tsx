import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { logout } from "../lib/auth";
import { appProductName, isDesktopShell } from "../lib/desktopEnv";
import { fetchConversations } from "../lib/conversationsApi";
import { listCustomers } from "../lib/customerApi";
import { listIngredients } from "../lib/inventoryApi";
import { fetchOrders } from "../lib/ordersApi";
import { fetchRiders } from "../lib/ridersApi";
import { listTickets } from "../lib/ticketsApi";
import { useOpenTicketsCountQuery } from "../lib/queries/dashboard";
import s from "./NavSidebar.module.css";

type NavItem = { to: string; label: string; icon: string };
type NavGroup = { id: string; label: string; items: NavItem[] };

const GROUPS: NavGroup[] = [
  {
    id: "floor",
    label: "Floor",
    items: [
      { to: "/", label: "Live Ops", icon: "⌂" },
      { to: "/orders", label: "Orders", icon: "☰" },
      { to: "/new-order", label: "New Order", icon: "+" },
      { to: "/kds", label: "Kitchen", icon: "▣" },
    ],
  },
  {
    id: "catalog",
    label: "Catalog & stock",
    items: [
      { to: "/menu", label: "Menu", icon: "◇" },
      { to: "/inventory", label: "Inventory", icon: "▦" },
      { to: "/branches", label: "Branches", icon: "▣" },
    ],
  },
  {
    id: "delivery",
    label: "Delivery",
    items: [
      { to: "/riders", label: "Riders", icon: "›" },
      { to: "/conversations", label: "Chats", icon: "◎" },
      { to: "/channels", label: "Channels", icon: "⇄" },
    ],
  },
  {
    id: "people",
    label: "People",
    items: [
      { to: "/customers", label: "Customers", icon: "○" },
      { to: "/staff", label: "Staff", icon: "◎" },
      { to: "/tickets", label: "Complaints", icon: "!" },
    ],
  },
  {
    id: "money",
    label: "Money",
    items: [
      { to: "/payments", label: "Payments", icon: "¤" },
      { to: "/coupons", label: "Coupons", icon: "%" },
      { to: "/compliance", label: "Compliance", icon: "§" },
      { to: "/reports", label: "Reports", icon: "≡" },
    ],
  },
  {
    id: "intelligence",
    label: "AI & data",
    items: [
      { to: "/ai", label: "AI Insights", icon: "◆" },
      { to: "/analytics", label: "Analytics", icon: "▴" },
      { to: "/marketing", label: "Marketing", icon: "✦" },
      { to: "/predictions", label: "Forecast", icon: "◈" },
    ],
  },
  {
    id: "system",
    label: "System",
    items: [
      { to: "/reliability", label: "Reliability", icon: "⟳" },
      { to: "/settings", label: "Settings", icon: "⚙" },
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
  return path === "/" ? "floor" : null;
}

export function NavSidebar({ unread = 0 }: { unread?: number }) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { data: openTickets = 0 } = useOpenTicketsCountQuery();
  const activeGroup = groupContaining(location.pathname);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const g of GROUPS) {
      // Floor + active group open; rest collapsed for terminal density
      init[g.id] = g.id === "floor" || g.id === activeGroup;
    }
    return init;
  });

  const desktop = useMemo(() => isDesktopShell(), []);

  function toggleGroup(id: string) {
    setOpenGroups((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  function prefetchRoute(to: string) {
    const entry = PREFETCH[to];
    if (!entry) return;
    void queryClient.prefetchQuery(entry);
  }

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <nav className={s.nav} aria-label="Main">
      <div className={s.logo}>
        <span className={s.logoMark}>POS</span>
        <div className={s.logoText}>
          <strong>{appProductName()}</strong>
          <span>{desktop ? "Desktop" : "Manager"}</span>
        </div>
      </div>

      <div className={s.scroll}>
        {GROUPS.map((group) => {
          const open = openGroups[group.id] ?? false;
          return (
            <div key={group.id} className={s.group}>
              <button
                type="button"
                className={s.groupHead}
                onClick={() => toggleGroup(group.id)}
                aria-expanded={open}
              >
                <span>{group.label}</span>
                <span className={s.chev}>{open ? "▾" : "▸"}</span>
              </button>
              {open && (
                <div className={s.groupBody}>
                  {group.items.map((it) => (
                    <NavLink
                      key={it.to}
                      to={it.to}
                      end={it.to === "/"}
                      className={({ isActive }) => `${s.item} ${isActive ? s.active : ""}`}
                      onMouseEnter={() => prefetchRoute(it.to)}
                    >
                      <span className={s.icon} aria-hidden>
                        {it.icon}
                      </span>
                      <span className={s.label}>{it.label}</span>
                      {it.to === "/conversations" && unread > 0 && (
                        <span className={s.badge}>{unread}</span>
                      )}
                      {it.to === "/tickets" && openTickets > 0 && (
                        <span className={s.badge}>{openTickets}</span>
                      )}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <button type="button" className={`${s.item} ${s.logout}`} onClick={handleLogout}>
        <span className={s.icon}>⎋</span>
        <span className={s.label}>Sign out</span>
      </button>
    </nav>
  );
}
