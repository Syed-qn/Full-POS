import { apiClient } from "./apiClient";

export interface KdsTicketItem {
  id: number;
  order_id: number;
  dish_name: string;
  variant_name: string | null;
  qty: number;
  kitchen_status: string;
  notes: string | null;
}

export function fetchStationTickets(stationId: number) {
  return apiClient.get<KdsTicketItem[]>(`/api/v1/kds/stations/${stationId}/tickets`);
}

export function bumpItem(itemId: number) {
  return apiClient.patch<KdsTicketItem>(`/api/v1/kds/items/${itemId}/bump`);
}
