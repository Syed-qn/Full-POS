import { apiClient } from "./apiClient";

export interface KdsTicketItem {
  id: number;
  order_id: number;
  dish_name: string;
  variant_name: string | null;
  qty: number;
  kitchen_status: string;
  notes: string | null;
  created_at: string;
}

export type TicketUrgency = "ok" | "warning" | "late";

const WARNING_AFTER_MINUTES = 8;
const LATE_AFTER_MINUTES = 15;

export function ticketUrgency(createdAt: string, now: Date = new Date()): TicketUrgency {
  const ageMinutes = (now.getTime() - new Date(createdAt).getTime()) / 60000;
  if (ageMinutes >= LATE_AFTER_MINUTES) return "late";
  if (ageMinutes >= WARNING_AFTER_MINUTES) return "warning";
  return "ok";
}

export function fetchStationTickets(stationId: number) {
  return apiClient.get<KdsTicketItem[]>(`/api/v1/kds/stations/${stationId}/tickets`);
}

export function bumpItem(itemId: number) {
  return apiClient.patch<KdsTicketItem>(`/api/v1/kds/items/${itemId}/bump`);
}
