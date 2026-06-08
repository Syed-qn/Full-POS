import { NavLink } from "react-router-dom";
import s from "./NavSidebar.module.css";

const ITEMS: Array<{ to: string; label: string; icon: string }> = [
  { to: "/", label: "Home", icon: "🏠" },
  { to: "/orders", label: "Orders", icon: "📋" },
  { to: "/menu", label: "Menu", icon: "🍽️" },
  { to: "/riders", label: "Riders", icon: "🛵" },
  { to: "/conversations", label: "Chats", icon: "💬" },
  { to: "/analytics", label: "Reports", icon: "📊" },
  { to: "/settings", label: "Settings", icon: "⚙️" },
];

export function NavSidebar({ unread = 0 }: { unread?: number }) {
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
        </NavLink>
      ))}
    </nav>
  );
}
