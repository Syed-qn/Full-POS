/**
 * Restaurant demand forecast — computed entirely from real order history.
 *
 * No ML service required: we take the trailing window of orders the restaurant
 * has already taken and project it forward with a transparent, explainable
 * method a manager can trust:
 *
 *   • Next 7 days   → average of the SAME weekday over the trailing weeks
 *                     (Mondays predict Mondays), for both order count + revenue.
 *   • Meal periods  → how demand splits across breakfast/lunch/dinner/late,
 *                     as an average per active day.
 *   • Top dishes    → what to prep ahead, as an average per active day.
 *   • Trend         → last 7 days vs the 7 before, so the numbers read in context.
 *
 * Pure functions only (no fetch, no Date.now besides the caller-supplied
 * `today`) so this is unit-testable and deterministic.
 */

import type { OrderOut } from "./types";

// Orders that never represent real demand and must not inflate the forecast.
const EXCLUDED_STATUSES = new Set(["cancelled", "draft"]);

export type PeriodKey = "breakfast" | "lunch" | "dinner" | "late";

export interface PeriodForecast {
  key: PeriodKey;
  label: string;
  emoji: string;
  /** Average orders in this window per active day. */
  avgPerDay: number;
  /** Share of all demand that falls in this window (0–100). */
  sharePct: number;
}

export interface DayForecast {
  /** YYYY-MM-DD (local). */
  date: string;
  /** Short weekday, e.g. "Mon". */
  weekday: string;
  isToday: boolean;
  predictedOrders: number;
  predictedRevenue: number;
  /** How many historical same-weekdays were averaged (higher = steadier). */
  sampleDays: number;
}

export interface DishForecast {
  name: string;
  totalQty: number;
  avgPerDay: number;
  /** Suggested prep count for a typical day (rounded up). */
  suggestedPrep: number;
}

export interface ForecastModel {
  windowDays: number;
  /** Demand-bearing orders in the window. */
  historyOrders: number;
  /** Distinct calendar days that had at least one order. */
  activeDays: number;
  avgOrdersPerDay: number;
  avgRevenuePerDay: number;
  /** last-7-days vs previous-7-days change (%). Null when no prior week. */
  trendPct: number | null;
  busiestWeekday: string | null;
  busiestPeriod: PeriodForecast | null;
  confidence: "low" | "medium" | "high";
  next7: DayForecast[];
  periods: PeriodForecast[];
  topDishes: DishForecast[];
  /** True when the history feed was capped (older orders may be missing). */
  truncated: boolean;
}

const WEEKDAY_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const PERIOD_DEFS: { key: PeriodKey; label: string; emoji: string; hours: number[] }[] = [
  { key: "breakfast", label: "Breakfast", emoji: "🌅", hours: [5, 6, 7, 8, 9, 10] },
  { key: "lunch", label: "Lunch", emoji: "☀️", hours: [11, 12, 13, 14, 15] },
  { key: "dinner", label: "Dinner", emoji: "🌙", hours: [16, 17, 18, 19, 20, 21, 22] },
  { key: "late", label: "Late night", emoji: "🌃", hours: [23, 0, 1, 2, 3, 4] },
];

function periodForHour(hour: number): PeriodKey {
  for (const p of PERIOD_DEFS) if (p.hours.includes(hour)) return p.key;
  return "late";
}

function toLocalYMD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDays(d: Date, n: number): Date {
  const c = new Date(d);
  c.setDate(c.getDate() + n);
  return c;
}

function mean(xs: number[]): number {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
}

function round(n: number): number {
  return Math.round(n);
}

export interface BuildForecastOpts {
  /** "Now" — the day the next-7 window starts on. Injected for testability. */
  today: Date;
  windowDays: number;
  /** True when fetchOrders hit its row cap (so history is partial). */
  truncated?: boolean;
}

/**
 * Turn a flat list of orders into a full forecast model. `orders` may contain
 * anything the API returned; we filter to demand-bearing rows inside.
 */
