import { apiClient } from "./apiClient";
import type { ItemPerformanceRow, RetentionReport, SalesRollupRow, ZReport } from "./types";

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

export async function getZReport(targetDate: string): Promise<ZReport> {
  return apiClient.get<ZReport>(`/api/v1/reports/z-report?target_date=${targetDate}`);
}

export async function getRetention(startDate: string, endDate: string): Promise<RetentionReport> {
  return apiClient.get<RetentionReport>(
    `/api/v1/reports/retention?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getLaborHours(targetDate: string): Promise<unknown> {
  return apiClient.get(`/api/v1/reports/labor-hours?target_date=${targetDate}`);
}

export async function getPrepTimeByItem(startDate: string, endDate: string): Promise<unknown> {
  return apiClient.get(`/api/v1/reports/prep-time-by-item?start_date=${startDate}&end_date=${endDate}`);
}

export async function getPrepTimeByStaff(startDate: string, endDate: string): Promise<unknown> {
  return apiClient.get(`/api/v1/reports/prep-time-by-staff?start_date=${startDate}&end_date=${endDate}`);
}
