import { apiClient } from "./apiClient";

export interface PosConfig {
  pos_enabled: boolean;
  pos_account: string;
  pos_location: string;
  pos_base_url?: string | null;
}

export interface PosSyncAccepted {
  started: boolean;
  mode: string; // "celery" | "inprocess"
  detail: string;
}

export interface PosSyncStatus {
  state: string; // idle | running | done | error
  started_at?: string | null;
  finished_at?: string | null;
  fetched?: number | null;
  created?: number | null;
  updated?: number | null;
  deactivated?: number | null;
  images?: number | null;
  skipped_empty?: boolean | null;
  error?: string | null;
}

export async function getPosConfig(): Promise<PosConfig> {
  return apiClient.get<PosConfig>("/api/v1/pos/config");
}

export async function savePosConfig(body: Partial<PosConfig>): Promise<PosConfig> {
  return apiClient.patch<PosConfig>("/api/v1/pos/config", body);
}

/** Kick off the full POS sync in the background. Returns immediately. */
export async function startPosSync(): Promise<PosSyncAccepted> {
  return apiClient.post<PosSyncAccepted>("/api/v1/pos/sync");
}

export async function getPosSyncStatus(): Promise<PosSyncStatus> {
  return apiClient.get<PosSyncStatus>("/api/v1/pos/sync/status");
}
