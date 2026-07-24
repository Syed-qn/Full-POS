import { describe, expect, it } from "vitest";
import { buildForecast } from "./forecast";
import type { OrderOut } from "./types";

/** Minimal OrderOut factory — only the fields the forecast reads. */
function order(partial: {
  id: number;
  created_at: string;
  total_aed: string;
  status?: string;
  items?: { name: string; qty: number }[];
}): OrderOut {
  return {
    id: partial.id,
    status: (partial.status ?? "delivered") as OrderOut["status"],
    customer_name: "T",
    customer_phone: "1",
    items: (partial.items ?? []).map((i) => ({
      dish_number: null,
      name: i.name,
      qty: i.qty,
      price_aed: "10.00",
    })),
    total_aed: partial.total_aed,
    rider_id: null,
    rider_name: null,
    sla_started_at: null,
    prep_deadline: null,
    cook_estimate_minutes: null,
    created_at: partial.created_at,
    address: null,
    lat: null,
    lng: null,
  };
}

// A fixed "today" so weekday math is deterministic.
// 2026-07-24 is a Friday (getDay() === 5).
const TODAY = new Date(2026, 6, 24, 15, 0, 0);

/** ISO for a local datetime n days before TODAY at the given hour. */
function daysAgo(n: number, hour: number): string {
  const d = new Date(2026, 6, 24, hour, 0, 0);
  d.setDate(d.getDate() - n);
  return d.toISOString();
}

describe("buildForecast", () => {
  it("returns an empty-but-safe model when there is no history", () => {
    const f = buildForecast([], { today: TODAY, windowDays: 28 });
    expect(f.historyOrders).toBe(0);
    expect(f.activeDays).toBe(0);
    expect(f.avgOrdersPerDay).toBe(0);
    expect(f.trendPct).toBeNull();
    expect(f.next7).toHaveLength(7);
    expect(f.next7.every((d) => d.predictedOrders === 0)).toBe(true);
    expect(f.topDishes).toHaveLength(0);
    expect(f.confidence).toBe("low");
  });

  it("excludes cancelled and draft orders from demand", () => {
    const orders = [
      order({ id: 1, created_at: daysAgo(1, 12), total_aed: "50.00" }),
      order({ id: 2, created_at: daysAgo(1, 12), total_aed: "50.00", status: "cancelled" }),
      order({ id: 3, created_at: daysAgo(1, 12), total_aed: "50.00", status: "draft" }),
    ];
    const f = buildForecast(orders, { today: TODAY, windowDays: 28 });
    expect(f.historyOrders).toBe(1);
  });

  it("predicts a weekday from the average of that same weekday", () => {
    // Two prior Fridays with 2 and 4 orders → predict 3 for the upcoming Friday.
    const orders = [
      order({ id: 1, created_at: daysAgo(7, 12), total_aed: "10.00" }),
      order({ id: 2, created_at: daysAgo(7, 13), total_aed: "10.00" }),
      order({ id: 3, created_at: daysAgo(14, 12), total_aed: "10.00" }),
      order({ id: 4, created_at: daysAgo(14, 13), total_aed: "10.00" }),
      order({ id: 5, created_at: daysAgo(14, 14), total_aed: "10.00" }),
      order({ id: 6, created_at: daysAgo(14, 19), total_aed: "10.00" }),
    ];
    const f = buildForecast(orders, { today: TODAY, windowDays: 28 });
    const friday = f.next7[0]; // TODAY is Friday
    expect(friday.weekday).toBe("Fri");
    expect(friday.isToday).toBe(true);
    expect(friday.predictedOrders).toBe(3);
    expect(friday.sampleDays).toBe(2);
  });

  it("buckets orders into meal periods and finds the busiest", () => {
    const orders = [
      order({ id: 1, created_at: daysAgo(1, 8), total_aed: "10" }), // breakfast
      order({ id: 2, created_at: daysAgo(1, 13), total_aed: "10" }), // lunch
      order({ id: 3, created_at: daysAgo(1, 19), total_aed: "10" }), // dinner
      order({ id: 4, created_at: daysAgo(1, 20), total_aed: "10" }), // dinner
      order({ id: 5, created_at: daysAgo(1, 21), total_aed: "10" }), // dinner
    ];
    const f = buildForecast(orders, { today: TODAY, windowDays: 28 });
    expect(f.busiestPeriod?.key).toBe("dinner");
    const dinner = f.periods.find((p) => p.key === "dinner")!;
    expect(dinner.sharePct).toBeCloseTo(60, 5);
  });

  it("ranks top dishes and suggests prep counts", () => {
    const orders = [
      order({ id: 1, created_at: daysAgo(1, 12), total_aed: "10", items: [{ name: "Biryani", qty: 3 }] }),
      order({ id: 2, created_at: daysAgo(2, 12), total_aed: "10", items: [{ name: "Biryani", qty: 2 }, { name: "Fries", qty: 1 }] }),
    ];
    const f = buildForecast(orders, { today: TODAY, windowDays: 28 });
    expect(f.topDishes[0].name).toBe("Biryani");
    expect(f.topDishes[0].totalQty).toBe(5);
    // 2 active days → avg 2.5/day → prep 3.
    expect(f.topDishes[0].suggestedPrep).toBe(3);
  });

  it("computes a week-over-week trend", () => {
    // prev 7 days (8..14 ago): 2 orders; last 7 days (1..7 ago): 4 orders → +100%.
    const orders = [
      order({ id: 1, created_at: daysAgo(10, 12), total_aed: "10" }),
      order({ id: 2, created_at: daysAgo(11, 12), total_aed: "10" }),
      order({ id: 3, created_at: daysAgo(2, 12), total_aed: "10" }),
      order({ id: 4, created_at: daysAgo(3, 12), total_aed: "10" }),
      order({ id: 5, created_at: daysAgo(4, 12), total_aed: "10" }),
      order({ id: 6, created_at: daysAgo(5, 12), total_aed: "10" }),
    ];
    const f = buildForecast(orders, { today: TODAY, windowDays: 28 });
    expect(f.trendPct).toBeCloseTo(100, 5);
  });
});
