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
  // POS partner API key, returned ONCE right after connect auto-provisions it. Null on
  // every other read. Surface it immediately so the manager can hand it to the POS.
  api_key?: string | null;
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

export interface MetaEmbedConfig {
  enabled: boolean;
  app_id: string;
  config_id: string;
  graph_version: string;
}

export async function fetchMetaEmbedConfig(): Promise<MetaEmbedConfig> {
  return apiClient.get<MetaEmbedConfig>("/api/v1/onboarding/meta-embed-config");
}

/** Disconnect this restaurant's WhatsApp (Meta) account and re-open onboarding. */
export async function disconnectMeta(): Promise<MetaConfig> {
  return apiClient.post<MetaConfig>("/api/v1/onboarding/meta-disconnect", {});
}

export interface MetaConnectPayload {
  code: string;
  phone_number_id: string;
  waba_id: string;
  // Partner attribution from the onboarding link (?partner=<slug>). Omit/null =
  // standalone (no POS) — the store uses the platform end-to-end, no webhook/key.
  partner?: string | null;
}

/** Send the Embedded Signup popup result to the backend to exchange + store creds. */
export async function connectMetaEmbedded(payload: MetaConnectPayload): Promise<MetaConfig> {
  return apiClient.post<MetaConfig>("/api/v1/onboarding/meta-connect", payload);
}