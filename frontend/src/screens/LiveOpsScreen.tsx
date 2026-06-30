import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CompactTable, type Column } from "../components/CompactTable";
import { DispatchKpiPanel } from "../components/DispatchKpiPanel";
import { LiveOpsMap } from "../components/LiveOpsMap";
import { SectionBanner } from "../components/SectionBanner";
import { SLAOrderCard } from "../components/SLAOrderCard";
import { StatusPill } from "../components/StatusPill";
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
  draft:                "Draft",
  pending_confirmation: "Pending",
  confirmed:            "New",
  preparing:            "Cooking",
  ready:                "Ready",
  assigned:             "With Rider",
  picked_up:            "On the Way",
  arriving:             "Arriving",
  delivered:            "Delivered",
  cancelled:            "Cancelled",
  on_resale:            "On Resale",
};

// Greyscale ramp (light = earlier in the flow, dark = completed) so the donut
// stays cohesive with the white & grey theme.
const STATUS_COLORS: Record<string, string> = {
  draft:                "#cbd0d6",
  pending_confirmation: "#b3b9c0",
  confirmed:            "#9aa0a8",
  preparing:            "#7e858e",
  ready:                "#656c75",
  assigned:             "#525964",
  picked_up:            "#444b54",
  arriving:             "#363c44",
  delivered:            "#23272f",
  cancelled:            "#a7adb4",
  on_resale:            "#8b929b",
};

// Loading skeleton mirroring the home layout: 4 KPI cards + a donut card and
// the orders-feed card. Shown until the first poll resolves.
function LiveOpsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading live operations">
      <div className={s.kpiStrip}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className={s.stat}>
            <div className={s.statTop}>
              <span className={`${s.sk} ${s.skIcon}`} />
              <span className={`${s.sk} ${s.skLabel}`} />
            </div>
            <span className={`${s.sk} ${s.skValue}`} />
            <span className={`${s.sk} ${s.skSub}`} />
          </div>
        ))}
      </div>

      <div className={s.grid2} style={{ marginTop: 20 }}>
        <div className={s.card}>
          <span className={`${s.sk} ${s.skCardTitle}`} />
          <div className={s.statusBody}>
            <span className={`${s.sk} ${s.skDonut}`} />
            <div className={s.legend}>
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className={s.legendRow}>
                  <span className={`${s.sk} ${s.skDot}`} />
                  <span className={`${s.sk} ${s.skLine}`} style={{ flex: 1 }} />
                  <span className={`${s.sk} ${s.skLineSm}`} />
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className={s.card}>
          <span className={`${s.sk} ${s.skCardTitle}`} />
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className={s.skFeedRow}>
              <span className={`${s.sk} ${s.skLineSm}`} style={{ width: 36 }} />
              <span className={`${s.sk} ${s.skLine}`} style={{ flex: 1 }} />
              <span className={`${s.sk} ${s.skLineSm}`} style={{ width: 54 }} />
              <span className={`${s.sk} ${s.skPill}`} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon, label, value, accent, sub,
}: {
  icon: string; label: string; value: string; accent: string; sub?: string;
}) {
  return (
    <div className={s.stat} style={{ ["--accent" as string]: accent }}>
      <div className={s.statTop}>
        <span className={s.statIcon}>{icon}</span>
        <span className={s.statLabel}>{label}</span>
      </div>
      <span className={s.statValue}>{value}</span>
      {sub && <span className={s.statSub}>{sub}</span>}
    </div>
  );
}

