import { apiClient } from "./apiClient";
import type { RestaurantOut } from "./types";

export interface OnboardingStatus {
  complete: boolean;
  has_location: boolean;
  has_menu: boolean;
  has_catalog_id: boolean;
  catalog_synced: boolean;
  has_meta: boolean;
}

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  return apiClient.get<OnboardingStatus>("/api/v1/onboarding/status");
}

export async function completeOnboarding(): Promise<RestaurantOut> {
  return apiClient.post<RestaurantOut>("/api/v1/onboarding/complete", {});
}

export interface MetaConfig {
  wa_phone_number_id: string;
  wa_business_account_id: string;
  wa_access_token_set: boolean;
  catalog_id: string;
  connected: boolean;
}

export interface MetaConfigPatch {
  wa_phone_number_id?: string;
  wa_business_account_id?: string;
  wa_access_token?: string;
  catalog_id?: string;
}

export async function fetchMetaConfig(): Promise<MetaConfig> {
  return apiClient.get<MetaConfig>("/api/v1/onboarding/meta-config");
}

export async function saveMetaConfig(patch: MetaConfigPatch): Promise<MetaConfig> {
  return apiClient.patch<MetaConfig>("/api/v1/onboarding/meta-config", patch);
}