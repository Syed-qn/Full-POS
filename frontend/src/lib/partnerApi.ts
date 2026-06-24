import { apiClient } from "./apiClient";

export interface ApiKey {
  id: number;
  label: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

// Returned only at creation — carries the full secret, shown to the manager once.
export interface ApiKeyCreated extends ApiKey {
  api_key: string;
}

/** List this restaurant's partner API keys (active + revoked), newest first. */
export function listApiKeys(): Promise<ApiKey[]> {
  return apiClient.get<ApiKey[]>("/api/v1/api-keys");
}

/** Mint a new key. The `api_key` in the response is shown once and never again. */
export function createApiKey(label: string): Promise<ApiKeyCreated> {
  return apiClient.post<ApiKeyCreated>("/api/v1/api-keys", { label });
}

/** Revoke (soft-delete) a key so it can no longer authenticate. */
export function revokeApiKey(id: number): Promise<void> {
  return apiClient.delete<void>(`/api/v1/api-keys/${id}`);
}
