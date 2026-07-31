import { API_BASE, TOKEN_KEY, apiClient } from "./apiClient";

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
  return apiClient.post<{
    id?: number;
    status: string;
    size_bytes?: number;
    /** False when today already had one — the two outcomes must be tellable apart. */
    created: boolean;
  }>("/api/v1/reliability/backups/daily", {});
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
      /** False when the job row outlived its file — e.g. after a redeploy. */
      file_present: boolean;
      meta: { backend?: string; truncated?: string[]; counts?: Record<string, number> } | null;
    }>
  >("/api/v1/reliability/backups");
}

export type BackupTarget = {
  backend: "local" | "s3";
  location: string;
  endpoint: string | null;
  /** Whether the files survive a redeploy. Drives the warning banner. */
  durable: boolean;
  note: string;
  restore_enabled: boolean;
  /** Exact text the restore endpoint accepts, e.g. "RESTORE 1". */
  restore_confirm_phrase: string;
};

export function getBackupTarget() {
  return apiClient.get<BackupTarget>("/api/v1/reliability/backup-target");
}

export function restoreBackup(id: number, confirm: string) {
  return apiClient.post<{
    restore_mode: string;
    pre_restore_backup_id: number;
    deleted: Record<string, number>;
    inserted: Record<string, number>;
  }>(`/api/v1/reliability/backups/${id}/restore`, { confirm });
}

/**
 * Download a snapshot to the user's machine.
 *
 * A plain <a href> cannot be used: the endpoint is bearer-authenticated and an
 * anchor sends no Authorization header. Fetch the bytes, then hand the browser
 * a blob URL — which is also why "Full data export" previously downloaded
 * nothing at all.
 */
export async function downloadBackup(id: number): Promise<string> {
  const token = localStorage.getItem(TOKEN_KEY);
  const resp = await fetch(`${API_BASE}/api/v1/reliability/backups/${id}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) throw new Error(`download failed (${resp.status})`);
  const disposition = resp.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `backup-${id}.json`;
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return filename;
}

export function verifyBackup(id: number) {
  return apiClient.post<{
    ok: boolean;
    restorable: boolean;
    checks: Record<string, boolean>;
    /** Plain-language verdict for a restaurant manager, not a checksum. */
    summary: string;
    checksum: string;
  }>(`/api/v1/reliability/backups/${id}/verify`, {});
}

export type BackupHealth = {
  has_backup: boolean;
  ok: boolean;
  summary: string;
  backup_job_id?: number;
  taken_at?: string | null;
  size_bytes?: number;
  /** Whether TODAY (Asia/Dubai) has a completed backup yet. */
  backed_up_today: boolean;
  today_backup_id?: number | null;
};

/** Health of the NEWEST backup — the one a restore would actually use. */
export function getBackupHealth() {
  return apiClient.get<BackupHealth>("/api/v1/reliability/backups/health");
}

export function restorePreview(id: number) {
  return apiClient.post<{
    restore_mode: string;
    counts: Record<string, number>;
    message: string;
  }>(`/api/v1/reliability/backups/${id}/restore-preview`, {});
}

export function exportDataPack() {
  return apiClient.post<{
    backup_job_id: number;
    checksum: string;
    size_bytes: number;
    download_url: string;
  }>("/api/v1/reliability/export", {});
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
