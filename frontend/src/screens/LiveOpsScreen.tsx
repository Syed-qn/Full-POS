import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button, TouchButton } from "../components/Button";
import { DispatchKpiPanel } from "../components/DispatchKpiPanel";
import { EmptyState } from "../components/EmptyState";
import { LiveOpsMap } from "../components/LiveOpsMap";
import { SectionBanner } from "../components/SectionBanner";
import { SLAOrderCard } from "../components/SLAOrderCard";
import { StatusPill } from "../components/StatusPill";
import { CountdownTimer } from "../components/CountdownTimer";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
import { useLiveOpsOrdersQuery } from "../lib/queries/dashboard";
import { remainingMs, slaTier } from "../lib/sla";
import type { OrderOut } from "../lib/types";
import s from "./LiveOpsScreen.module.css";

const ACTIVE: OrderOut["status"][] = [
  "confirmed", "preparing", "ready", "assigned", "picked_up", "arriving",
];

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  pending_confirmation: "Pending",
  confirmed: "New",
  preparing: "Cooking",
  ready: "Ready",
  assigned: "With Rider",
  picked_up: "On the Way",
  arriving: "Arriving",
  delivered: "Delivered",
  cancelled: "Cancelled",
  on_resale: "On Resale",
};

type LaneKey = "new" | "preparing" | "ready" | "out" | "late";

const LANES: { key: LaneKey; title: string; hint: string }[] = [
  { key: "new", title: "New", hint: "Just confirmed" },
  { key: "preparing", title: "Preparing", hint: "In kitchen" },
  { key: "ready", title: "Ready", hint: "Awaiting rider" },
  { key: "out", title: "Out", hint: "On the road" },
  { key: "late", title: "Late", hint: "SLA risk" },
];

function isLate(order: OrderOut): boolean {
  return remainingMs(order.sla_started_at) <= 10 * 60_000;
}

function boardLane(order: OrderOut): LaneKey {
  // Late is visually unavoidable — always take priority over status columns.
  if (ACTIVE.includes(order.status) && isLate(order)) return "late";
  if (order.status === "confirmed") return "new";
  if (order.status === "preparing") return "preparing";
  if (order.status === "ready") return "ready";
  if (order.status === "assigned" || order.status === "picked_up" || order.status === "arriving") {
    return "out";
  }
  return "new";
}

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
      <div className={s.board} style={{ marginTop: 20 }}>
        {LANES.map((lane) => (
          <div key={lane.key} className={s.lane}>
            <div className={s.laneHead}>
              <span className={`${s.sk} ${s.skLabel}`} />
            </div>
            {Array.from({ length: 2 }).map((_, i) => (
              <span key={i} className={`${s.sk} ${s.skCard}`} />
            ))}
          </div>
        ))}
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

function BoardCard({ order, onOpen }: { order: OrderOut; onOpen: () => void }) {
  const tier = slaTier(order.sla_started_at);
  const late = isLate(order);
  const items = order.items.map((i) => `${i.qty}× ${i.name}`).join(", ");
  return (
    <button
      type="button"
      className={`${s.orderCard} ${late ? s.orderCardLate : ""} ${s[`tier_${tier}`] ?? ""}`}
      onClick={onOpen}
    >
      <div className={s.orderCardTop}>
        <span className={s.orderId}>#{order.id}</span>
        <StatusPill status={order.status} />
      </div>
      <span className={s.orderCust}>{order.customer_name}</span>
      <span className={s.orderItems} title={items}>{items || "—"}</span>
      <div className={s.orderCardFoot}>
        <span className={s.orderTotal}>AED {order.total_aed}</span>
        {late ? (
          <span className={s.lateChip}>
            {tier === "breach" ? "OVERDUE" : "LATE RISK"}
          </span>
        ) : (
          <span className={s.timerChip}>
            <CountdownTimer slaStartedAt={order.sla_started_at} />
          </span>
        )}
      </div>
      {order.rider_name && <span className={s.orderRider}>{order.rider_name}</span>}
    </button>
  );
}

