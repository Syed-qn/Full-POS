import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { TouchButton } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { SectionBanner } from "../components/SectionBanner";
import { StatusPill } from "../components/StatusPill";
import { CountdownTimer } from "../components/CountdownTimer";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
import { orderStatusLabel } from "../lib/orderDisplay";
import { useLiveOpsOrdersQuery } from "../lib/queries/dashboard";
import { remainingMs, slaTier } from "../lib/sla";
import type { OrderOut } from "../lib/types";
import s from "./LiveOpsScreen.module.css";

const ACTIVE: OrderOut["status"][] = [
  "confirmed", "preparing", "ready", "assigned", "picked_up", "arriving",
];

/** Toggle above the table. "All" first — it is the default view, not a state. */
type BoardTab = "all" | "dine" | "takeaway";

const BOARD_TABS: { key: BoardTab; title: string }[] = [
  { key: "all", title: "All" },
  { key: "dine", title: "Dine In" },
  { key: "takeaway", title: "Take Away" },
];

/**
 * Channel grouping, matching the KDS card badges so the two boards can never
 * disagree about what counts as dine-in. Delivery/online is not in this build,
 * so those order types fall outside both tabs and show only under "All".
 */
function channelOf(order: OrderOut): BoardTab | null {
  switch (order.order_type) {
    case "dine_in":
    case "tableside":
    case "qr":
      return "dine";
    case "takeaway":
    case "drive_thru":
      return "takeaway";
    default:
      return null;
  }
}

/** Rows shown before the list defers to the full Orders screen. */
const BOARD_LIMIT = 10;

function isLate(order: OrderOut): boolean {
  return remainingMs(order.sla_started_at) <= 10 * 60_000;
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
      {/* Skeleton mirrors the real table, not the retired lane board. */}
      <div className={s.tableWrap} style={{ marginTop: 20 }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <span key={i} className={`${s.sk} ${s.skRow}`} />
        ))}
      </div>
    </div>
  );
}

function StatCard({
  icon, label, value, accent, sub, onClick, active, testId,
}: {
  icon: string; label: string; value: string; accent: string; sub?: string;
  onClick?: () => void; active?: boolean; testId?: string;
}) {
  const body = (
    <>
      <div className={s.statTop}>
        <span className={s.statIcon}>{icon}</span>
        <span className={s.statLabel}>{label}</span>
      </div>
      <span className={s.statValue}>{value}</span>
      {sub && <span className={s.statSub}>{sub}</span>}
    </>
  );
  const style = { ["--accent" as string]: accent };
  // A card that filters the board is a button, not a div — keyboard and
  // screen readers get the same affordance the pointer does.
  if (!onClick) return <div className={s.stat} style={style}>{body}</div>;
  return (
    <button
      type="button"
      className={`${s.stat} ${s.statAction} ${active ? s.statOn : ""}`}
      style={style}
      onClick={onClick}
      aria-pressed={active}
      data-testid={testId}
    >
      {body}
    </button>
  );
}

/** One line of the order table. Rows, not cards: with two orders a five-lane
 *  card board collapses into slivers of whitespace, while a table stays
 *  readable at any count and puts every order's fields in the same column. */
function BoardRow({ order, onOpen }: { order: OrderOut; onOpen: () => void }) {
  const tier = slaTier(order.sla_started_at);
  const late = isLate(order);
  const items = order.items.map((i) => `${i.qty}× ${i.name}`).join(", ");
  return (
    <tr
      className={`${s.row} ${late ? s.rowLate : ""} ${s[`tier_${tier}`] ?? ""}`}
      onClick={onOpen}
      tabIndex={0}
      role="button"
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onOpen();
      }}
    >
      <td className={s.cRef}>#{order.id}</td>
      <td className={s.cCust}>{order.customer_name || "Walk-in"}</td>
      <td className={s.cItems} title={items}>{items || "—"}</td>
      <td className={s.cStatus}>
        {/* Same wording as the Orders board: a dine-in / take-away tab has no
            delivery leg, so it reads Open · Paid · Cancelled, not "Confirmed". */}
        <StatusPill
          status={order.status}
          label={orderStatusLabel(order.status, {
            resaleOfOrderId: order.resale_of_order_id,
            orderNumber: order.order_number,
            orderType: order.order_type,
            cancellationReason: order.cancellation_reason,
          })}
        />
      </td>
      <td className={s.cTotal}>AED {order.total_aed}</td>
      <td className={s.cTimer}>
        {late ? (
          <span className={s.lateChip}>
            {tier === "breach" ? "OVERDUE" : "LATE"}
          </span>
        ) : (
          <span className={s.timerChip}>
            <CountdownTimer slaStartedAt={order.sla_started_at} />
          </span>
        )}
      </td>
    </tr>
  );
}

