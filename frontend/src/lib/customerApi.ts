import { apiClient } from "./apiClient";
import type {
  AddressDetailOut,
  AddressPatchIn,
  CustomerDetailOut,
  CustomerListOut,
  CustomerPatchIn,
  CustomerProfileOut,
} from "./types";

export async function listCustomers(params?: {
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<CustomerListOut> {
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const query = qs.toString() ? `?${qs}` : "";
  return apiClient.get<CustomerListOut>(`/api/v1/ordering/customers${query}`);
}

export async function getCustomerProfile(customerId: number): Promise<CustomerProfileOut> {
  return apiClient.get<CustomerProfileOut>(`/api/v1/ordering/customers/${customerId}`);
}

export async function patchCustomerProfile(
  customerId: number,
  body: CustomerPatchIn,
): Promise<CustomerDetailOut> {
  return apiClient.patch<CustomerDetailOut>(
    `/api/v1/ordering/customers/${customerId}`,
    body,
  );
}

export async function patchCustomerAddress(
  customerId: number,
  addressId: number,
  body: AddressPatchIn,
): Promise<AddressDetailOut> {
  return apiClient.patch<AddressDetailOut>(
    `/api/v1/ordering/customers/${customerId}/addresses/${addressId}`,
    body,
  );
}

export async function deleteCustomerAddress(
  customerId: number,
  addressId: number,
): Promise<void> {
  await apiClient.delete(`/api/v1/ordering/customers/${customerId}/addresses/${addressId}`);
}

/**
 * Manager loyalty-tier override. Pass `{ tier }` (gold/silver/bronze or null) to
 * set + lock the tier, or `{ unlock: true }` to resume auto-recompute. Returns
 * the refreshed profile.
 */
export async function setCustomerLoyaltyTier(
  customerId: number,
  body: { tier: "gold" | "silver" | "bronze" | null } | { unlock: true },
): Promise<CustomerProfileOut> {
  return apiClient.post<CustomerProfileOut>(
    `/api/v1/ordering/customers/${customerId}/loyalty-tier`,
    body,
  );
}

export async function listHighValueCustomers(params?: {
  min_spend_aed?: number;
  min_orders?: number;
  limit?: number;
}): Promise<CustomerListOut> {
  const qs = new URLSearchParams();
  if (params?.min_spend_aed != null) qs.set("min_spend_aed", String(params.min_spend_aed));
  if (params?.min_orders != null) qs.set("min_orders", String(params.min_orders));
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const query = qs.toString() ? `?${qs}` : "";
  return apiClient.get<CustomerListOut>(`/api/v1/ordering/customers/high-value${query}`);
}

export async function redeemStampCard(customerId: number) {
  return apiClient.post<{
    stamps: number;
    stamps_required: number;
    rewards_redeemed: number;
    coupon_code: string | null;
  }>(`/api/v1/ordering/customers/${customerId}/stamp-card/redeem`);
}

export async function redeemLoyaltyPoints(customerId: number, points: number, reason?: string) {
  return apiClient.post<{ loyalty_points: number }>(
    `/api/v1/ordering/customers/${customerId}/loyalty-points/redeem`,
    { points, reason },
  );
}

export async function reorderLastOrder(customerId: number) {
  return apiClient.post<{
    id: number;
    order_number: string;
    status: string;
    source_order_id: number;
  }>(`/api/v1/ordering/customers/${customerId}/reorder-last`);
}

export async function createReferralCode(customerId: number) {
  return apiClient.post<{ code: string }>(`/api/v1/customers/${customerId}/referral-code`);
}
