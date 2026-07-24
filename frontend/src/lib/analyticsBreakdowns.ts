/**
 * Analytics breakdowns computed from real orders — top-selling dishes and an
 * hour×weekday demand heatmap. Bucketed in Asia/Dubai (UTC+4, no DST) so hours
 * and weekdays are the restaurant's real trading clock. Pure + deterministic.
 */

import type { OrderOut } from "./types";

const EXCLUDED_STATUSES = new Set(["cancelled", "draft"]);
const DUBAI_OFFSET_MS = 4 * 60 * 60 * 1000;

export interface DishSales {
  name: string;
  qty: number;
  revenue: number;
}

export interface HeatmapResult {
  /** grid[weekday 0=Sun..6=Sat][hour 0..23] = order count. */
  grid: number[][];
  /** Busiest single cell count (for colour scaling); 0 when no data. */
  max: number;
  /** Total demand orders counted. */
  total: number;
  /** Order counts summed per hour (0..23). */
  byHour: number[];
  /** Order counts summed per weekday (0..6). */
  byWeekday: number[];
}

function isDemand(o: OrderOut): boolean {
  return Boolean(o.created_at) && !EXCLUDED_STATUSES.has(o.status);
}

/**
 * Top dishes by revenue across the given orders. Revenue is qty × unit price.
 * Returns at most `limit` entries, highest revenue first.
 */
export function topDishes(orders: OrderOut[], limit = 8): DishSales[] {
  const byName = new Map<string, DishSales>();
  for (const o of orders) {
    if (!isDemand(o)) continue;
    for (const it of o.items ?? []) {
      const name = (it.name || "").trim();
      if (!name) continue;
      const qty = Number(it.qty) || 0;
      const price = Number.parseFloat(it.price_aed) || 0;
      const row = byName.get(name) ?? { name, qty: 0, revenue: 0 };
      row.qty += qty;
      row.revenue += qty * price;
      byName.set(name, row);
    }
  }
  return Array.from(byName.values())
    .sort((a, b) => b.revenue - a.revenue || b.qty - a.qty)
    .slice(0, limit);
}

/** Demand heatmap: order counts per Dubai hour × weekday. */
export function hourlyHeatmap(orders: OrderOut[]): HeatmapResult {
  const grid: number[][] = Array.from({ length: 7 }, () => new Array(24).fill(0));
  const byHour = new Array(24).fill(0);
  const byWeekday = new Array(7).fill(0);
  let max = 0;
  let total = 0;

  for (const o of orders) {
    if (!isDemand(o)) continue;
    const t = Date.parse(o.created_at);
    if (Number.isNaN(t)) continue;
    const d = new Date(t + DUBAI_OFFSET_MS);
    const wd = d.getUTCDay();
    const hr = d.getUTCHours();
    grid[wd][hr] += 1;
    byHour[hr] += 1;
    byWeekday[wd] += 1;
    total += 1;
    if (grid[wd][hr] > max) max = grid[wd][hr];
  }

  return { grid, max, total, byHour, byWeekday };
}