export function LiveOpsScreen() {
  const { data, error, isPending } = useLiveOpsOrdersQuery();
  const loading = isPending && data == null;
  const orders = data ?? [];
  const nav = useNavigate();
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  const activeOrders = orders.filter((o) => ACTIVE.includes(o.status));
  const urgent = activeOrders
    .filter((o) => isLate(o))
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

  const lanes = useMemo(() => {
    const buckets: Record<LaneKey, OrderOut[]> = {
      new: [],
      preparing: [],
      ready: [],
      out: [],
      late: [],
    };
    for (const o of activeOrders) {
      buckets[boardLane(o)].push(o);
    }
    for (const key of Object.keys(buckets) as LaneKey[]) {
      buckets[key].sort((a, b) => remainingMs(a.sla_started_at) - remainingMs(b.sla_started_at));
    }
    return buckets;
  }, [activeOrders]);

  return (
    <div className={s.screen}>
      <OfflineLimitsBanner surface="live-ops" />
      {error != null && <SectionBanner tone="warning">Connection lost — reconnecting…</SectionBanner>}

      <header className={s.pageHeader}>
        <div>
          <h1 className={s.h1}>Live Operations</h1>
          <p className={s.sub}>Order board · SLA · fleet — rush-hour command center</p>
        </div>
        <div className={s.headerRight}>
          <span className={s.livePill}><span className={s.liveDot} />LIVE</span>
        </div>
      </header>

      {loading ? (
        <LiveOpsSkeleton />
      ) : (
      <>
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

      {/* Status board — cards by lane (no dense table) */}
      <section className={s.boardSection} aria-label="Order status board">
        <div className={s.boardHead}>
          <h2 className={s.boardTitle}>Order board</h2>
          <span className={s.boardMeta}>{activeOrders.length} active</span>
        </div>
        {activeOrders.length === 0 ? (
          <EmptyState
            title="No active orders"
            description="New confirmations appear here by status. Start a walk-in or WhatsApp order."
            action={
              <TouchButton type="button" onClick={() => nav("/new-order")}>
                New Order
              </TouchButton>
            }
          />
        ) : (
          <div className={s.board}>
            {LANES.map((lane) => {
              const rows = lanes[lane.key];
              return (
                <div
                  key={lane.key}
                  className={`${s.lane} ${lane.key === "late" ? s.laneLate : ""}`}
                >
                  <div className={s.laneHead}>
                    <div>
                      <span className={s.laneTitle}>{lane.title}</span>
                      <span className={s.laneHint}>{lane.hint}</span>
                    </div>
                    <span className={`${s.laneCount} ${lane.key === "late" && rows.length ? s.laneCountHot : ""}`}>
                      {rows.length}
                    </span>
                  </div>
                  <div className={s.laneBody}>
                    {rows.length === 0 ? (
                      <div className={s.laneEmpty}>None</div>
                    ) : (
                      rows.map((o) => (
                        <BoardCard
                          key={o.id}
                          order={o}
                          onOpen={() => nav(`/orders?id=${o.id}`)}
                        />
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <div className={s.card}>
        <div className={s.cardTitle}>Fleet Map</div>
        <LiveOpsMap />
      </div>

      {/* Compact distribution legend (not the primary board) */}
      <div className={s.card}>
        <div className={s.cardTitle}>Today by status</div>
        {orders.length === 0 ? (
          <div className={s.miniEmpty}>No orders yet today.</div>
        ) : (
          <div className={s.statusChips}>
            {Object.entries(
              orders.reduce<Record<string, number>>((acc, o) => {
                acc[o.status] = (acc[o.status] || 0) + 1;
                return acc;
              }, {}),
            )
              .sort((a, b) => b[1] - a[1])
              .map(([status, count]) => (
                <span key={status} className={s.statusChip}>
                  <StatusPill status={status as OrderOut["status"]} />
                  <strong>{count}</strong>
                  <span className={s.statusChipLabel}>{STATUS_LABEL[status] ?? status}</span>
                </span>
              ))}
          </div>
        )}
      </div>
      </>
      )}

      <BottomActionBar>
        <TouchButton type="button" onClick={() => nav("/new-order")}>
          New Order
        </TouchButton>
        <Button type="button" variant="ghost" size="lg" onClick={() => nav("/orders")}>
          Open Orders
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={() => nav("/floor")}>
          Floor
        </Button>
        <Link className={s.barLink} to="/riders">
          Riders
        </Link>
        <Link className={s.barLink} to="/kds">
          Kitchen
        </Link>
        <Link className={s.barLink} to="/kds?view=expo">
          Expo
        </Link>
        <Link className={s.barLink} to="/reports">
          Reports
        </Link>
      </BottomActionBar>
    </div>
  );
}
