import { apiClient } from "./apiClient";
import type { WalletBalance, WalletEntry } from "./types";

export async function getWallet(customerId: number): Promise<WalletBalance> {
  return apiClient.get<WalletBalance>(`/api/v1/wallet/${customerId}`);
}

export async function getWalletEntries(customerId: number): Promise<WalletEntry[]> {
  return apiClient.get<WalletEntry[]>(`/api/v1/wallet/${customerId}/entries`);
}

export async function creditWallet(
  customerId: number,
  amountAed: string,
  reason: string,
): Promise<WalletBalance> {
  return apiClient.post<WalletBalance>(`/api/v1/wallet/${customerId}/credit`, {
    amount_aed: amountAed,
    reason,
  });
}

export async function debitWallet(
  customerId: number,
  amountAed: string,
  reason: string,
): Promise<WalletBalance> {
  return apiClient.post<WalletBalance>(`/api/v1/wallet/${customerId}/debit`, {
    amount_aed: amountAed,
    reason,
  });
}
