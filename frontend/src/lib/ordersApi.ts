import { ApiError, apiClient } from "./apiClient";
import fixtureOrders from "./fixtures/orders.json";
import type { OrderOut } from "./types";

// Fixture fallback is a dev-only convenience for endpoints not yet deployed.
// In production we rethrow so failures surface instead of masking with stale data.
// NOTE: vitest runs with import.meta.env.DEV === true, so existing tests still
// exercise the fixture fallback path.
export async function fetchOrders(): Promise<OrderOut[]> {
  try {
    return await apiClient.get<OrderOut[]>("/api/v1/orders");
  } catch (err) {
    if (!import.meta.env.DEV) throw err;
    // Endpoint not yet deployed (404) or backend unreachable → recorded fixtures.
    if (err instanceof ApiError && err.status !== 404) throw err;
    return fixtureOrders as OrderOut[];
  }
}

export async function cancelOrder(id: number, reason?: string): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${id}/cancel`, reason ? { reason } : {});
}

export async function fetchOrder(id: number): Promise<OrderOut> {
  try {
    return await apiClient.get<OrderOut>(`/api/v1/orders/${id}`);
  } catch (err) {
    if (!import.meta.env.DEV) throw err;
    if (err instanceof ApiError && err.status !== 404) throw err;
    const match = (fixtureOrders as OrderOut[]).find((o) => o.id === id);
    if (!match) throw err;
    return match;
  }
}
