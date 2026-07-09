import { ApiError, apiClient } from "./apiClient";
import fixtureOrders from "./fixtures/orders.json";
import type { OrderOut } from "./types";

// Fixture fallback is a dev-only convenience for endpoints not yet deployed.
// In production we rethrow so failures surface instead of masking with stale data.
// NOTE: vitest runs with import.meta.env.DEV === true, so existing tests still
// exercise the fixture fallback path.
function toYMD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Dev fixture path mirrors server filters so local UI matches production behaviour. */
function applyFixtureFilters(orders: OrderOut[], opts?: FetchOrdersOpts): OrderOut[] {
  let rows = [...orders];
  if (opts?.status) rows = rows.filter((o) => o.status === opts.status);
  if (opts?.fromDate || opts?.toDate) {
    rows = rows.filter((o) => {
      const day = o.created_at ? toYMD(new Date(o.created_at)) : "";
      if (!day) return false;
      if (opts.fromDate && day < opts.fromDate) return false;
      if (opts.toDate && day > opts.toDate) return false;
      return true;
    });
  }
  if (opts?.q) {
    const q = opts.q.trim().replace(/^#/, "").toLowerCase();
    rows = rows.filter(
      (o) =>
        String(o.id).includes(q) ||
        o.customer_name.toLowerCase().includes(q) ||
        o.customer_phone.includes(q),
    );
  }
  rows.sort((a, b) => b.id - a.id);
  const offset = opts?.offset ?? 0;
  const limit = opts?.limit ?? 50;
  return rows.slice(offset, offset + limit);
}

export type FetchOrdersOpts = {
  /** Skip batch-preview grouping on list (faster for live-ops polls). */
  previewBatch?: boolean;
  status?: string;
  limit?: number;
  offset?: number;
  fromDate?: string;
  toDate?: string;
  q?: string;
  /** Category 8 — filter by source_channel / aggregator_source */
  channel?: string;
};

export async function fetchOrders(opts?: FetchOrdersOpts): Promise<OrderOut[]> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null && opts.offset > 0) params.set("offset", String(opts.offset));
  if (opts?.fromDate) params.set("from_date", opts.fromDate);
  if (opts?.toDate) params.set("to_date", opts.toDate);
  if (opts?.q) params.set("q", opts.q);
  if (opts?.channel) params.set("channel", opts.channel);
  if (opts?.previewBatch === false) params.set("preview_batch", "false");
  const qs = params.toString();
  const path = qs ? `/api/v1/orders?${qs}` : "/api/v1/orders";
  try {
    return await apiClient.get<OrderOut[]>(path);
  } catch (err) {
    if (!import.meta.env.DEV) throw err;
    // Endpoint not yet deployed (404) or backend unreachable → recorded fixtures.
    if (err instanceof ApiError && err.status !== 404) throw err;
    return applyFixtureFilters(fixtureOrders as OrderOut[], opts);
  }
}

export async function cancelOrder(id: number, reason?: string): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${id}/cancel`, reason ? { reason } : {});
}

export async function reassignOrder(id: number, riderId: number): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${id}/reassign`, { rider_id: riderId });
}

export async function assignOrder(id: number, riderId: number): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${id}/assign`, { rider_id: riderId });
}

export async function setOrderPriority(id: number, priority: string): Promise<OrderOut> {
  return apiClient.patch<OrderOut>(`/api/v1/orders/${id}/priority`, { priority });
}

export async function markDeliveryFailed(id: number, reason: string): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${id}/delivery-failed`, { reason });
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