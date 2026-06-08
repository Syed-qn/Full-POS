import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { KPITile } from "../components/KPITile";
import { LiveOrderRow } from "../components/LiveOrderRow";
import { SectionBanner } from "../components/SectionBanner";
import { SLAOrderCard } from "../components/SLAOrderCard";
import { fetchOrders } from "../lib/ordersApi";
import { remainingMs } from "../lib/sla";
import type { OrderOut } from "../lib/types";
import { usePoll } from "../lib/usePoll";
import s from "./LiveOpsScreen.module.css";

const ACTIVE: OrderOut["status"][] = [
  "confirmed", "preparing", "ready", "assigned", "picked_up", "arriving",
];

// Friendly labels for status — plain English
const STATUS_LABEL: Record<string, string> = {
  confirmed:  "New",
  preparing:  "Cooking",
  ready:      "Ready",
  assigned:   "With Rider",
  picked_up:  "On the Way",
  arriving:   "Arriving",
  delivered:  "Delivered",
  cancelled:  "Cancelled",
};

const STATUS_COLORS: Record<string, string> = {
  confirmed:  "#2563eb",
  preparing:  "#d97706",
  ready:      "#7c3aed",
  assigned:   "#0891b2",
  picked_up:  "#6366f1",
  arriving:   "#059669",
  delivered:  "#16a34a",
  cancelled:  "#dc2626",
};

export function LiveOpsScreen() {
  const { data, error } = usePoll<OrderOut[]>(fetchOrders, 4000);
  const orders = data ?? [];
  const nav = useNavigate();
  const [filter, setFilter] = useState<OrderOut["status"] | "all">("all");

  const kpis = useMemo(() => {
    const delivered = orders.filter((o) => o.status === "delivered");
    const active = orders.filter((o) => ACTIVE.includes(o.status));
    const revenue = orders.filter((o) => o.status === "delivered")
      .reduce((sum, o) => sum + Number(o.total_aed), 0);
    return {
      total: orders.length,
      active: active.length,
      delivered: delivered.length,
      revenue: `AED ${revenue.toFixed(0)}`,
    };
  }, [orders]);

  // Pie chart data — only statuses that have orders
  const pieData = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const o of orders) {
      counts[o.status] = (counts[o.status] || 0) + 1;
    }
    return Object.entries(counts).map(([status, value]) => ({
      name: STATUS_LABEL[status] ?? status,
      value,
      color: STATUS_COLORS[status] ?? "#9ca3af",
    }));
  }, [orders]);

  const activeOrders = orders.filter((o) => ACTIVE.includes(o.status));
  const urgent = activeOrders.filter((o) => {
    const rem = remainingMs(o.sla_started_at);
    return rem <= 10 * 60_000;
  });
  const laneIds = new Set(urgent.map((o) => o.id));
  const feedSource = orders.filter((o) => !laneIds.has(o.id));
  const feed = filter === "all" ? feedSource : feedSource.filter((o) => o.status === filter);

  return (
    <div className={s.screen}>
      {error != null && <SectionBanner tone="warning">Connection lost — reconnecting…</SectionBanner>}

      {/* ── Big friendly numbers ─── */}
      <div className={s.kpiStrip}>
        <KPITile label="Orders Today" value={String(kpis.total)} accent="var(--chart-1)" />
        <KPITile label="Active Now" value={String(kpis.active)} accent="var(--sla-warn)" />
        <KPITile label="Delivered" value={String(kpis.delivered)} accent="var(--sla-safe)" />
        <KPITile label="Money Collected" value={kpis.revenue} accent="var(--chart-3)" />
      </div>

      {/* ── Order status breakdown — simple pie + legend ─── */}
      {orders.length > 0 && (
        <div className={s.statusCard}>
          <div className={s.cardTitle}>Where are the orders?</div>
          <div className={s.statusBody}>
            <ResponsiveContainer width={180} height={180}>
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={2}
                >
                  {pieData.map((entry, i) => (
                    <Cell key={i} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: "#fff",
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "8px",
                    fontSize: 13,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className={s.legend}>
              {pieData.map((d) => (
                <div key={d.name} className={s.legendRow}>
                  <span className={s.legendDot} style={{ background: d.color }} />
                  <span className={s.legendLabel}>{d.name}</span>
                  <span className={s.legendCount}>{d.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Urgent orders (need attention) ─── */}
      {urgent.length > 0 && (
        <div className={s.urgentCard}>
          <div className={s.urgentTitle}>⚠️ Needs Attention Now</div>
          <div className={s.urgentList}>
            {urgent.map((o) => (
              <SLAOrderCard key={o.id} order={o} onClick={() => nav(`/orders?id=${o.id}`)} />
            ))}
          </div>
        </div>
      )}

      {/* ── Order feed ─── */}
      <div className={s.feed}>
        <div className={s.feedHead}>
          <span className={s.feedTitle}>All Orders</span>
          <div className={s.filters}>
            <button
              className={`${s.filterPill} ${filter === "all" ? s.filterActive : ""}`}
              onClick={() => setFilter("all")}
            >All</button>
            {ACTIVE.map((st) => (
              <button
                key={st}
                className={`${s.filterPill} ${filter === st ? s.filterActive : ""}`}
                onClick={() => setFilter(st)}
              >
                {STATUS_LABEL[st] ?? st}
              </button>
            ))}
          </div>
        </div>
        {feed.length === 0 ? (
          <div className={s.empty}>
            {orders.length === 0
              ? "No orders yet today. Orders will appear here when customers message."
              : "Nothing in this category right now."}
          </div>
        ) : (
          feed.map((o) => <LiveOrderRow key={o.id} order={o} onOpen={(id) => nav(`/orders?id=${id}`)} />)
        )}
      </div>
    </div>
  );
}
