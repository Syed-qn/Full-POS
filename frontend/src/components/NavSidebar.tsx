import { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { logout } from "../lib/auth";
import { listTickets } from "../lib/ticketsApi";
import s from "./NavSidebar.module.css";

const ITEMS: Array<{ to: string; label: string; icon: string }> = [
  { to: "/", label: "Home", icon: "🏠" },
  { to: "/orders", label: "Orders", icon: "📋" },
  { to: "/customers", label: "Customers", icon: "👥" },
  { to: "/new-order", label: "New Order", icon: "➕" },
  { to: "/menu", label: "Menu", icon: "🍽️" },
  { to: "/riders", label: "Riders", icon: "🛵" },
  { to: "/conversations", label: "Chats", icon: "💬" },
  { to: "/tickets", label: "Complaints", icon: "🎫" },
  { to: "/coupons", label: "Coupons", icon: "🏷️" },
  { to: "/marketing", label: "Marketing", icon: "📣" },
  { to: "/analytics", label: "Reports", icon: "📊" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
];

export function NavSidebar({ unread = 0 }: { unread?: number }) {
  const navigate = useNavigate();
  const [openTickets, setOpenTickets] = useState(0);

  // Live open-complaint count for the nav badge — polls every 30s so a complaint
  // raised while the manager is on another page surfaces without a reload.
  useEffect(() => {
    let cancelled = false;
    const refresh = () =>
      listTickets("open")
        .then((t) => !cancelled && setOpenTickets(t.length))
        .catch(() => {});
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

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
