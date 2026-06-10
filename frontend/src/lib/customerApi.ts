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
