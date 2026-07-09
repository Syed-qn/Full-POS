import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { apiClient } from "../lib/apiClient";
import { isDesktopShell } from "../lib/desktopEnv";
import type { RestaurantOut } from "../lib/types";
import s from "./TopBar.module.css";

const TITLES: Record<string, string> = {
  "/": "Live Ops",
  "/orders": "Orders",
  "/new-order": "New Order",
  "/kds": "Kitchen Display",
  "/menu": "Menu",
  "/inventory": "Inventory",
  "/branches": "Branches",
  "/riders": "Riders",
  "/conversations": "Conversations",
  "/channels": "Channels",
  "/customers": "Customers",
  "/staff": "Staff",
  "/tickets": "Complaints",
  "/payments": "Payments",
  "/coupons": "Coupons",
  "/compliance": "Compliance",
  "/reports": "Reports",
  "/ai": "AI Insights",
  "/analytics": "Analytics",
  "/marketing": "Marketing",
  "/reliability": "Reliability",
  "/settings": "Settings",
  "/predictions": "Demand Forecast",
};

function titleFor(path: string): string {
  if (TITLES[path]) return TITLES[path];
  const hit = Object.keys(TITLES)
    .filter((k) => k !== "/" && path.startsWith(k))
    .sort((a, b) => b.length - a.length)[0];
  return hit ? TITLES[hit] : "Full POS";
}

export function TopBar() {
  const loc = useLocation();
  const [name, setName] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());
  const desktop = isDesktopShell();

  useEffect(() => {
    apiClient
      .get<RestaurantOut>("/api/v1/me")
      .then((r) => setName(r.name))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className={s.bar}>
      <div className={s.left}>
        <h1 className={s.pageTitle}>{titleFor(loc.pathname)}</h1>
        <span className={s.sep}>/</span>
        <span className={s.store} title="Restaurant">
          {name ?? "…"}
        </span>
        {desktop && <span className={s.pill}>Local app</span>}
      </div>
      <div className={s.right}>
        <span className={s.date}>
          {now.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}
        </span>
        <span className={s.time}>
          {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </header>
  );
}
