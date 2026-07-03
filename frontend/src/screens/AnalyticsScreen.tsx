import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  CampaignSummarySkeleton,
  CampaignSummaryStrip,
} from "../components/CampaignSummaryStrip";
import { DispatchKpiPanel } from "../components/DispatchKpiPanel";
import { PageHeader } from "../components/PageHeader";
import { ReportsDateRangePicker } from "../components/ReportsDateRangePicker";
import { SectionBanner } from "../components/SectionBanner";
import {
  computeCampaignSummary,
  filterCampaignsByDate,
} from "../lib/campaignSummary";
import type { CampaignResponse } from "../lib/marketingApi";
import { fetchCampaigns } from "../lib/marketingApi";
import { computeOrderDeliveryKpis } from "../lib/orderDeliveryKpis";
import { fetchOrders } from "../lib/ordersApi";
import type { ForecastResult } from "../lib/predictionsApi";
import { fetchLatestForecast } from "../lib/predictionsApi";
import { boundsForPreset, type ReportsDatePreset } from "../lib/reportsDateRange";
import { usePoll } from "../lib/usePoll";
import s from "./AnalyticsScreen.module.css";

const HORIZONS = ["breakfast", "lunch", "dinner", "midnight"] as const;
type Horizon = (typeof HORIZONS)[number];

const HORIZON_EMOJI: Record<string, string> = {
  breakfast: "🌅",
  lunch: "☀️",
  dinner: "🌙",
  midnight: "🌃",
};
const HORIZON_COLORS = ["#2563eb", "#f59e0b", "#7c3aed", "#0891b2"];

async function fetchAllForecasts(): Promise<Partial<Record<Horizon, ForecastResult>>> {
  const results = await Promise.allSettled(HORIZONS.map((h) => fetchLatestForecast(h)));
  const map: Partial<Record<Horizon, ForecastResult>> = {};
  HORIZONS.forEach((h, i) => {
    const r = results[i];
    if (r.status === "fulfilled" && r.value !== null) map[h] = r.value;
  });
  return map;
}

async function fetchCampaignSummary(): Promise<CampaignResponse[]> {
  try {
    return await fetchCampaigns();
  } catch {
    return [];
  }
}

function forecastCount(f: ForecastResult): number {
  const p = f.predictions;
  if (typeof p.order_count === "number") return p.order_count;
  if (typeof p.total === "number") return p.total;
  if (typeof p.count === "number") return p.count;
  return Object.values(p)
    .filter((v): v is number => typeof v === "number")
    .reduce((a, b) => a + b, 0);
}

function ForecastSkeleton() {
  const bars = [62, 88, 74, 96];
  return (
    <div className={s.skChart} aria-busy="true" aria-label="Loading forecast">
      {bars.map((h, i) => (
        <div key={i} className={s.skBarCol}>
          <span className={`${s.sk} ${s.skBar}`} style={{ height: `${h}%` }} />
          <span className={`${s.sk} ${s.skBarLabel}`} />
        </div>
      ))}
    </div>
  );
}

function DeliverySkeleton() {
  return (
    <div className={s.statRow} aria-busy="true" aria-label="Loading delivery metrics">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className={s.statBox}>
          <span className={`${s.sk} ${s.skStatNum}`} />
          <span className={`${s.sk} ${s.skStatLabel}`} />
        </div>
      ))}
    </div>
  );
}