export function buildForecast(orders: OrderOut[], opts: BuildForecastOpts): ForecastModel {
  const { today, windowDays } = opts;
  const demand = orders.filter((o) => o.created_at && !EXCLUDED_STATUSES.has(o.status));

  // ── Per-date rollup (count + revenue + weekday) ────────────────────────────
  type DayAgg = { count: number; revenue: number; weekday: number };
  const byDate = new Map<string, DayAgg>();
  // ── Meal-period + dish rollups ─────────────────────────────────────────────
  const periodCount: Record<PeriodKey, number> = {
    breakfast: 0,
    lunch: 0,
    dinner: 0,
    late: 0,
  };
  const dishQty = new Map<string, number>();

  for (const o of demand) {
    const dt = new Date(o.created_at);
    if (Number.isNaN(dt.getTime())) continue;
    const ymd = toLocalYMD(dt);
    const agg = byDate.get(ymd) ?? { count: 0, revenue: 0, weekday: dt.getDay() };
    agg.count += 1;
    agg.revenue += Number.parseFloat(o.total_aed) || 0;
    byDate.set(ymd, agg);

    periodCount[periodForHour(dt.getHours())] += 1;

    for (const it of o.items ?? []) {
      const name = (it.name || "").trim();
      if (!name) continue;
      dishQty.set(name, (dishQty.get(name) ?? 0) + (Number(it.qty) || 0));
    }
  }

  const activeDays = byDate.size;
  const totalOrders = demand.length;
  const totalRevenue = Array.from(byDate.values()).reduce((a, d) => a + d.revenue, 0);
  const avgOrdersPerDay = activeDays ? totalOrders / activeDays : 0;
  const avgRevenuePerDay = activeDays ? totalRevenue / activeDays : 0;

  // ── Weekday averages (Mondays predict Mondays) ─────────────────────────────
  const wkCounts: number[][] = Array.from({ length: 7 }, () => []);
  const wkRevenue: number[][] = Array.from({ length: 7 }, () => []);
  for (const agg of byDate.values()) {
    wkCounts[agg.weekday].push(agg.count);
    wkRevenue[agg.weekday].push(agg.revenue);
  }

  const next7: DayForecast[] = [];
  for (let i = 0; i < 7; i++) {
    const d = addDays(today, i);
    const wd = d.getDay();
    next7.push({
      date: toLocalYMD(d),
      weekday: WEEKDAY_SHORT[wd],
      isToday: i === 0,
      predictedOrders: round(mean(wkCounts[wd])),
      predictedRevenue: mean(wkRevenue[wd]),
      sampleDays: wkCounts[wd].length,
    });
  }

  // Busiest weekday by average order count (only weekdays we have data for).
  let busiestWeekday: string | null = null;
  let bestWkAvg = -1;
  for (let wd = 0; wd < 7; wd++) {
    if (!wkCounts[wd].length) continue;
    const avg = mean(wkCounts[wd]);
    if (avg > bestWkAvg) {
      bestWkAvg = avg;
      busiestWeekday = WEEKDAY_SHORT[wd];
    }
  }

  // ── Meal-period forecast ───────────────────────────────────────────────────
  const periods: PeriodForecast[] = PERIOD_DEFS.map((p) => ({
    key: p.key,
    label: p.label,
    emoji: p.emoji,
    avgPerDay: activeDays ? periodCount[p.key] / activeDays : 0,
    sharePct: totalOrders ? (periodCount[p.key] / totalOrders) * 100 : 0,
  }));
  const busiestPeriod =
    periods.reduce<PeriodForecast | null>(
      (best, p) => (p.avgPerDay > (best?.avgPerDay ?? 0) ? p : best),
      null,
    ) ?? null;

  // ── Top dishes to prep ahead ───────────────────────────────────────────────
  const topDishes: DishForecast[] = Array.from(dishQty.entries())
    .map(([name, totalQty]) => {
      const avgPerDay = activeDays ? totalQty / activeDays : 0;
      return { name, totalQty, avgPerDay, suggestedPrep: Math.ceil(avgPerDay) };
    })
    .sort((a, b) => b.totalQty - a.totalQty)
    .slice(0, 8);

  // ── Trend: last 7 days vs the 7 before ─────────────────────────────────────
  const sumRange = (fromInclusive: number, toInclusive: number): number => {
    let sum = 0;
    for (let i = fromInclusive; i <= toInclusive; i++) {
      const agg = byDate.get(toLocalYMD(addDays(today, -i)));
      if (agg) sum += agg.count;
    }
    return sum;
  };
  const last7 = sumRange(1, 7);
  const prev7 = sumRange(8, 14);
  const trendPct = prev7 > 0 ? ((last7 - prev7) / prev7) * 100 : null;

  const confidence: ForecastModel["confidence"] =
    activeDays >= 28 ? "high" : activeDays >= 10 ? "medium" : "low";

  return {
    windowDays,
    historyOrders: totalOrders,
    activeDays,
    avgOrdersPerDay,
    avgRevenuePerDay,
    trendPct,
    busiestWeekday,
    busiestPeriod,
    confidence,
    next7,
    periods,
    topDishes,
    truncated: Boolean(opts.truncated),
  };
}
