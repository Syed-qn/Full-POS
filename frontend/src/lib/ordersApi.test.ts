import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchOrders } from "./ordersApi";

describe("ordersApi", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns live orders when endpoint responds", async () => {
    const live = [{ id: 1, status: "ready", customer_name: "X", customer_phone: "+9715", items: [], total_aed: "10.00", rider_id: null, rider_name: null, sla_started_at: null, created_at: "2026-06-06T09:00:00Z", address: null, lat: null, lng: null }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(live), { status: 200 })));
    const orders = await fetchOrders();
    expect(orders).toHaveLength(1);
    expect(orders[0].customer_name).toBe("X");
  });

  it("falls back to fixtures on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not found", { status: 404 })));
    const orders = await fetchOrders();
    expect(orders.length).toBeGreaterThan(0);
    expect(orders.some((o) => o.id === 47)).toBe(true);
  });

  it("falls back to fixtures on network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const orders = await fetchOrders();
    expect(orders.some((o) => o.id === 47)).toBe(true);
  });
});