export function AnalyticsScreen() {
  const [datePreset, setDatePreset] = useState<ReportsDatePreset>("7d");
  const dateBounds = useMemo(() => boundsForPreset(datePreset), [datePreset]);

  const { data: forecasts, error: fErr } = usePoll<Partial<Record<Horizon, ForecastResult>>>(
    fetchAllForecasts,
    60_000,
  );
  const { data: campaigns, error: cErr } = usePoll<CampaignResponse[]>(
    fetchCampaignSummary,
    60_000,
  );
  const fetchOrdersForRange = useMemo(
    () => () =>
      fetchOrders({
        fromDate: dateBounds.fromDate,
        toDate: dateBounds.toDate,
        previewBatch: false,
        limit: 500,
      }),
    [dateBounds.fromDate, dateBounds.toDate],
  );
  const { data: orders, error: oErr } = usePoll(fetchOrdersForRange, 60_000);

  const filteredCampaigns = useMemo(
    () => (campaigns ? filterCampaignsByDate(campaigns, dateBounds) : null),
    [campaigns, dateBounds],
  );
  const campaignStats = useMemo(
    () => (filteredCampaigns ? computeCampaignSummary(filteredCampaigns) : null),
    [filteredCampaigns],
  );
  const deliveryKpis = useMemo(
    () => (orders ? computeOrderDeliveryKpis(orders) : null),
    [orders],
  );

  const hasForecasts = forecasts != null && Object.keys(forecasts).length > 0;
  const error = fErr ?? cErr ?? oErr;

  const forecastChart = useMemo(() => {
    if (!forecasts) return [];
    return HORIZONS.map((h, i) => ({
      name: HORIZON_EMOJI[h] + " " + h.charAt(0).toUpperCase() + h.slice(1),
      orders: forecasts[h] ? forecastCount(forecasts[h]!) : 0,
      color: HORIZON_COLORS[i],
    })).filter((d) => d.orders > 0);
  }, [forecasts]);

  return (
    <div className={s.screen}>
      <PageHeader
        title="Reports"
        subtitle="Performance and delivery insights"
        right={
          <ReportsDateRangePicker value={datePreset} onChange={setDatePreset} />
        }
      />
      {error != null && (
        <SectionBanner tone="warning">Could not load data — retrying…</SectionBanner>
      )}

      <div className={s.card}>
        <div className={s.cardHead}>
          <span className={s.cardTitle}>Delivery &amp; Operations</span>
          <span className={s.cardSub}>
            Orders and fleet performance for {dateBounds.label.toLowerCase()}
          </span>
        </div>

        {orders === null ? (
          <DeliverySkeleton />
        ) : deliveryKpis ? (
          <div className={s.statRow}>
            <div className={s.statBox}>
              <div className={s.statNum}>{deliveryKpis.orders}</div>
              <div className={s.statLabel}>Orders</div>
            </div>
            <div className={s.statBox}>
              <div className={s.statNum}>{deliveryKpis.delivered}</div>
              <div className={s.statLabel}>Delivered</div>
            </div>
            <div className={s.statBox}>
              <div className={s.statNum}>AED {deliveryKpis.revenueAed.toFixed(0)}</div>
              <div className={s.statLabel}>Revenue collected</div>
            </div>
            <div className={s.statBox}>
              <div className={s.statNum}>{deliveryKpis.completionPct}%</div>
              <div className={s.statLabel}>Completion rate</div>
            </div>
          </div>
        ) : null}

        <DispatchKpiPanel />
      </div>

      <div className={s.card}>
        <div className={s.cardHead}>
          <span className={s.cardTitle}>Marketing Messages</span>
          <span className={s.cardSub}>
            Promotion results for {dateBounds.label.toLowerCase()}
          </span>
        </div>

        {filteredCampaigns === null ? (
          <CampaignSummarySkeleton />
        ) : !campaignStats ? (
          <div className={s.empty}>
            <div className={s.emptyIcon}>📣</div>
            <div className={s.emptyTitle}>No campaigns in this period</div>
            <div className={s.emptyDesc}>
              Send your first promotion from the Marketing section, or widen the date
              range.
            </div>
          </div>
        ) : (
          <CampaignSummaryStrip summary={campaignStats} />
        )}
      </div>

      <div className={s.card}>
        <div className={s.cardHead}>
          <span className={s.cardTitle}>Expected Orders Today</span>
          <span className={s.cardSub}>Our prediction for each meal time</span>
        </div>

        {forecasts === null ? (
          <ForecastSkeleton />
        ) : !hasForecasts || forecastChart.length === 0 ? (
          <div className={s.empty}>
            <div className={s.emptyIcon}>📊</div>
            <div className={s.emptyTitle}>No predictions yet</div>
            <div className={s.emptyDesc}>
              Predictions appear after a few days of orders. Keep taking orders!
            </div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <BarChart
              data={forecastChart}
              margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
              barSize={48}
            >
              <XAxis
                dataKey="name"
                tick={{ fontSize: 13, fill: "#374151" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis hide />
              <Tooltip
                contentStyle={{
                  background: "#fff",
                  border: "1px solid #e5e7eb",
                  borderRadius: 8,
                  fontSize: 13,
                }}
                formatter={(v) => [`${v} orders`, "Expected"]}
                cursor={{ fill: "rgba(0,0,0,0.04)" }}
              />
              <Bar
                dataKey="orders"
                radius={[6, 6, 0, 0]}
                label={{ position: "top", fontSize: 14, fontWeight: 700, fill: "#111827" }}
              >
                {forecastChart.map((d, i) => (
                  <Cell key={i} fill={d.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}