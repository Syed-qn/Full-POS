import { apiClient } from "./apiClient";

export interface KdsTicketItem {
  id: number;
  order_id: number;
  order_number?: string | null;
  order_priority?: string | null;
  order_type?: string | null;
  dish_name: string;
  variant_name: string | null;
  qty: number;
  kitchen_status: string;
  notes: string | null;
  created_at: string;
  kitchen_received_at?: string | null;
  allergens?: string[];
  selected_modifiers?: Array<{ name?: string; price_delta_aed?: string } | string>;
  packaging_checked?: boolean;
  quality_checked?: boolean;
  missing_item_confirmed?: boolean;
  missing_item_note?: string | null;
  course_number?: number;
  course_held?: boolean;
  customer_allergy_notes?: string | null;
  estimated_ready_at?: string | null;
  age_seconds?: number;
  age_minutes?: number;
  urgency?: TicketUrgency;
  is_delayed?: boolean;
  station_id?: number | null;
  kitchen_code?: string | null;
  /** Real menu category ("Popcorn", "Paratha Spot") — shown on the board chip. */
  category?: string | null;
  /** Dine-in source: which table the waiter sent the ticket from. */
  table_id?: number | null;
  table_label?: string | null;
  /** Parcel line on a dine-in bill — the kitchen must box this one. */
  is_takeaway?: boolean;
  /** Bill already settled while the line is still on the pass: the guest has
   *  paid and is waiting at the counter. */
  order_settled?: boolean;
}

export interface KdsStation {
  id: number;
  name: string;
  station_type: string;
  kitchen_code: string;
  printer_ip: string | null;
  printer_port: number | null;
  fallback_station_id: number | null;
  is_active: boolean;
}

export interface ReadyPickupOrder {
  order_id: number;
  order_number: string;
  items: Array<{
    id: number;
    dish_name: string;
    variant_name: string | null;
    qty: number;
    kitchen_status: string;
    allergens?: string[];
    packaging_checked?: boolean;
    quality_checked?: boolean;
    missing_item_confirmed?: boolean;
  }>;
}

export interface KitchenPerformance {
  ticket_count: number;
  bumped_count: number;
  late_ticket_count: number;
  avg_prep_minutes: number | null;
  by_station: Array<{
    station_id: number | null;
    station_name: string;
    avg_prep_minutes: number;
    ticket_count: number;
  }>;
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

export function formatElapsed(ageSeconds: number): string {
  const m = Math.floor(ageSeconds / 60);
  const s = ageSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function fetchStations(kitchenCode?: string) {
  const q = kitchenCode ? `?kitchen_code=${encodeURIComponent(kitchenCode)}` : "";
  return apiClient.get<KdsStation[]>(`/api/v1/kds/stations${q}`);
}

export function seedDefaultStations(kitchenCode = "main") {
  return apiClient.post<KdsStation[]>(
    `/api/v1/kds/stations/seed-defaults?kitchen_code=${encodeURIComponent(kitchenCode)}`,
  );
}

export function fetchStationTickets(stationId: number, includeReady = false) {
  const q = includeReady ? "?include_ready=true" : "";
  return apiClient.get<KdsTicketItem[]>(`/api/v1/kds/stations/${stationId}/tickets${q}`);
}

export function bumpItem(itemId: number, staffId?: number) {
  return apiClient.patch<KdsTicketItem>(`/api/v1/kds/items/${itemId}/bump`, {
    staff_id: staffId ?? null,
  });
}

export function recallItem(itemId: number) {
  return apiClient.patch<KdsTicketItem>(`/api/v1/kds/items/${itemId}/recall`);
}

export function startPrep(itemId: number) {
  return apiClient.patch<KdsTicketItem>(`/api/v1/kds/items/${itemId}/start-prep`);
}

export function packagingCheck(itemId: number) {
  return apiClient.post<{ id: number; packaging_checked: boolean }>(
    `/api/v1/kds/items/${itemId}/packaging-check`,
  );
}

export function qualityCheck(itemId: number) {
  return apiClient.post<{ id: number; quality_checked: boolean }>(
    `/api/v1/kds/items/${itemId}/quality-check`,
  );
}

export function missingItemConfirm(itemId: number, note?: string) {
  return apiClient.post<{ id: number; missing_item_confirmed: boolean }>(
    `/api/v1/kds/items/${itemId}/missing-item`,
    { note: note ?? null },
  );
}

export function fetchReadyForPickup() {
  return apiClient.get<ReadyPickupOrder[]>(`/api/v1/kds/ready-for-pickup`);
}

export function fetchKitchenPerformance(startDate: string, endDate: string) {
  return apiClient.get<KitchenPerformance>(
    `/api/v1/kds/performance?start_date=${startDate}&end_date=${endDate}`,
  );
}

export function fetchPrinterStatus() {
  return apiClient.get<Array<{ station_id: number; healthy: boolean; last_heartbeat_at: string }>>(
    `/api/v1/kds/printer-status`,
  );
}
