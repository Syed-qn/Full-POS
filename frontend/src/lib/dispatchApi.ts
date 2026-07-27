import { apiClient } from "./apiClient";
import type { DispatchKpisOut } from "./types";

/** GET /api/v1/dispatch/kpis — batch rate, avg stops, engine fallback %, avg delivery. */
export async function fetchDispatchKpis(): Promise<DispatchKpisOut> {
  return apiClient.get<DispatchKpisOut>("/api/v1/dispatch/kpis");
}

export async function reconcileRiderCod(
  riderId: number,
  body?: { shift_date?: string; declared_collected_aed?: string },
) {
  return apiClient.post<{
    id: number;
    rider_id: number;
    shift_date: string;
    expected_total_aed: string;
    collected_total_aed: string;
    variance_aed: string;
    status: string;
  }>(`/api/v1/cod/shift/${riderId}/reconcile`, body ?? {});
}

export async function listCodCollections(riderId: number) {
  return apiClient.get<{
    rider_id: number;
    collections: Array<{ order_id: number; amount_aed: string; collected_at: string }>;
  }>(`/api/v1/cod/shift/${riderId}`);
}
