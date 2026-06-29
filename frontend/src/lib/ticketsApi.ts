import { apiClient } from "./apiClient";
import type { ResolveTicketIn, Ticket, TicketStatus } from "./types";

export async function listTickets(
  status?: TicketStatus,
  phone?: string,
): Promise<Ticket[]> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (phone) params.set("phone", phone);
  const qs = params.toString();
  return apiClient.get<Ticket[]>(`/api/v1/tickets${qs ? `?${qs}` : ""}`);
}

export async function getTicket(id: number): Promise<Ticket> {
  return apiClient.get<Ticket>(`/api/v1/tickets/${id}`);
}

export async function resolveTicket(id: number, body: ResolveTicketIn): Promise<Ticket> {
  return apiClient.post<Ticket>(`/api/v1/tickets/${id}/resolve`, body);
}
