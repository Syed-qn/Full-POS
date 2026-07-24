import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
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
import { useAppTheme } from "../lib/appTheme";
import {
  computeCampaignSummary,
  filterCampaignsByDate,
} from "../lib/campaignSummary";
import type { CampaignResponse } from "../lib/marketingApi";
import { fetchCampaigns } from "../lib/marketingApi";
import {
  hourlyHeatmap,
  topDishes,
  type DishSales,
  type HeatmapResult,
} from "../lib/analyticsBreakdowns";
import { computeOrderDeliveryKpis } from "../lib/orderDeliveryKpis";
import { fetchOrders } from "../lib/ordersApi";
import { buildDailySeries, type DailyPoint } from "../lib/salesSeries";
import { boundsForPreset, type ReportsDatePreset } from "../lib/reportsDateRange";
import { usePoll } from "../lib/usePoll";
import s from "./AnalyticsScreen.module.css";

type Metric = "revenue" | "orders";

/** Chart palette per app theme — axes/grid must stay legible in dark + blue. */
function chartColors(theme: string) {
  const dark = theme === "dark" || theme === "blue";
  return {
    axis: dark ? "#94a3b8" : "#64748b",
    grid: dark ? "rgba(148,163,184,0.18)" : "#e5e7eb",
    stroke: "#2563eb",
    fill: dark ? "rgba(37,99,235,0.28)" : "rgba(37,99,235,0.14)",
    tooltipBg: dark ? "#1e293b" : "#ffffff",
    tooltipBorder: dark ? "#334155" : "#e5e7eb",
    tooltipText: dark ? "#e2e8f0" : "#111827",
  };
}

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Blue heat scale, count ratio 0..1 → cell colour (works on light + dark). */
function heatColor(ratio: number): string {
  if (ratio <= 0) return "var(--bg-surface-inset)";
  return `rgba(37, 99, 235, ${(0.12 + 0.88 * ratio).toFixed(3)})`;
}

/** One weekday row of the heatmap: label + 24 hour cells. */
function ReactFragmentRow({ day, row, max }: { day: string; row: number[]; max: number }) {
  return (
    <>
      <div className={s.heatDay}>{day}</div>
      {row.map((count, h) => (
        <div
          key={h}
          className={s.heatCell}
          style={{ background: heatColor(max ? count / max : 0) }}
          title={`${day} ${String(h).padStart(2, "0")}:00 · ${count} order${count === 1 ? "" : "s"}`}
        />
      ))}
    </>
  );
}

