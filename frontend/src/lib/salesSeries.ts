/**
 * Daily sales series for the Analytics trend chart — orders + revenue per day,
 * bucketed by the restaurant's timezone (Asia/Dubai, UTC+4, no DST) so a "day"
 * means a Dubai trading day, not a UTC one. Pure + deterministic for testing.
 */

import type { OrderOut } from "./types";

const EXCLUDED_STATUSES = new Set(["cancelled", "draft"]);
const DUBAI_OFFSET_MS = 4 * 60 * 60 * 1000;

export interface DailyPoint {
  /** YYYY-MM-DD (Dubai). */
  date: string;
  /** Short "24 Jul" label for the axis. */
  label: string;
  orders: number;
  revenue: number;
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function dubaiYMD(t: number): { ymd: string; label: string } {
  const d = new Date(t + DUBAI_OFFSET_MS);
  const y = d.getUTCFullYear();
  const mo = d.getUTCMonth();
  const day = d.getUTCDate();
  const ymd = `${y}-${String(mo + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  return { ymd, label: `${day} ${MONTHS[mo]}` };
}

/**
 * Roll a flat order list into one point per Dubai day, sorted ascending.
 * Cancelled/draft rows are excluded. Days with no demand are simply absent.
 */
export function buildDailySeries(orders: OrderOut[]): DailyPoint[] {
  const byDay = new Map<string, DailyPoint>();
  for (const o of orders) {
    if (!o.created_at || EXCLUDED_STATUSES.has(o.status)) continue;
    const t = Date.parse(o.created_at);
    if (Number.isNaN(t)) continue;
    const { ymd, label } = dubaiYMD(t);
    const pt = byDay.get(ymd) ?? { date: ymd, label, orders: 0, revenue: 0 };
    pt.orders += 1;
    pt.revenue += Number.parseFloat(o.total_aed) || 0;
    byDay.set(ymd, pt);
  }
  return Array.from(byDay.values()).sort((a, b) => a.date.localeCompare(b.date));
}
