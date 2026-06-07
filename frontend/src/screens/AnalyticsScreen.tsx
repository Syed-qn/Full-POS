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
import { KPITile } from "../components/KPITile";
import { SectionBanner } from "../components/SectionBanner";
import type { ForecastResult } from "../lib/predictionsApi";
import { fetchLatestForecast } from "../lib/predictionsApi";
import { fetchCampaigns } from "../lib/marketingApi";
import type { CampaignResponse } from "../lib/marketingApi";
import { usePoll } from "../lib/usePoll";
import s from "./AnalyticsScreen.module.css";

const HORIZONS = ["breakfast", "lunch", "dinner", "midnight"] as const;
type Horizon = (typeof HORIZONS)[number];

const HORIZON_COLORS = ["#2563eb", "#7c3aed", "#059669", "#d97706"];

async function fetchAllForecasts(): Promise<Partial<Record<Horizon, ForecastResult>>> {
  const results = await Promise.allSettled(
    HORIZONS.map((h) => fetchLatestForecast(h)),
  );
  const map: Partial<Record<Horizon, ForecastResult>> = {};
  HORIZONS.forEach((h, i) => {
    const r = results[i];
    if (r.status === "fulfilled" && r.value !== null) {
      map[h] = r.value;
    }
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

function forecastOrderCount(f: ForecastResult): number {
  const p = f.predictions;
  if (typeof p.order_count === "number") return p.order_count;
  if (typeof p.total === "number") return p.total;
  if (typeof p.count === "number") return p.count;
  return Object.values(p)
    .filter((v): v is number => typeof v === "number")
    .reduce((sum, v) => sum + v, 0);
}

export function AnalyticsScreen() {
  const { data: forecasts, error: forecastError } = usePoll<Partial<Record<Horizon, ForecastResult>>>(
    fetchAllForecasts,
    60_000,
  );
  const { data: campaigns, error: campaignError } = usePoll<CampaignResponse[]>(
    fetchCampaignSummary,
    60_000,
  );

  const hasForecasts = forecasts != null && Object.keys(forecasts).length > 0;
  const hasCampaigns = campaigns != null && campaigns.length > 0;
  const error = forecastError ?? campaignError;

  const campaignStats = useMemo(() => {
    if (!campaigns || campaigns.length === 0) return null;
    const total = campaigns.length;
    const sent = campaigns.reduce((sum, c) => {
      const v = typeof c.stats.sent === "number" ? c.stats.sent : 0;
      return sum + v;
    }, 0);
    const converted = campaigns.reduce((sum, c) => {
      const v = typeof c.stats.converted === "number" ? c.stats.converted : 0;
      return sum + v;
    }, 0);
    const conversionRate = sent > 0 ? ((converted / sent) * 100).toFixed(1) : "—";
    return { total, sent, conversionRate };
  }, [campaigns]);

  const forecastChart = useMemo(() => {
    if (!forecasts) return [];
    return HORIZONS.map((h) => ({
      name: h.charAt(0).toUpperCase() + h.slice(1),
      orders: forecasts[h] ? forecastOrderCount(forecasts[h]!) : 0,
    }));
  }, [forecasts]);

  const campaignChart = useMemo(() => {
    if (!campaigns || campaigns.length === 0) return [];
    return campaigns.slice(0, 10).map((c) => ({
      name: `#${c.id}`,
      sent: typeof c.stats.sent === "number" ? c.stats.sent : 0,
      converted: typeof c.stats.converted === "number" ? c.stats.converted : 0,
    }));
  }, [campaigns]);

  const tooltipStyle = {
    contentStyle: {
      background: "var(--bg-surface)",
      border: "1px solid var(--border-subtle)",
      borderRadius: "6px",
      fontSize: 12,
      boxShadow: "var(--shadow-sm)",
    },
    cursor: { fill: "rgba(37,99,235,0.06)" },
  };

  return (
    <div className={s.screen}>
      {error != null && (
        <SectionBanner tone="warning">
          Analytics data could not be refreshed — retrying.
        </SectionBanner>
      )}

      {/* ── Demand Predictions ─────────────────────────────────────────── */}
      <section className={s.section}>
        <span className="label-upper">Demand Predictions — Today</span>
        {forecasts === null ? (
          <div className={s.loading}>Loading forecasts…</div>
        ) : !hasForecasts ? (
          <div className={s.empty} data-testid="no-predictions">
            No predictions yet — data builds over time.
          </div>
        ) : (
          <>
            <div className={s.kpiStrip}>
              {HORIZONS.map((h, i) => {
                const f = forecasts[h];
                return (
                  <KPITile
                    key={h}
                    label={h.charAt(0).toUpperCase() + h.slice(1)}
                    value={f ? String(forecastOrderCount(f)) + " orders" : "—"}
                    accent={HORIZON_COLORS[i]}
                  />
                );
              })}
            </div>

            {/* Forecast bar chart */}
            <div className={s.chartWrap}>
              <span className={s.chartTitle}>Predicted Orders by Meal Horizon</span>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={forecastChart} margin={{ top: 8, right: 16, bottom: 0, left: 0 }} barSize={36}>
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 12, fill: "var(--text-secondary)" }}
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
                  <Tooltip {...tooltipStyle} />
                  <Bar dataKey="orders" radius={[4, 4, 0, 0]}>
                    {forecastChart.map((_, i) => (
                      <Cell key={i} fill={HORIZON_COLORS[i] ?? "#2563eb"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </section>

      {/* ── Forecast Run Details ───────────────────────────────────────── */}
      {hasForecasts && forecasts && (
        <section className={s.section}>
          <span className="label-upper">Forecast Details</span>
          <div className={s.forecastGrid}>
            {HORIZONS.map((h, i) => {
              const f = forecasts[h];
              if (!f) return null;
              return (
                <div key={h} className={s.forecastCard} style={{ borderTop: `3px solid ${HORIZON_COLORS[i]}` }}>
                  <div className={s.forecastHorizon}>{h}</div>
                  <div className={s.forecastDate}>{f.target_date}</div>
                  {f.adjusted && <span className={s.adjustedBadge}>Adjusted</span>}
                  <div className={s.forecastRunId}>Run #{f.run_id}</div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Campaign Performance ───────────────────────────────────────── */}
      <section className={s.section}>
        <span className="label-upper">Campaign Performance</span>
        {campaigns === null ? (
          <div className={s.loading}>Loading campaigns…</div>
        ) : !hasCampaigns ? (
          <div className={s.empty}>No campaigns yet — create one to start marketing.</div>
        ) : (
          <>
            <div className={s.kpiStrip}>
              <KPITile label="Total Campaigns" value={String(campaignStats?.total ?? 0)} accent="var(--chart-1)" />
              <KPITile label="Messages Sent" value={String(campaignStats?.sent ?? 0)} accent="var(--chart-3)" />
              <KPITile label="Conversion Rate" value={`${campaignStats?.conversionRate ?? "—"}%`} accent="var(--chart-2)" />
            </div>

            {/* Campaign sent vs converted bar chart */}
            {campaignChart.length > 0 && (
              <div className={s.chartWrap}>
                <span className={s.chartTitle}>Sent vs Converted per Campaign</span>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={campaignChart} margin={{ top: 8, right: 16, bottom: 0, left: 0 }} barSize={18} barCategoryGap="30%">
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
                    <Tooltip {...tooltipStyle} />
                    <Bar dataKey="sent" name="Sent" fill="var(--chart-1)" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="converted" name="Converted" fill="var(--chart-3)" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            <div className={s.campaignTable}>
              <div className={s.tableHead}>
                <span>ID</span>
                <span>Type</span>
                <span>Status</span>
                <span>Sent</span>
                <span>Converted</span>
              </div>
              {campaigns.map((c) => (
                <div key={c.id} className={s.tableRow}>
                  <span className={s.mono}>#{c.id}</span>
                  <span className={s.typeLabel}>{c.type}</span>
                  <span className={s.statusLabel} data-status={c.status}>{c.status}</span>
                  <span>{typeof c.stats.sent === "number" ? c.stats.sent : "—"}</span>
                  <span>{typeof c.stats.converted === "number" ? c.stats.converted : "—"}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