async function fetchCampaignSummary(): Promise<CampaignResponse[]> {
  try {
    return await fetchCampaigns();
  } catch {
    return [];
  }
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

function TrendSkeleton() {
  const bars = [40, 62, 54, 78, 68, 90, 72, 84];
  return (
    <div className={s.skChart} aria-busy="true" aria-label="Loading trend">
      {bars.map((h, i) => (
        <div key={i} className={s.skBarCol}>
          <span className={`${s.sk} ${s.skBar}`} style={{ height: `${h}%` }} />
        </div>
      ))}
    </div>
  );
}

export function AnalyticsScreen() {
  const theme = useAppTheme();
  const [datePreset, setDatePreset] = useState<ReportsDatePreset>("7d");
  const [metric, setMetric] = useState<Metric>("revenue");
  const dateBounds = useMemo(() => boundsForPreset(datePreset), [datePreset]);
  const colors = useMemo(() => chartColors(theme), [theme]);

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
        limit: 1000,
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
  const series: DailyPoint[] | null = useMemo(
    () => (orders ? buildDailySeries(orders) : null),
    [orders],
  );
  const dishes: DishSales[] | null = useMemo(
    () => (orders ? topDishes(orders, 8) : null),
    [orders],
  );
  const heat: HeatmapResult | null = useMemo(
    () => (orders ? hourlyHeatmap(orders) : null),
    [orders],
  );
  const maxDishRevenue = useMemo(
    () => (dishes && dishes.length ? Math.max(...dishes.map((d) => d.revenue)) : 1),
    [dishes],
  );

  const error = cErr ?? oErr;

  return (
    <div className={s.screen}>
      <PageHeader
        title="Analytics"
        subtitle="Performance, sales and delivery insights"
        right={
          <ReportsDateRangePicker value={datePreset} onChange={setDatePreset} />
        }
      />
      {error != null && (
        <SectionBanner tone="warning">Could not load data, retrying…</SectionBanner>
      )}

      <div className={s.bento}>
      <div className={`${s.card} ${s.spanFull}`}>
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

      {/* ── Sales trend over time ─────────────────────────────────────── */}
      <div className={`${s.card} ${s.spanFull}`}>
        <div className={s.trendHead}>
          <div className={s.cardHead}>
            <span className={s.cardTitle}>Sales trend</span>
            <span className={s.cardSub}>
              {metric === "revenue" ? "Revenue" : "Orders"} per day for{" "}
              {dateBounds.label.toLowerCase()}
            </span>
          </div>
          <div className={s.toggle} role="group" aria-label="Trend metric">
            <button
              type="button"
              className={`${s.toggleBtn} ${metric === "revenue" ? s.toggleActive : ""}`}
              aria-pressed={metric === "revenue"}
              onClick={() => setMetric("revenue")}
            >
              Revenue
            </button>
            <button
              type="button"
              className={`${s.toggleBtn} ${metric === "orders" ? s.toggleActive : ""}`}
              aria-pressed={metric === "orders"}
              onClick={() => setMetric("orders")}
            >
              Orders
            </button>
          </div>
        </div>

        {orders === null ? (
          <TrendSkeleton />
        ) : !series || series.length === 0 ? (
          <div className={s.empty}>
            <div className={s.emptyIcon}>📉</div>
            <div className={s.emptyTitle}>No orders in this period</div>
            <div className={s.emptyDesc}>
              Widen the date range, or take a few orders and the trend fills in per day.
            </div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={series} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={colors.stroke} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={colors.stroke} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={colors.grid} vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 12, fill: colors.axis }}
                axisLine={{ stroke: colors.grid }}
                tickLine={false}
                minTickGap={24}
              />
              <YAxis
                tick={{ fontSize: 12, fill: colors.axis }}
                axisLine={false}
                tickLine={false}
                width={48}
                tickFormatter={(v) =>
                  metric === "revenue"
                    ? `${Math.round(Number(v) / (Number(v) >= 1000 ? 1000 : 1))}${
                        Number(v) >= 1000 ? "k" : ""
                      }`
                    : String(v)
                }
              />
              <Tooltip
                contentStyle={{
                  background: colors.tooltipBg,
                  border: `1px solid ${colors.tooltipBorder}`,
                  borderRadius: 8,
                  fontSize: 13,
                  color: colors.tooltipText,
                }}
                labelStyle={{ color: colors.tooltipText, fontWeight: 700 }}
                formatter={(value, _name, item) => {
                  const p = item?.payload as DailyPoint | undefined;
                  return metric === "revenue"
                    ? [`AED ${Math.round(Number(value)).toLocaleString()} · ${p?.orders ?? 0} orders`, "Revenue"]
                    : [`${value} orders · AED ${Math.round(p?.revenue ?? 0).toLocaleString()}`, "Orders"];
                }}
                cursor={{ stroke: colors.stroke, strokeWidth: 1, strokeOpacity: 0.3 }}
              />
              <Area
                type="monotone"
                dataKey={metric}
                stroke={colors.stroke}
                strokeWidth={2}
                fill="url(#trendFill)"
                dot={series.length <= 31 ? { r: 2, fill: colors.stroke } : false}
                activeDot={{ r: 4 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* ── Top sellers ───────────────────────────────────────────────── */}
      <div className={s.card}>
        <div className={s.cardHead}>
          <span className={s.cardTitle}>Top sellers</span>
          <span className={s.cardSub}>
            Best dishes by revenue for {dateBounds.label.toLowerCase()}
          </span>
        </div>
        {orders === null ? (
          <TrendSkeleton />
        ) : !dishes || dishes.length === 0 ? (
          <div className={s.empty}>
            <div className={s.emptyIcon}>🍽️</div>
            <div className={s.emptyTitle}>No dishes sold in this period</div>
            <div className={s.emptyDesc}>Widen the date range to see your best sellers.</div>
          </div>
        ) : (
          <div className={s.dishList}>
            {dishes.map((d, i) => (
              <div key={d.name} className={s.dishRow}>
                <div className={s.dishRank}>{i + 1}</div>
                <div className={s.dishName} title={d.name}>
                  {d.name}
                </div>
                <div className={s.dishBarTrack}>
                  <div
                    className={s.dishBarFill}
                    style={{ width: `${(d.revenue / maxDishRevenue) * 100}%` }}
                  />
                </div>
                <div className={s.dishVal}>
                  AED {Math.round(d.revenue).toLocaleString()}
                  <span className={s.dishValSub}>{d.qty} sold</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Marketing (paired beside Top sellers) ─────────────────────── */}
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

      {/* ── Busy hours heatmap ────────────────────────────────────────── */}
      <div className={`${s.card} ${s.spanFull}`}>
        <div className={s.cardHead}>
          <span className={s.cardTitle}>Busy hours</span>
          <span className={s.cardSub}>
            Orders by hour and weekday (Asia/Dubai) for {dateBounds.label.toLowerCase()}
          </span>
        </div>
        {orders === null ? (
          <TrendSkeleton />
        ) : !heat || heat.total === 0 ? (
          <div className={s.empty}>
            <div className={s.emptyIcon}>🕒</div>
            <div className={s.emptyTitle}>No orders in this period</div>
            <div className={s.emptyDesc}>
              The heatmap fills in once orders come through. Busiest slots go darkest.
            </div>
          </div>
        ) : (
          <div className={s.heatWrap}>
            <div className={s.heat}>
              <div />
              {Array.from({ length: 24 }).map((_, h) => (
                <div key={h} className={s.heatHour}>
                  {h % 3 === 0 ? h : ""}
                </div>
              ))}
              {WEEKDAY_LABELS.map((day, wd) => (
                <ReactFragmentRow
                  key={day}
                  day={day}
                  row={heat.grid[wd]}
                  max={heat.max}
                />
              ))}
            </div>
            <div className={s.heatLegend}>
              <span>Fewer</span>
              <span className={s.heatLegendScale} aria-hidden="true">
                {[0.12, 0.35, 0.6, 0.85, 1].map((r) => (
                  <i key={r} style={{ background: heatColor(r) }} />
                ))}
              </span>
              <span>More</span>
            </div>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
