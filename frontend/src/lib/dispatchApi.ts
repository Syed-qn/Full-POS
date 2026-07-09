import { apiClient } from "./apiClient";
import type { DispatchKpisOut, LiveOpsMapOut } from "./types";

/** GET /api/v1/dispatch/kpis — batch rate, avg stops, engine fallback %, avg delivery. */
export async function fetchDispatchKpis(): Promise<DispatchKpisOut> {
  return apiClient.get<DispatchKpisOut>("/api/v1/dispatch/kpis");
}

/** Active batch polylines and SLA rings for the live ops fleet map. */
export async function fetchLiveOpsMap(): Promise<LiveOpsMapOut> {
  return apiClient.get<LiveOpsMapOut>("/api/v1/dispatch/live-map");
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
