import { apiClient } from "./apiClient";
import type { DispatchKpisOut, LiveOpsMapOut } from "./types";

/** GET /api/v1/dispatch/kpis — batch rate, avg stops, engine fallback %. */
export async function fetchDispatchKpis(): Promise<DispatchKpisOut> {
  return apiClient.get<DispatchKpisOut>("/api/v1/dispatch/kpis");
}

/** Active batch polylines and SLA rings for the live ops fleet map. */
export async function fetchLiveOpsMap(): Promise<LiveOpsMapOut> {
  return apiClient.get<LiveOpsMapOut>("/api/v1/dispatch/live-map");
}