import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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

  const active = orders.filter((o) => ACTIVE.includes(o.status));
  const yellow = active.filter((o) => {
    const rem = remainingMs(o.sla_started_at);
    return rem <= 10 * 60_000 && rem > 5 * 60_000;
  });
  const red = active.filter((o) => remainingMs(o.sla_started_at) <= 5 * 60_000);

  // Orders surfaced in the SLA lanes are not duplicated in the feed below.
  const laneIds = new Set([...yellow, ...red].map((o) => o.id));
  const feedSource = orders.filter((o) => !laneIds.has(o.id));
  const feed = filter === "all" ? feedSource : feedSource.filter((o) => o.status === filter);

  return (
    <div className={s.screen}>
      {error != null && <SectionBanner tone="warning">Live updates paused — reconnecting.</SectionBanner>}

      <div className={s.kpiStrip}>
        <KPITile label="Orders Today" value={String(kpis.count)} />
        <KPITile label="Revenue Today" value={kpis.revenue} />
        <KPITile label="AOV" value={kpis.aov} />
        <KPITile label="Avg Delivery Time" value="—" />
        <KPITile label="SLA %" value="—" />
        <KPITile label="Late Count" value="0" />
        <KPITile label="Coupons Issued" value="0" />
      </div>

      <div className={s.midRow}>
        <div className={s.mapPanel}>
          <span className="label-upper">Dispatch Map</span>
          <div className={s.mapBody}>Map — riders &amp; batches (live tracking phase)</div>
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
