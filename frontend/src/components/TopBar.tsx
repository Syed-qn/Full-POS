import { useEffect, useState } from "react";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
import s from "./TopBar.module.css";

// Slim global top bar shown across all pages (next to the sidebar): a welcome +
// restaurant name on the left, a live clock on the right.
export function TopBar() {
  const [name, setName] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    apiClient.get<RestaurantOut>("/api/v1/me").then((r) => setName(r.name)).catch(() => {});
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className={s.bar}>
      <div className={s.welcome}>
        <span className={s.hi}>Welcome back,</span>
        <span className={s.name}>{name ?? "…"}</span>
      </div>
      <div className={s.clock}>
        <span className={s.time}>
          {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
        <span className={s.date}>
          {now.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}
        </span>
      </div>
    </header>
  );
}
