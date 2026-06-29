import { apiClient } from "./apiClient";
import type { RestaurantOut } from "./types";

export interface OnboardingStatus {
  complete: boolean;
  has_location: boolean;
  has_menu: boolean;
  has_catalog_id: boolean;
  catalog_synced: boolean;
}

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  return apiClient.get<OnboardingStatus>("/api/v1/onboarding/status");
}

export async function completeOnboarding(): Promise<RestaurantOut> {
  return apiClient.post<RestaurantOut>("/api/v1/onboarding/complete", {});
}