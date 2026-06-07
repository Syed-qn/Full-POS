import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
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

const STATUS_COLORS: Record<string, string> = {
  pending:    "#6b7280",
  confirmed:  "#2563eb",
  preparing:  "#d97706",
  ready:      "#7c3aed",
  assigned:   "#0891b2",
  picked_up:  "#7c3aed",
  arriving:   "#6366f1",
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
    const revenue = orders.reduce((sum, o) => sum + Number(o.total_aed), 0);
    const aov = orders.length ? revenue / orders.length : 0;
    return {
      count: orders.length,
      revenue: `AED ${revenue.toFixed(0)}`,
      aov: `AED ${aov.toFixed(0)}`,
      delivered: delivered.length,
    };
  }, [orders]);

  const statusChart = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const o of orders) {
      counts[o.status] = (counts[o.status] || 0) + 1;
    }
    return Object.entries(counts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [orders]);

  const active = orders.filter((o) => ACTIVE.includes(o.status));
  const yellow = active.filter((o) => {
    const rem = remainingMs(o.sla_started_at);
    return rem <= 10 * 60_000 && rem > 5 * 60_000;
  });
  const red = active.filter((o) => remainingMs(o.sla_started_at) <= 5 * 60_000);

  const laneIds = new Set([...yellow, ...red].map((o) => o.id));
  const feedSource = orders.filter((o) => !laneIds.has(o.id));
  const feed = filter === "all" ? feedSource : feedSource.filter((o) => o.status === filter);

  return (
    <div className={s.screen}>
      {error != null && <SectionBanner tone="warning">Live updates paused — reconnecting.</SectionBanner>}

      <div className={s.kpiStrip}>
        <KPITile label="Orders Today" value={String(kpis.count)} accent="var(--chart-1)" />
        <KPITile label="Revenue Today" value={kpis.revenue} accent="var(--chart-3)" />
        <KPITile label="AOV" value={kpis.aov} accent="var(--chart-6)" />
        <KPITile label="Delivered" value={String(kpis.delivered)} accent="var(--sla-safe)" />
        <KPITile label="SLA %" value="—" accent="var(--chart-2)" />
        <KPITile label="Late Count" value="0" accent="var(--sla-warn)" />
        <KPITile label="Coupons Issued" value="0" accent="var(--sla-critical)" />
      </div>

      {/* Orders by status — Power BI bar chart */}
      <div className={s.chartPanel}>
        <span className="label-upper">Orders by Status</span>
        {statusChart.length === 0 ? (
          <div className={s.chartEmpty}>No orders yet.</div>
        ) : (
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={statusChart} margin={{ top: 8, right: 16, bottom: 0, left: 0 }} barSize={28}>
              <XAxis
                dataKey="name"
                tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: "var(--text-muted)" }}
                axisLine={false}
                tickLine={false}
                width={28}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--bg-surface)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "6px",
                  fontSize: 12,
                  boxShadow: "var(--shadow-sm)",
                }}
                cursor={{ fill: "rgba(37,99,235,0.06)" }}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {statusChart.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={STATUS_COLORS[entry.name] ?? "var(--chart-1)"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className={s.midRow}>
        <div className={s.mapPanel}>
          <span className="label-upper">Dispatch Map</span>
          <div className={s.mapBody}>
            <svg viewBox="0 0 400 260" className={s.mapSvg} aria-label="Tactical dispatch map">
              <rect x="0" y="0" width="400" height="260" fill="var(--map-bg)" />
              <g stroke="var(--map-road)" strokeWidth="1.5" opacity="0.6">
                <line x1="20" y1="60" x2="380" y2="70" />
                <line x1="40" y1="140" x2="360" y2="150" />
                <line x1="80" y1="30" x2="90" y2="230" />
                <line x1="300" y1="20" x2="310" y2="240" />
              </g>
              <rect x="320" y="180" width="70" height="70" fill="var(--map-water)" opacity="0.3" rx="4" />
              {active.length > 1 && (
                <polygon
                  points="90,80 140,110 180,70 160,130"
                  fill="var(--map-batch-hull)"
                  stroke="var(--map-batch-stroke)"
                  strokeWidth="1.5"
                  strokeDasharray="4 2"
                />
              )}
              {active.slice(0, 5).map((o, i) => {
                const rem = remainingMs(o.sla_started_at);
                const tier = rem <= 0 ? "breach" : rem < 5 * 60_000 ? "critical" : rem < 10 * 60_000 ? "warn" : "safe";
                const color = tier === "breach" ? "var(--sla-breach)" : tier === "critical" ? "var(--sla-critical)" : tier === "warn" ? "var(--sla-warn)" : "var(--sla-safe)";
                const x = 60 + (i % 3) * 90;
                const y = 55 + Math.floor(i / 3) * 55;
                return (
                  <g key={o.id}>
                    <circle cx={x} cy={y} r="5" fill={color} />
                    <text x={x + 8} y={y + 3} fontSize="9" fill="var(--text-primary)">{o.order_number?.slice(-3) || "ORD"}</text>
                  </g>
                );
              })}
              <circle cx="120" cy="95" r="4.5" fill="var(--map-rider-active)" className={s.riderDot} />
              <circle cx="195" cy="125" r="4" fill="var(--map-rider-stale)" />
              <circle cx="260" cy="88" r="4.5" fill="var(--map-rider-active)" className={s.riderDot} />
              <text x="12" y="248" fontSize="8" fill="var(--text-muted)">Riders • Orders (SLA) • Batches (hull)</text>
            </svg>
          </div>
        </div>

        <div className={s.slaBoard}>
          <span className="label-upper">SLA Board</span>
          <div className={s.lane}>
            <span className={s.laneLabel} style={{ color: "var(--sla-warn)" }}>Yellow Lane</span>
            <div data-testid="sla-lane-yellow" className={s.laneCards}>
              {yellow.length === 0 ? (
                <span className={s.clear}>All clear</span>
              ) : (
                yellow.map((o) => <SLAOrderCard key={o.id} order={o} onClick={() => nav(`/orders?id=${o.id}`)} />)
              )}
            </div>
          </div>
          <div className={s.lane}>
            <span className={s.laneLabel} style={{ color: "var(--sla-critical)" }}>Red Lane</span>
            <div data-testid="sla-lane-red" className={s.laneCards}>
              {red.length === 0 ? (
                <span className={s.clear}>All clear</span>
              ) : (
                red.map((o) => <SLAOrderCard key={o.id} order={o} onClick={() => nav(`/orders?id=${o.id}`)} />)
              )}
            </div>
          </div>
        </div>
      </div>

      <div className={s.feed}>
        <div className={s.feedHead}>
          <span className="label-upper">Live Order Feed</span>
          <div className={s.filters}>
            {(["all", ...ACTIVE] as const).map((st) => (
              <button
                key={st}
                className={`${s.filterPill} ${filter === st ? s.filterActive : ""}`}
                onClick={() => setFilter(st)}
              >
                {st}
              </button>
            ))}
          </div>
        </div>
        {feed.length === 0 ? (
          <div className={s.empty}>No orders yet today.</div>
        ) : (
          feed.map((o) => <LiveOrderRow key={o.id} order={o} onOpen={(id) => nav(`/orders?id=${id}`)} />)
        )}
      </div>
    </div>
  );
}
