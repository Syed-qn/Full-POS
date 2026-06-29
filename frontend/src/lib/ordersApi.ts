import { ApiError, apiClient } from "./apiClient";
import fixtureOrders from "./fixtures/orders.json";
import type { OrderOut } from "./types";

// Fixture fallback is a dev-only convenience for endpoints not yet deployed.
// In production we rethrow so failures surface instead of masking with stale data.
// NOTE: vitest runs with import.meta.env.DEV === true, so existing tests still
// exercise the fixture fallback path.
export type FetchOrdersOpts = {
  /** Skip batch-preview grouping on list (faster for live-ops polls). */
  previewBatch?: boolean;
  status?: string;
  limit?: number;
};

export async function fetchOrders(opts?: FetchOrdersOpts): Promise<OrderOut[]> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.previewBatch === false) params.set("preview_batch", "false");
  const qs = params.toString();
  const path = qs ? `/api/v1/orders?${qs}` : "/api/v1/orders";
  try {
    return await apiClient.get<OrderOut[]>(path);
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

export async function reassignOrder(id: number, riderId: number): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${id}/reassign`, { rider_id: riderId });
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