export function LiveOpsScreen() {
  const { data, error } = usePoll<OrderOut[]>(
    () => fetchOrders({ previewBatch: false }),
    4000,
  );
  // First paint, before the initial poll resolves — show the skeleton.
  const loading = data === null && error == null;
  const orders = data ?? [];
  const nav = useNavigate();
  const [filter, setFilter] = useState<OrderOut["status"] | "all">("all");
  // Manager-dismissed urgent alerts (kept in memory only — a page refresh
  // re-surfaces anything still breaching so nothing is silently lost).
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  const activeOrders = orders.filter((o) => ACTIVE.includes(o.status));
  const urgent = activeOrders
    .filter((o) => remainingMs(o.sla_started_at) <= 10 * 60_000)
    .filter((o) => !dismissed.has(o.id));

  const kpis = useMemo(() => {
    const delivered = orders.filter((o) => o.status === "delivered").length;
    const revenue = orders.filter((o) => o.status === "delivered")
      .reduce((sum, o) => sum + Number(o.total_aed), 0);
    const finished = delivered + orders.filter((o) => o.status === "cancelled").length;
    const completion = finished > 0 ? Math.round((delivered / finished) * 100) : 100;
    return {
      total: orders.length,
      active: activeOrders.length,
      delivered,
      revenue: `AED ${revenue.toFixed(0)}`,
      completion,
    };
  }, [orders, activeOrders.length]);

  // Status breakdown for the donut — only statuses that have orders.
  const pieData = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const o of orders) counts[o.status] = (counts[o.status] || 0) + 1;
    return Object.entries(counts)
      .map(([status, value]) => ({
        name: STATUS_LABEL[status] ?? status,
        value,
        color: STATUS_COLORS[status] ?? "#9ca3af",
      }))
      .sort((a, b) => b.value - a.value);
  }, [orders]);

  // Conic-gradient stops for the donut ring — always a perfectly closed circle
  // (no recharts single-segment seam), segments sized by share of total.
  const conic = useMemo(() => {
    const total = orders.length || 1;
    let acc = 0;
    const stops = pieData.map((d) => {
      const start = (acc / total) * 360;
      acc += d.value;
      const end = (acc / total) * 360;
      return `${d.color} ${start}deg ${end}deg`;
    });
    return `conic-gradient(${stops.join(", ")})`;
  }, [pieData, orders.length]);

  const laneIds = new Set(urgent.map((o) => o.id));
  const feedSource = orders.filter((o) => !laneIds.has(o.id));
  const feed = filter === "all" ? feedSource : feedSource.filter((o) => o.status === filter);
  // Show only the 5 most recent orders in the side panel.
  const visibleFeed = [...feed].sort((a, b) => b.id - a.id).slice(0, 5);

  const orderColumns: Column<OrderOut>[] = [
    { key: "id", header: "#", render: (o) => <span className="mono">#{o.id}</span> },
    { key: "cust", header: "Customer", render: (o) => o.customer_name },
    {
      key: "items",
      header: "Items",
      render: (o) => {
        const text = o.items.map((i) => `${i.qty}× ${i.name}`).join(", ");
        // Truncate long item lists to one line; full text on hover.
        return <span className={s.itemsCell} title={text}>{text}</span>;
      },
    },
    { key: "total", header: "Total", render: (o) => <span className="mono">AED {o.total_aed}</span> },
    { key: "status", header: "Status", render: (o) => <StatusPill status={o.status} /> },
  ];

  return (
    <div className={s.screen}>
      {error != null && <SectionBanner tone="warning">Connection lost — reconnecting…</SectionBanner>}

      {/* ── Command-center header ─── */}
      <header className={s.pageHeader}>
        <div>
          <h1 className={s.h1}>Live Operations</h1>
          <p className={s.sub}>Real time order &amp; delivery command center</p>
        </div>
        <div className={s.headerRight}>
          <span className={s.livePill}><span className={s.liveDot} />LIVE</span>
        </div>
      </header>

      {loading ? (
        <LiveOpsSkeleton />
      ) : (
      <>
      {/* ── KPI cards ─── */}
      <div className={s.kpiStrip}>
        <StatCard icon="📦" label="Orders Today" value={String(kpis.total)}
          accent="var(--chart-1)" sub={`${kpis.active} active now`} />
        <StatCard icon="⚡" label="Active Now" value={String(kpis.active)}
          accent="var(--sla-warn)" sub={urgent.length > 0 ? `${urgent.length} urgent` : "all on track"} />
        <StatCard icon="✅" label="Delivered" value={String(kpis.delivered)}
          accent="var(--sla-safe)" sub={`${kpis.completion}% completion`} />
        <StatCard icon="💰" label="Money Collected" value={kpis.revenue}
          accent="var(--accent-revenue)" sub="collected today" />
      </div>

      <div className={s.dispatchKpiRow}>
        <DispatchKpiPanel />
      </div>

      <div className={s.card}>
        <div className={s.cardTitle}>Fleet Map</div>
        <LiveOpsMap />
      </div>

      {/* ── Urgent orders (need attention) ─── */}
      {urgent.length > 0 && (
        <div className={s.urgentCard}>
          <div className={s.urgentTitle}>
            <span className={s.urgentPulse} />Needs Attention Now
            <span className={s.urgentBadge}>{urgent.length}</span>
          </div>
          <div className={s.urgentList}>
            {urgent.map((o) => (
              <SLAOrderCard
                key={o.id}
                order={o}
                onClick={() => nav(`/orders?id=${o.id}`)}
                onDismiss={() =>
                  setDismissed((prev) => new Set(prev).add(o.id))
                }
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Distribution + All Orders ─── */}
      <div className={s.grid2}>
        <div className={s.card}>
          <div className={s.cardTitle}>Order Distribution</div>
          {orders.length === 0 ? (
            <div className={s.miniEmpty}>No orders to chart yet.</div>
          ) : (
            <div className={s.statusBody}>
              <div className={s.donutWrap}>
                <div className={s.donut} style={{ background: conic }} />
                <div className={s.donutHole} />
                <div className={s.donutCenter}>
                  <span className={s.donutNum}>{orders.length}</span>
                  <span className={s.donutCap}>orders</span>
                </div>
              </div>
              <div className={s.legend}>
                {pieData.map((d) => (
                  <div key={d.name} className={s.legendRow}>
                    <span className={s.legendDot} style={{ background: d.color }} />
                    <span className={s.legendLabel}>{d.name}</span>
                    <span className={s.legendPct}>{Math.round((d.value / orders.length) * 100)}%</span>
                    <span className={s.legendCount}>{d.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className={s.card}>
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
          <CompactTable
            columns={orderColumns}
            rows={visibleFeed}
            rowKey={(o) => o.id}
            onRowClick={(o) => nav(`/orders?id=${o.id}`)}
            emptyText={orders.length === 0 ? "No orders yet today." : "Nothing in this category right now."}
          />
        </div>
      </div>
      </>
      )}
    </div>
  );
}
