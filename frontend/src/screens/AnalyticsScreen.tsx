import { useMemo } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { SectionBanner } from "../components/SectionBanner";
import type { ForecastResult } from "../lib/predictionsApi";
import { fetchLatestForecast } from "../lib/predictionsApi";
import { fetchCampaigns } from "../lib/marketingApi";
import type { CampaignResponse } from "../lib/marketingApi";
import { usePoll } from "../lib/usePoll";
import { PageHeader } from "../components/PageHeader";
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
  try { return await fetchCampaigns(); } catch { return []; }
}

function forecastCount(f: ForecastResult): number {
  const p = f.predictions;
  if (typeof p.order_count === "number") return p.order_count;
  if (typeof p.total === "number") return p.total;
  if (typeof p.count === "number") return p.count;
  return Object.values(p).filter((v): v is number => typeof v === "number").reduce((a, b) => a + b, 0);
}

export function AnalyticsScreen() {
  const { data: forecasts, error: fErr } = usePoll<Partial<Record<Horizon, ForecastResult>>>(fetchAllForecasts, 60_000);
  const { data: campaigns, error: cErr } = usePoll<CampaignResponse[]>(fetchCampaignSummary, 60_000);

  const hasForecasts = forecasts != null && Object.keys(forecasts).length > 0;
  const error = fErr ?? cErr;

  const forecastChart = useMemo(() => {
    if (!forecasts) return [];
    return HORIZONS.map((h, i) => ({
      name: HORIZON_EMOJI[h] + " " + h.charAt(0).toUpperCase() + h.slice(1),
      orders: forecasts[h] ? forecastCount(forecasts[h]!) : 0,
      color: HORIZON_COLORS[i],
    })).filter((d) => d.orders > 0);
  }, [forecasts]);

  const campaignStats = useMemo(() => {
    if (!campaigns || campaigns.length === 0) return null;
    const sent = campaigns.reduce((s, c) => s + (typeof c.stats.sent === "number" ? c.stats.sent : 0), 0);
    const converted = campaigns.reduce((s, c) => s + (typeof c.stats.converted === "number" ? c.stats.converted : 0), 0);
    return {
      total: campaigns.length,
      sent,
      converted,
      rate: sent > 0 ? Math.round((converted / sent) * 100) : 0,
    };
  }, [campaigns]);

  return (
    <div className={s.screen}>
      <PageHeader title="Reports" subtitle="Performance and delivery insights" />
      {error != null && <SectionBanner tone="warning">Could not load data — retrying…</SectionBanner>}

      {/* ── Today's demand forecast ─── */}
      <div className={s.card}>
        <div className={s.cardHead}>
          <span className={s.cardTitle}>Expected Orders Today</span>
          <span className={s.cardSub}>Our prediction for each meal time</span>
        </div>

        {forecasts === null ? (
          <div className={s.loading}>Loading…</div>
        ) : !hasForecasts || forecastChart.length === 0 ? (
          <div className={s.empty}>
            <div className={s.emptyIcon}>📊</div>
            <div className={s.emptyTitle}>No predictions yet</div>
            <div className={s.emptyDesc}>Predictions appear after a few days of orders. Keep taking orders!</div>
          </div>
        ) : (
          <>
            {/* Simple column chart */}
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={forecastChart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barSize={48}>
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 13, fill: "#374151" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis hide />
                <Tooltip
                  contentStyle={{ background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8, fontSize: 13 }}
                  formatter={(v) => [`${v} orders`, "Expected"]}
                  cursor={{ fill: "rgba(0,0,0,0.04)" }}
                />
                <Bar dataKey="orders" radius={[6, 6, 0, 0]} label={{ position: "top", fontSize: 14, fontWeight: 700, fill: "#111827" }}>
                  {forecastChart.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </>
        )}
      </div>

      {/* ── Marketing / campaigns ─── */}
      <div className={s.card}>
        <div className={s.cardHead}>
          <span className={s.cardTitle}>Marketing Messages</span>
          <span className={s.cardSub}>How well your promotions are working</span>
        </div>

        {campaigns === null ? (
          <div className={s.loading}>Loading…</div>
        ) : !campaignStats ? (
          <div className={s.empty}>
            <div className={s.emptyIcon}>📣</div>
            <div className={s.emptyTitle}>No campaigns yet</div>
            <div className={s.emptyDesc}>Send your first promotion to customers from the Marketing section.</div>
          </div>
        ) : (
          <div className={s.statRow}>
            <div className={s.statBox} style={{ borderTopColor: "#2563eb" }}>
              <div className={s.statNum}>{campaignStats.total}</div>
              <div className={s.statLabel}>Campaigns sent</div>
            </div>
            <div className={s.statBox} style={{ borderTopColor: "#059669" }}>
              <div className={s.statNum}>{campaignStats.sent}</div>
              <div className={s.statLabel}>Messages delivered</div>
            </div>
            <div className={s.statBox} style={{ borderTopColor: "#7c3aed" }}>
              <div className={s.statNum}>{campaignStats.converted}</div>
              <div className={s.statLabel}>Orders from campaigns</div>
            </div>
            <div className={s.statBox} style={{ borderTopColor: "#d97706" }}>
              <div className={s.statNum}>{campaignStats.rate}%</div>
              <div className={s.statLabel}>Success rate</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
