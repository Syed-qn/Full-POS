import { apiClient } from "./apiClient";
import type { RiderOut, RiderStatus } from "./types";

export interface RiderIn {
  name: string;
  phone: string;
}

export async function fetchRiders(): Promise<RiderOut[]> {
  return apiClient.get<RiderOut[]>("/api/v1/riders");
}

export async function addRider(data: RiderIn): Promise<RiderOut> {
  return apiClient.post<RiderOut>("/api/v1/riders", data);
}

export async function setRiderStatus(id: number, status: RiderStatus): Promise<RiderOut> {
  return apiClient.patch<RiderOut>(`/api/v1/riders/${id}`, { status });
}

export async function deleteRider(id: number): Promise<void> {
  await apiClient.delete(`/api/v1/riders/${id}`);
}
