import { apiClient } from "./apiClient";
import type { RiderLocationOut, RiderOut, RiderStatus } from "./types";

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

/** Manager side of the shared On/Off duty switch (same flag the rider toggles in-app). */
export async function setRiderDuty(id: number, on_duty: boolean): Promise<RiderOut> {
  return apiClient.patch<RiderOut>(`/api/v1/riders/${id}`, { on_duty });
}

export async function updateRider(id: number, data: Partial<RiderIn>): Promise<RiderOut> {
  return apiClient.patch<RiderOut>(`/api/v1/riders/${id}`, data);
}

export async function deleteRider(id: number): Promise<void> {
  await apiClient.delete(`/api/v1/riders/${id}`);
}

/** Latest location ping for one rider, or null if they've never shared one. */
export async function fetchRiderLocation(id: number): Promise<RiderLocationOut | null> {
  return apiClient.get<RiderLocationOut | null>(`/api/v1/riders/${id}/location`);
}

export interface AppInviteOut {
  success: boolean;
  code: string;
  expires_in_minutes: number;
}

/** Generate + WhatsApp the rider a one-time pairing code for the tracking app. */
export async function inviteRiderToApp(id: number): Promise<AppInviteOut> {
  return apiClient.post<AppInviteOut>(`/api/v1/riders/${id}/app-invite`, {});
}

/** The configured rider-app APK download link (null if not set up yet). */
export async function fetchRiderAppInfo(): Promise<{ apkUrl: string | null }> {
  return apiClient.get<{ apkUrl: string | null }>("/api/v1/rider-app/info");
}
