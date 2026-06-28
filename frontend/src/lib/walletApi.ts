import { apiClient } from "./apiClient";
import type { WalletBalance, WalletEntry } from "./types";

export async function getWallet(customerId: number): Promise<WalletBalance> {
  return apiClient.get<WalletBalance>(`/api/v1/wallet/${customerId}`);
}

export async function getWalletEntries(customerId: number): Promise<WalletEntry[]> {
  return apiClient.get<WalletEntry[]>(`/api/v1/wallet/${customerId}/entries`);
}
