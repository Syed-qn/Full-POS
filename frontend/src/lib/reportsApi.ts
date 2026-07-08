import { apiClient, ApiError, TOKEN_KEY } from "./apiClient";
import type {
  ItemPerformanceRow,
  LaborHoursRow,
  PrepTimeRow,
  RetentionReport,
  SalesRollupRow,
  ZReport,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function getSalesRollup(
  startDate: string,
  endDate: string,
  granularity: "daily" | "hourly" | "weekly" | "monthly" = "daily",
): Promise<SalesRollupRow[]> {
  return apiClient.get<SalesRollupRow[]>(
    `/api/v1/reports/sales-rollup?start_date=${startDate}&end_date=${endDate}&granularity=${granularity}`,
  );
}

export async function getItemPerformance(startDate: string, endDate: string): Promise<ItemPerformanceRow[]> {
  return apiClient.get<ItemPerformanceRow[]>(
    `/api/v1/reports/item-performance?start_date=${startDate}&end_date=${endDate}`,
  );
}

export function itemPerformanceCsvUrl(startDate: string, endDate: string): string {
  return `/api/v1/reports/item-performance.csv?start_date=${startDate}&end_date=${endDate}`;
}

/**
 * Fetches the item-performance CSV export with the same Bearer auth header
 * apiClient uses, since apiClient only supports JSON responses. A plain
 * anchor `href` to the endpoint sends no credentials (auth here is a
 * localStorage token, not a cookie) and always 401s.
 */
export async function fetchItemPerformanceCsv(startDate: string, endDate: string): Promise<Blob> {
  const token = localStorage.getItem(TOKEN_KEY);
  const resp = await fetch(`${API_BASE}${itemPerformanceCsvUrl(startDate, endDate)}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = typeof data.detail === "string" ? data.detail : detail;
    } catch {
      /* non-JSON */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.blob();
}

export async function getZReport(targetDate: string): Promise<ZReport> {
  return apiClient.get<ZReport>(`/api/v1/reports/z-report?target_date=${targetDate}`);
}

export async function getRetention(startDate: string, endDate: string): Promise<RetentionReport> {
  return apiClient.get<RetentionReport>(
    `/api/v1/reports/retention?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getLaborHours(targetDate: string): Promise<LaborHoursRow[]> {
  return apiClient.get<LaborHoursRow[]>(`/api/v1/reports/labor-hours?target_date=${targetDate}`);
}

export async function getPrepTimeByItem(startDate: string, endDate: string): Promise<PrepTimeRow[]> {
  return apiClient.get<PrepTimeRow[]>(
    `/api/v1/reports/prep-time-by-item?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getPrepTimeByStaff(startDate: string, endDate: string): Promise<PrepTimeRow[]> {
  return apiClient.get<PrepTimeRow[]>(
    `/api/v1/reports/prep-time-by-staff?start_date=${startDate}&end_date=${endDate}`,
  );
}
