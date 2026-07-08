import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getItemPerformance, getSalesRollup, getZReport } from "./reportsApi";

describe("reportsApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (String(url).includes("/sales-rollup")) {
          return Promise.resolve(
            new Response(JSON.stringify([{ bucket: "2026-07-08", revenue_aed: "500.00", order_count: 10 }]), { status: 200 }),
          );
        }
        if (String(url).includes("/item-performance")) {
          return Promise.resolve(
            new Response(
              JSON.stringify([{ dish_name: "Biryani", order_count: 5, revenue_aed: "100.00", food_cost_aed: "40.00", margin_aed: "60.00", margin_pct: 60 }]),
              { status: 200 },
            ),
          );
        }
        if (String(url).includes("/z-report")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ gross_sales_aed: "500.00", total_discounts_aed: "0.00", cod_collected_aed: "500.00", drawer_sessions: [] }),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(new Response("[]", { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("gets sales rollup", async () => {
    const rows = await getSalesRollup("2026-07-01", "2026-07-08", "daily");
    expect(rows[0].bucket).toBe("2026-07-08");
    expect(rows[0].revenue_aed).toBe("500.00");
  });

  it("gets item performance", async () => {
    const rows = await getItemPerformance("2026-07-01", "2026-07-08");
    expect(rows[0].dish_name).toBe("Biryani");
  });

  it("gets z-report", async () => {
    const report = await getZReport("2026-07-08");
    expect(report.gross_sales_aed).toBe("500.00");
  });
});
