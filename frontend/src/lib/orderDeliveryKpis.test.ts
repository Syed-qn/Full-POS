import { describe, expect, it } from "vitest";
import type { OrderOut } from "./types";
import { computeOrderDeliveryKpis } from "./orderDeliveryKpis";

function order(partial: Partial<OrderOut> & Pick<OrderOut, "id" | "status">): OrderOut {
  return {
    customer_name: "Test",
    customer_phone: "+971500000000",
    total_aed: "50.00",
    items: [],
    sla_started_at: null,
    ...partial,
  };
}

describe("orderDeliveryKpis", () => {
  it("computes delivered count, revenue, and completion rate", () => {
    const kpis = computeOrderDeliveryKpis([
      order({ id: 1, status: "delivered", total_aed: "40.00" }),
      order({ id: 2, status: "delivered", total_aed: "60.00" }),
      order({ id: 3, status: "cancelled", total_aed: "10.00" }),
      order({ id: 4, status: "preparing", total_aed: "25.00" }),
    ]);
    expect(kpis).toEqual({
      orders: 4,
      delivered: 2,
      revenueAed: 100,
      completionPct: 67,
    });
  });

  it("returns 100% completion when there are no finished orders", () => {
    const kpis = computeOrderDeliveryKpis([
      order({ id: 1, status: "preparing", total_aed: "25.00" }),
    ]);
    expect(kpis.completionPct).toBe(100);
  });
});