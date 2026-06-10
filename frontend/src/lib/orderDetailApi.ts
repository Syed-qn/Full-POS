import { apiClient } from "./apiClient";
import type {
  AddressDetailOut,
  AddressPatchIn,
  CustomerDetailOut,
  CustomerPatchIn,
  OrderDetailOut,
} from "./types";

export async function fetchOrderDetail(orderId: number): Promise<OrderDetailOut> {
  return apiClient.get<OrderDetailOut>(`/api/v1/orders/${orderId}/detail`);
}

export async function patchCustomer(
  customerId: number,
  body: CustomerPatchIn,
): Promise<CustomerDetailOut> {
  return apiClient.patch<CustomerDetailOut>(
    `/api/v1/ordering/customers/${customerId}`,
    body,
  );
}

export async function patchAddress(
  customerId: number,
  addressId: number,
  body: AddressPatchIn,
): Promise<AddressDetailOut> {
  return apiClient.patch<AddressDetailOut>(
    `/api/v1/ordering/customers/${customerId}/addresses/${addressId}`,
    body,
  );
}
