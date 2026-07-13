import { apiClient } from "./apiClient";
import type {
  ClockEventOut,
  Shift,
  ShiftCreateIn,
  StaffCreateIn,
  StaffHoursOut,
  StaffMember,
} from "./types";

export async function listStaff(): Promise<StaffMember[]> {
  return apiClient.get<StaffMember[]>("/api/v1/staff");
}

export async function createStaff(body: StaffCreateIn): Promise<StaffMember> {
  return apiClient.post<StaffMember>("/api/v1/staff", body);
}

export async function staffLogin(staffId: number, pin: string) {
  // Wrong PIN must not clear the current shell session (staff switch / login pad).
  return apiClient.post<{
    access_token: string;
    token_type: string;
    role: string;
    staff_id: number;
    name: string;
    training_mode: boolean;
  }>("/api/v1/staff/login", { staff_id: staffId, pin }, { skipAuthRedirect: true });
}

export async function clockStaff(
  staffId: number,
  type: "clock_in" | "clock_out" | "break_start" | "break_end",
): Promise<ClockEventOut> {
  return apiClient.post<ClockEventOut>(`/api/v1/staff/${staffId}/clock`, { type });
}

export async function getHours(staffId: number, targetDate: string): Promise<StaffHoursOut> {
  return apiClient.get<StaffHoursOut>(`/api/v1/staff/${staffId}/hours?target_date=${targetDate}`);
}

export async function getClockStatus(staffId: number): Promise<{ staff_id: number; status: string }> {
  return apiClient.get<{ staff_id: number; status: string }>(`/api/v1/staff/${staffId}/status`);
}

export async function getSales(staffId: number, targetDate: string): Promise<{ staff_id: number; date: string; sales_aed: string }> {
  return apiClient.get(`/api/v1/staff/${staffId}/sales?target_date=${targetDate}`);
}

export async function setTrainingMode(staffId: number, training_mode: boolean): Promise<StaffMember> {
  return apiClient.patch<StaffMember>(`/api/v1/staff/${staffId}/training-mode`, { training_mode });
}

export async function createShift(body: ShiftCreateIn): Promise<Shift> {
  return apiClient.post<Shift>("/api/v1/staff/shifts", body);
}

export async function listShifts(weekStart: string): Promise<Shift[]> {
  return apiClient.get<Shift[]>(`/api/v1/staff/shifts?week_start=${weekStart}`);
}

export async function openShift(shiftId: number): Promise<Shift> {
  return apiClient.post<Shift>(`/api/v1/staff/shifts/${shiftId}/open`, {});
}

export async function closeShift(shiftId: number): Promise<Shift> {
  return apiClient.post<Shift>(`/api/v1/staff/shifts/${shiftId}/close`, {});
}

export async function getTipPool(startDate: string, endDate: string): Promise<Record<string, string>> {
  return apiClient.get<Record<string, string>>(
    `/api/v1/staff/tip-pool?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function getTipsByStaff(startDate: string, endDate: string): Promise<Record<string, string>> {
  return apiClient.get<Record<string, string>>(
    `/api/v1/staff/tips-by-staff?start_date=${startDate}&end_date=${endDate}`,
  );
}

export async function attributeTip(orderId: number, staffId: number) {
  return apiClient.post<{ order_id: number; tip_staff_id: number }>("/api/v1/staff/attribute-tip", {
    order_id: orderId,
    staff_id: staffId,
  });
}

export async function submitManagerPin(body: {
  pin: string;
  action_type: string;
  order_id?: number;
  amount_aed?: string;
  reason?: string;
  requested_by_staff_id?: number;
}) {
  return apiClient.post<{
    id: number;
    action_type: string;
    status: string;
    amount_aed?: string | null;
  }>("/api/v1/staff/approvals", body);
}

export async function listApprovals(status?: string) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiClient.get<
    Array<{
      id: number;
      action_type: string;
      status: string;
      order_id?: number | null;
      amount_aed?: string | null;
      reason?: string | null;
      created_at?: string | null;
    }>
  >(`/api/v1/staff/approvals${qs}`);
}

export async function recordMistake(body: {
  staff_id: number;
  mistake_type: string;
  order_id?: number;
  amount_aed?: string;
  notes?: string;
}) {
  return apiClient.post("/api/v1/staff/mistakes", body);
}

export async function listMistakes(staffId?: number) {
  const qs = staffId != null ? `?staff_id=${staffId}` : "";
  return apiClient.get<
    Array<{
      id: number;
      staff_id: number;
      mistake_type: string;
      amount_aed: string;
      notes?: string | null;
    }>
  >(`/api/v1/staff/mistakes${qs}`);
}

export async function fetchAttendance(targetDate: string) {
  return apiClient.get<{
    date: string;
    rows: Array<{
      staff_id: number;
      name: string;
      scheduled_hours: number;
      worked_hours: number;
      variance_hours: number;
      attendance_status: string;
    }>;
  }>(`/api/v1/staff/attendance?target_date=${targetDate}`);
}

export async function fetchPerformance(startDate: string, endDate: string) {
  return apiClient.get<{
    rows: Array<{
      staff_id: number;
      name: string;
      role: string;
      hours: number;
      overtime_hours: number;
      order_count: number;
      sales_aed: string;
      tips_aed: string;
      mistake_count: number;
      mistake_cost_aed: string;
      sales_per_hour_aed: string;
    }>;
  }>(`/api/v1/staff/reports/performance?start_date=${startDate}&end_date=${endDate}`);
}

export async function fetchAlerts(unackedOnly = false) {
  return apiClient.get<
    Array<{
      id: number;
      alert_type: string;
      severity: string;
      staff_id?: number | null;
      detail: Record<string, unknown>;
      acknowledged: boolean;
    }>
  >(`/api/v1/staff/alerts?unacked_only=${unackedOnly}`);
}

export async function acknowledgeAlert(alertId: number) {
  return apiClient.post(`/api/v1/staff/alerts/${alertId}/acknowledge`, {});
}
