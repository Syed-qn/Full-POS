import { describe, expect, it } from "vitest";
import { hourlyHeatmap, topDishes } from "./analyticsBreakdowns";
import type { OrderOut } from "./types";

function order(p: {
  id: number;
  created_at: string;
  status?: string;
  items?: { name: string; qty: number; price_aed: string }[];
}): OrderOut {
  return {
    id: p.id,
    status: (p.status ?? "delivered") as OrderOut["status"],
    customer_name: "T",
    customer_phone: "1",
    items: (p.items ?? []).map((i) => ({ dish_number: null, ...i })),
    total_aed: "0",
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

describe("topDishes", () => {
  it("ranks by revenue (qty × price) and sums across orders", () => {
    const rows = topDishes([
      order({ id: 1, created_at: "2026-07-24T08:00:00Z", items: [
        { name: "Biryani", qty: 2, price_aed: "30.00" }, // 60
        { name: "Fries", qty: 1, price_aed: "10.00" }, // 10
      ] }),
      order({ id: 2, created_at: "2026-07-24T09:00:00Z", items: [
        { name: "Biryani", qty: 1, price_aed: "30.00" }, // +30 => 90, qty 3
      ] }),
    ]);
    expect(rows[0]).toEqual({ name: "Biryani", qty: 3, revenue: 90 });
    expect(rows[1]).toEqual({ name: "Fries", qty: 1, revenue: 10 });
  });

  it("excludes cancelled orders and respects the limit", () => {
    const rows = topDishes(
      [
        order({ id: 1, created_at: "2026-07-24T08:00:00Z", status: "cancelled", items: [
          { name: "Ghost", qty: 5, price_aed: "99.00" },
        ] }),
        order({ id: 2, created_at: "2026-07-24T08:00:00Z", items: [
          { name: "A", qty: 1, price_aed: "5" },
          { name: "B", qty: 1, price_aed: "4" },
          { name: "C", qty: 1, price_aed: "3" },
        ] }),
      ],
      2,
    );
    expect(rows.map((r) => r.name)).toEqual(["A", "B"]);
    expect(rows.find((r) => r.name === "Ghost")).toBeUndefined();
  });
});

describe("hourlyHeatmap", () => {
  it("buckets orders into Dubai hour × weekday", () => {
    // 2026-07-24T21:00Z -> Dubai 2026-07-25 01:00 (Sat, hour 1).
    // 2026-07-24T08:00Z -> Dubai 2026-07-24 12:00 (Fri, hour 12).
    const h = hourlyHeatmap([
      order({ id: 1, created_at: "2026-07-24T21:00:00Z" }),
      order({ id: 2, created_at: "2026-07-24T08:00:00Z" }),
      order({ id: 3, created_at: "2026-07-24T08:30:00Z" }),
    ]);
    expect(h.total).toBe(3);
    expect(h.grid[5][12]).toBe(2); // Fri 12:00
    expect(h.grid[6][1]).toBe(1); // Sat 01:00
    expect(h.max).toBe(2);
    expect(h.byHour[12]).toBe(2);
    expect(h.byWeekday[5]).toBe(2);
  });

  it("returns an all-zero grid for no data", () => {
    const h = hourlyHeatmap([]);
    expect(h.max).toBe(0);
    expect(h.total).toBe(0);
    expect(h.grid).toHaveLength(7);
    expect(h.grid[0]).toHaveLength(24);
  });
});
