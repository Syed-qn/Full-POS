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

export async function clockStaff(
  staffId: number,
  type: "clock_in" | "clock_out" | "break_start" | "break_end",
): Promise<ClockEventOut> {
  return apiClient.post<ClockEventOut>(`/api/v1/staff/${staffId}/clock`, { type });
}

export async function getHours(staffId: number, targetDate: string): Promise<StaffHoursOut> {
  return apiClient.get<StaffHoursOut>(`/api/v1/staff/${staffId}/hours?target_date=${targetDate}`);
}

export async function getSales(staffId: number, targetDate: string): Promise<{ staff_id: number; date: string; sales_aed: string }> {
  return apiClient.get(`/api/v1/staff/${staffId}/sales?target_date=${targetDate}`);
}

export async function createShift(body: ShiftCreateIn): Promise<Shift> {
  return apiClient.post<Shift>("/api/v1/staff/shifts", body);
}

export async function listShifts(weekStart: string): Promise<Shift[]> {
  return apiClient.get<Shift[]>(`/api/v1/staff/shifts?week_start=${weekStart}`);
}

export async function getTipPool(startDate: string, endDate: string): Promise<Record<string, string>> {
  return apiClient.get<Record<string, string>>(
    `/api/v1/staff/tip-pool?start_date=${startDate}&end_date=${endDate}`,
  );
}
