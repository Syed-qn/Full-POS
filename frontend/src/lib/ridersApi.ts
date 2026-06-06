import { apiClient } from "./apiClient";
import type { RiderOut, RiderStatus } from "./types";

export async function fetchRiders(): Promise<RiderOut[]> {
  return apiClient.get<RiderOut[]>("/api/v1/riders");
}

export async function setRiderStatus(id: number, status: RiderStatus): Promise<RiderOut> {
  return apiClient.patch<RiderOut>(`/api/v1/riders/${id}`, { status });
}
