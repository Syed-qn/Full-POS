import { NavLink } from "react-router-dom";
import s from "./NavSidebar.module.css";

const ITEMS: Array<{ to: string; label: string }> = [
  { to: "/", label: "Live Ops" },
  { to: "/orders", label: "Orders" },
  { to: "/menu", label: "Menu" },
  { to: "/riders", label: "Riders" },
  { to: "/conversations", label: "Conversations" },
  { to: "/analytics", label: "Analytics" },
  { to: "/settings", label: "Settings" },
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
          {it.label}
          {it.to === "/conversations" && unread > 0 && (
            <span className={s.badge}>{unread}</span>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
