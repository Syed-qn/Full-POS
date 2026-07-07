import { apiClient } from "./apiClient";

export interface CredentialsStatus {
  provider: string;
  configured: boolean;
}

export function getPaymentCredentials() {
  return apiClient.get<CredentialsStatus>("/api/v1/payments/credentials");
}

export function setPaymentCredentials(provider: string, secretKey: string) {
  return apiClient.put<CredentialsStatus>("/api/v1/payments/credentials", {
    provider, secret_key: secretKey,
  });
}

export function deletePaymentCredentials() {
  return apiClient.delete<void>("/api/v1/payments/credentials");
}
