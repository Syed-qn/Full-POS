import { useQueryClient } from "@tanstack/react-query";
import { NavLink, useNavigate } from "react-router-dom";
import { logout } from "../lib/auth";
import { fetchConversations } from "../lib/conversationsApi";
import { listCustomers } from "../lib/customerApi";
import { listIngredients } from "../lib/inventoryApi";
import { fetchOrders } from "../lib/ordersApi";
import { fetchRiders } from "../lib/ridersApi";
import { listTickets } from "../lib/ticketsApi";
import { useOpenTicketsCountQuery } from "../lib/queries/dashboard";
import s from "./NavSidebar.module.css";

const ITEMS: Array<{ to: string; label: string; icon: string }> = [
  { to: "/", label: "Home", icon: "🏠" },
  { to: "/orders", label: "Orders", icon: "📋" },
  { to: "/customers", label: "Customers", icon: "👥" },
  { to: "/new-order", label: "New Order", icon: "➕" },
  { to: "/menu", label: "Menu", icon: "🍽️" },
  { to: "/kds", label: "Kitchen", icon: "🍳" },
  { to: "/inventory", label: "Inventory", icon: "📦" },
  { to: "/branches", label: "Branches", icon: "🏢" },
  { to: "/riders", label: "Riders", icon: "🛵" },
  { to: "/staff", label: "Staff", icon: "🧑‍🍳" },
  { to: "/conversations", label: "Chats", icon: "💬" },
  { to: "/tickets", label: "Complaints", icon: "🎫" },
  { to: "/coupons", label: "Coupons", icon: "🏷️" },
  { to: "/payments", label: "Payments", icon: "💳" },
  { to: "/channels", label: "Channels", icon: "🔗" },
  { to: "/reliability", label: "Reliability", icon: "🛡️" },
  { to: "/compliance", label: "Compliance", icon: "📑" },
  { to: "/ai", label: "AI Insights", icon: "🤖" },
  { to: "/marketing", label: "Marketing", icon: "📣" },
  { to: "/analytics", label: "Analytics", icon: "📊" },
  { to: "/reports", label: "Reports", icon: "📈" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
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

export function NavSidebar({ unread = 0 }: { unread?: number }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: openTickets = 0 } = useOpenTicketsCountQuery();

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
    <nav className={s.nav}>
      <div className={s.logo}>OPS</div>
      {ITEMS.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          end={it.to === "/"}
          className={({ isActive }) => `${s.item} ${isActive ? s.active : ""}`}
          onMouseEnter={() => prefetchRoute(it.to)}
        >
          <span className={s.icon}>{it.icon}</span>
          {it.label}
          {it.to === "/conversations" && unread > 0 && (
            <span className={s.badge}>{unread}</span>
          )}
          {it.to === "/tickets" && openTickets > 0 && (
            <span className={s.badge}>{openTickets}</span>
          )}
        </NavLink>
      ))}
      <button type="button" className={`${s.item} ${s.logout}`} onClick={handleLogout}>
        <span className={s.icon}>🚪</span>
        Logout
      </button>
    </nav>
  );
}
