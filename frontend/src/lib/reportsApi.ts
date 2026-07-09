import { apiClient, ApiError, TOKEN_KEY } from "./apiClient";
import type {
  DriverPerformanceRow,
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

export async function fetchExcelExport(startDate: string, endDate: string): Promise<Blob> {
  const token = localStorage.getItem(TOKEN_KEY);
  const path = `/api/v1/reports/export.xlsx?start_date=${startDate}&end_date=${endDate}`;
  const resp = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
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

export async function getRetentionCohort(startDate: string, endDate: string) {
  return apiClient.get<{
    new_customers: number;
    returning_customers: number;
    repeat_rate_pct: number;
    retention_rate_pct: number;
    cohorts: Array<{ cohort_week: string; new_customers: number }>;
  }>(`/api/v1/reports/retention-cohort?start_date=${startDate}&end_date=${endDate}`);
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

export async function getDriverPerformance(
  startDate: string,
  endDate: string,
): Promise<DriverPerformanceRow[]> {
  return apiClient.get<DriverPerformanceRow[]>(
    `/api/v1/reports/driver-performance?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getSalesByChannel(startDate: string, endDate: string) {
  return apiClient.get<Array<{ channel: string; order_count: number; revenue_aed: string; aov_aed: string }>>(
    `/api/v1/reports/sales-by-channel?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getSalesByCategory(startDate: string, endDate: string) {
  return apiClient.get<Array<{ category: string; qty: number; revenue_aed: string; order_count: number }>>(
    `/api/v1/reports/sales-by-category?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getSalesByWaiter(startDate: string, endDate: string) {
  return apiClient.get<Array<{ staff_id: number | null; staff_name: string; order_count: number; revenue_aed: string }>>(
    `/api/v1/reports/sales-by-waiter?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getSalesByPayment(startDate: string, endDate: string) {
  return apiClient.get<
    Array<{ tender_type: string; txn_count: number; gross_aed: string; refunded_aed: string; net_aed: string }>
  >(`/api/v1/reports/sales-by-payment-method?start_date=${startDate}&end_date=${endDate}`);
}

export async function getGrossProfit(startDate: string, endDate: string) {
  return apiClient.get<{
    gross_revenue_aed: string;
    food_cost_aed: string;
    gross_profit_aed: string;
    gross_margin_pct: number;
  }>(`/api/v1/reports/gross-profit?start_date=${startDate}&end_date=${endDate}`);
}

export async function getFoodCost(startDate: string, endDate: string) {
  return apiClient.get<{
    total_food_cost_aed: string;
    total_revenue_aed: string;
    food_cost_pct: number;
    rows: Array<{ dish_name: string; food_cost_aed: string; revenue_aed: string; food_cost_pct: number }>;
  }>(`/api/v1/reports/food-cost?start_date=${startDate}&end_date=${endDate}`);
}

export async function getDiscountReport(startDate: string, endDate: string) {
  return apiClient.get<{
    manager_discount_aed: string;
    staff_discount_aed: string;
    coupon_discount_aed: string;
    total_discounts_aed: string;
    discounted_order_count: number;
  }>(`/api/v1/reports/discounts?start_date=${startDate}&end_date=${endDate}`);
}

export async function getVoidReport(startDate: string, endDate: string) {
  return apiClient.get<{
    void_count: number;
    void_value_aed: string;
    rows: Array<{ order_number: string; total_aed: string; reason?: string | null }>;
  }>(`/api/v1/reports/voids?start_date=${startDate}&end_date=${endDate}`);
}

export async function getRefundReport(startDate: string, endDate: string) {
  return apiClient.get<{
    refund_txn_count: number;
    refunded_total_aed: string;
  }>(`/api/v1/reports/refunds?start_date=${startDate}&end_date=${endDate}`);
}

export async function getWastageReport(startDate: string, endDate: string) {
  return apiClient.get<{
    event_count: number;
    estimated_cost_aed: string;
    by_reason_type: Record<string, string>;
  }>(`/api/v1/reports/wastage?start_date=${startDate}&end_date=${endDate}`);
}

export async function getTopSelling(startDate: string, endDate: string, limit = 10) {
  return apiClient.get<Array<{ rank: number; dish_name: string; order_count: number; revenue_aed: string }>>(
    `/api/v1/reports/top-selling?start_date=${startDate}&end_date=${endDate}&limit=${limit}`,
  );
}

export async function getSlowMoving(startDate: string, endDate: string) {
  return apiClient.get<Array<{ dish_name: string; order_count: number; revenue_aed: string }>>(
    `/api/v1/reports/slow-moving?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getDeadMenuItems(startDate: string, endDate: string) {
  return apiClient.get<Array<{ dish_name: string; category?: string | null; price_aed: string }>>(
    `/api/v1/reports/dead-menu-items?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getAov(startDate: string, endDate: string) {
  return apiClient.get<{ order_count: number; revenue_aed: string; aov_aed: string }>(
    `/api/v1/reports/aov?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getAvgDeliveryTime(startDate: string, endDate: string) {
  return apiClient.get<{
    delivery_count: number;
    avg_delivery_minutes: number | null;
    late_count: number;
    late_pct: number;
  }>(`/api/v1/reports/avg-delivery-time?start_date=${startDate}&end_date=${endDate}`);
}

export async function getPeakHours(startDate: string, endDate: string) {
  return apiClient.get<{
    peak_bucket: string | null;
    peak_order_count: number;
    peak_revenue_aed: string;
    hours: Array<{ bucket: string; order_count: number; revenue_aed: string; is_peak: boolean }>;
  }>(`/api/v1/reports/peak-hours?start_date=${startDate}&end_date=${endDate}`);
}

export async function getTaxReport(startDate: string, endDate: string) {
  return apiClient.get<{
    order_count: number;
    taxable_net_aed: string;
    vat_total_aed: string;
    gross_incl_vat_aed: string;
  }>(`/api/v1/reports/tax?start_date=${startDate}&end_date=${endDate}`);
}

export async function getForecastedSales(horizon = "tomorrow") {
  return apiClient.get<{
    horizon: string;
    predicted_order_count: number;
    trailing_aov_aed: string;
    forecasted_sales_aed: string;
  }>(`/api/v1/reports/forecasted-sales?horizon=${encodeURIComponent(horizon)}`);
}

export async function getTableTurnTime(startDate: string, endDate: string) {
  return apiClient.get<Array<{ table_id: number; turn_minutes: number }>>(
    `/api/v1/reports/table-turn-time?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function sendOwnerWhatsappReport(targetDate?: string) {
  const qs = targetDate ? `?target_date=${targetDate}` : "";
  return apiClient.post<{ status: string; preview: string; to_phone: string }>(
    `/api/v1/reports/owner-whatsapp-report${qs}`,
    {},
  );
}

export async function getOwnerDailySummary(targetDate: string) {
  return apiClient.get<{ text: string; aov_aed: string }>(
    `/api/v1/reports/owner-daily-summary?target_date=${targetDate}`,
  );
}
