import { describe, expect, it } from "vitest";
import { buildDailySeries } from "./salesSeries";
import type { OrderOut } from "./types";

function order(p: {
  id: number;
  created_at: string;
  total_aed: string;
  status?: string;
}): OrderOut {
  return {
    id: p.id,
    status: (p.status ?? "delivered") as OrderOut["status"],
    customer_name: "T",
    customer_phone: "1",
    items: [],
    total_aed: p.total_aed,
    rider_id: null,
    rider_name: null,
    sla_started_at: null,
    prep_deadline: null,
    cook_estimate_minutes: null,
    created_at: p.created_at,
    address: null,
    lat: null,
    lng: null,
  };
}

describe("buildDailySeries", () => {
  it("returns empty for no orders", () => {
    expect(buildDailySeries([])).toEqual([]);
  });

  it("groups by Dubai day and sums orders + revenue, sorted ascending", () => {
    const series = buildDailySeries([
      // Dubai 2026-07-24 (UTC 08:00) ×2
      order({ id: 1, created_at: "2026-07-24T08:00:00Z", total_aed: "50.00" }),
      order({ id: 2, created_at: "2026-07-24T09:30:00Z", total_aed: "25.50" }),
      // Dubai 2026-07-23
      order({ id: 3, created_at: "2026-07-23T10:00:00Z", total_aed: "100.00" }),
    ]);
    expect(series.map((p) => p.date)).toEqual(["2026-07-23", "2026-07-24"]);
    expect(series[1]).toMatchObject({ orders: 2, revenue: 75.5, label: "24 Jul" });
    expect(series[0]).toMatchObject({ orders: 1, revenue: 100 });
  });

  it("rolls a late-UTC order into the correct Dubai day", () => {
    // 2026-07-24T21:00Z is 2026-07-25 01:00 in Dubai → counts as the 25th.
    const series = buildDailySeries([
      order({ id: 1, created_at: "2026-07-24T21:00:00Z", total_aed: "10.00" }),
    ]);
    expect(series[0].date).toBe("2026-07-25");
  });

  it("excludes cancelled and draft orders", () => {
    const series = buildDailySeries([
      order({ id: 1, created_at: "2026-07-24T08:00:00Z", total_aed: "10", status: "cancelled" }),
      order({ id: 2, created_at: "2026-07-24T08:00:00Z", total_aed: "10", status: "draft" }),
    ]);
    expect(series).toEqual([]);
  });
});