export function LiveOpsScreen() {
  const { data, error, isPending } = useLiveOpsOrdersQuery();
  const loading = isPending && data == null;
  const orders = data ?? [];
  const nav = useNavigate();

  const activeOrders = orders.filter((o) => ACTIVE.includes(o.status));
  const urgent = activeOrders
    .filter((o) => isLate(o))
    .filter((o) => !o.sla_acked_at);

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

  const [boardTab, setBoardTab] = useState<BoardTab>("all");

  /** Counts per tab — always the FULL set, never the visible page, so a tab
   *  cannot promise rows the table then truncates away. */
  const laneCounts = useMemo(() => {
    const c: Record<BoardTab, number> = {
      all: activeOrders.length,
      dine: 0,
      takeaway: 0,
    };
    for (const o of activeOrders) {
      const ch = channelOf(o);
      if (ch) c[ch] += 1;
    }
    return c;
  }, [activeOrders]);

  /** Most urgent first — least SLA time left at the top, which is the order a
   *  manager needs to act in. */
  const boardAll = useMemo(() => {
    const rows =
      boardTab === "all"
        ? activeOrders
        : activeOrders.filter((o) => channelOf(o) === boardTab);
    return [...rows].sort(
      (a, b) => remainingMs(a.sla_started_at) - remainingMs(b.sla_started_at),
    );
  }, [activeOrders, boardTab]);

  const boardRows = boardAll.slice(0, BOARD_LIMIT);
  const hiddenCount = boardAll.length - boardRows.length;

  return (
    <div className={s.screen}>
      <OfflineLimitsBanner surface="live-ops" />
      {error != null && <SectionBanner tone="warning">Connection lost — reconnecting…</SectionBanner>}

      <header className={s.pageHeader}>
        <div>
          <h1 className={s.h1}>Live Operations</h1>
          <p className={s.sub}>Order board — rush-hour command center</p>
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
        {/* Channel tiles double as board filters — click one to narrow the
            table below, click it again to go back to All. */}
        <StatCard icon="🍽️" label="Dine In" value={String(laneCounts.dine)}
          accent="var(--amber, var(--sla-warn))" sub="active dine-in"
          testId="kpi-dine"
          active={boardTab === "dine"}
          onClick={() => setBoardTab(boardTab === "dine" ? "all" : "dine")} />
        <StatCard icon="🥡" label="Take Away" value={String(laneCounts.takeaway)}
          accent="var(--sla-safe)" sub="active take away"
          testId="kpi-takeaway"
          active={boardTab === "takeaway"}
          onClick={() => setBoardTab(boardTab === "takeaway" ? "all" : "takeaway")} />
      </div>

      {/* SLA "Needs Attention Now" list hidden for now. The board's Late tab
          shows the same orders; the acknowledge flow behind it is still wired
          (POST /orders/{id}/sla-ack) and can be brought back by restoring this
          block. */}
      {/* Order board — ONE table, filtered by a toggle. Was five lanes of
          cards, which only works with a full board: at two orders four lanes
          were empty slivers and the two real cards sat in 200px columns. */}
      <section className={s.boardSection} aria-label="Order board">
        <div className={s.boardHead}>
          <h2 className={s.boardTitle}>Order board</h2>
          <div className={s.boardTabs} role="tablist" aria-label="Filter orders">
            {BOARD_TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={boardTab === t.key}
                className={`${s.boardTab} ${boardTab === t.key ? s.boardTabOn : ""}`}
                onClick={() => setBoardTab(t.key)}
                data-testid={`board-tab-${t.key}`}
              >
                {t.title} <b>{laneCounts[t.key]}</b>
              </button>
            ))}
          </div>
        </div>

        {boardRows.length === 0 ? (
          <EmptyState
            title={boardTab === "all" ? "No active orders" : `Nothing in ${
              BOARD_TABS.find((t) => t.key === boardTab)?.title ?? "this list"
            }`}
            description="New confirmations appear here by status. Start a walk-in or WhatsApp order."
            action={
              <TouchButton type="button" onClick={() => nav("/new-order")}>
                New Order
              </TouchButton>
            }
          />
        ) : (
          <div className={s.tableWrap}>
            <table className={s.table}>
              <thead>
                <tr>
                  <th className={s.cRef}>Order</th>
                  <th className={s.cCust}>Customer</th>
                  <th className={s.cItems}>Items</th>
                  {/* No Rider column — this build is dine-in and take away only. */}
                  <th className={s.cStatus}>Status</th>
                  <th className={s.cTotal}>Total</th>
                  <th className={s.cTimer}>SLA</th>
                </tr>
              </thead>
              <tbody>
                {boardRows.map((o) => (
                  <BoardRow
                    key={o.id}
                    order={o}
                    onOpen={() => nav(`/orders?id=${o.id}`)}
                  />
                ))}
              </tbody>
            </table>
            {/* Say what is hidden. A silently truncated list reads as "that is
                everything", which on an ops board is the wrong belief. */}
            {hiddenCount > 0 && (
              <button
                type="button"
                className={s.moreLink}
                onClick={() => nav("/orders")}
              >
                {hiddenCount} more — open Orders
              </button>
            )}
          </div>
        )}
      </section>

      {/* Fleet Map and "Today by status" are hidden for now — delivery/fleet
          is not part of this build, and the status distribution restated what
          the order-board tabs already count. */}
      </>
      )}
    </div>
  );
}
