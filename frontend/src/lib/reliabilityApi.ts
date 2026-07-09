import { apiClient } from "./apiClient";

export function getNetworkStatus() {
  return apiClient.get<{
    devices_online: number;
    devices_offline: number;
    devices_total: number;
    last_backup_at: string | null;
    unacked_errors: number;
    devices: Array<{
      device_id: string;
      name: string;
      role: string;
      status: string;
      is_failover_active: boolean;
    }>;
  }>("/api/v1/reliability/network-status");
}

export function createBackup(kind = "manual") {
  return apiClient.post<{
    id: number;
    status: string;
    storage_path: string;
    size_bytes: number;
    checksum: string;
  }>(`/api/v1/reliability/backups?kind=${encodeURIComponent(kind)}`, {});
}

export function runDailyBackup() {
  return apiClient.post<{ id?: number; status: string }>("/api/v1/reliability/backups/daily", {});
}

export function listBackups() {
  return apiClient.get<
    Array<{
      id: number;
      kind: string;
      status: string;
      size_bytes: number;
      checksum: string | null;
      completed_at: string | null;
      storage_path: string | null;
    }>
  >("/api/v1/reliability/backups");
}

export function verifyBackup(id: number) {
  return apiClient.post<{ ok: boolean; checksum: string }>(
    `/api/v1/reliability/backups/${id}/verify`,
    {},
  );
}

export function restorePreview(id: number) {
  return apiClient.post<{
    restore_mode: string;
    counts: Record<string, number>;
    message: string;
  }>(`/api/v1/reliability/backups/${id}/restore-preview`, {});
}

export function exportDataPack() {
  return apiClient.post<{ backup_job_id: number; checksum: string; size_bytes: number }>(
    "/api/v1/reliability/export",
    {},
  );
}

export function listDevices() {
  return apiClient.get<
    Array<{
      device_id: string;
      name: string;
      role: string;
      status: string;
      is_failover_active: boolean;
    }>
  >("/api/v1/reliability/devices");
}

export function registerDevice(body: {
  device_id: string;
  name: string;
  device_type?: string;
  role?: string;
}) {
  return apiClient.post("/api/v1/reliability/devices", body);
}

export function promoteFailover(deviceId: string) {
  return apiClient.post(`/api/v1/reliability/devices/${encodeURIComponent(deviceId)}/failover`, {});
}

export function listErrors(unackedOnly = false) {
  return apiClient.get<
    Array<{
      id: number;
      level: string;
      source: string;
      message: string;
      acknowledged: boolean;
      created_at?: string | null;
    }>
  >(`/api/v1/reliability/errors?unacked_only=${unackedOnly}`);
}

export function ackError(id: number) {
  return apiClient.post(`/api/v1/reliability/errors/${id}/ack`, {});
}

export function reportClientError(message: string, detail?: Record<string, unknown>) {
  return apiClient.post("/api/v1/reliability/errors", {
    message,
    source: "dashboard",
    level: "error",
    detail: detail ?? {},
  });
}

export function listAuditLog(params?: { limit?: number; entity?: string }) {
  const q = new URLSearchParams();
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.entity) q.set("entity", params.entity);
  const qs = q.toString();
  return apiClient.get<{
    rows: Array<{
      id: number;
      actor: string;
      entity: string;
      entity_id: string;
      action: string;
      created_at: string;
    }>;
  }>(`/api/v1/audit-log${qs ? `?${qs}` : ""}`);
}

export function getBackupReadiness() {
  return apiClient.get<{
    orders_count: number;
    customers_count: number;
    dishes_count: number;
    last_backup_id?: number | null;
    last_backup_at?: string | null;
    cloud_backup_configured?: boolean;
  }>("/api/v1/audit-log/backup-readiness");
}
