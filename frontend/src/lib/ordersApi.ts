import { ApiError, apiClient } from "./apiClient";
import fixtureOrders from "./fixtures/orders.json";
import type { OrderOut } from "./types";

export async function fetchOrders(): Promise<OrderOut[]> {
  try {
    return await apiClient.get<OrderOut[]>("/api/v1/orders");
  } catch (err) {
    // Endpoint not yet deployed (404) or backend unreachable → recorded fixtures.
    if (err instanceof ApiError && err.status !== 404) throw err;
    return fixtureOrders as OrderOut[];
  }
}

export async function fetchOrder(id: number): Promise<OrderOut> {
  try {
    return await apiClient.get<OrderOut>(`/api/v1/orders/${id}`);
  } catch (err) {
    if (err instanceof ApiError && err.status !== 404) throw err;
    const match = (fixtureOrders as OrderOut[]).find((o) => o.id === id);
    if (!match) throw err;
    return match;
  }
}
