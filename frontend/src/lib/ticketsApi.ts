import { apiClient } from "./apiClient";
import type { ResolveTicketIn, Ticket, TicketStatus } from "./types";

export async function listTickets(status?: TicketStatus): Promise<Ticket[]> {
  const query = status ? `?status=${status}` : "";
  return apiClient.get<Ticket[]>(`/api/v1/tickets${query}`);
}

export async function getTicket(id: number): Promise<Ticket> {
  return apiClient.get<Ticket>(`/api/v1/tickets/${id}`);
}

export async function resolveTicket(id: number, body: ResolveTicketIn): Promise<Ticket> {
  return apiClient.post<Ticket>(`/api/v1/tickets/${id}/resolve`, body);
}
