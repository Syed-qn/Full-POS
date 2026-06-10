import { ApiError, apiClient } from "./apiClient";
import type { OrderOut } from "./types";

export interface AddressOut {
  apt_room: string;
  building: string;
  receiver_name: string;
  notes: string | null;
}

export interface CustomerLookupOut {
  name: string | null;
  last_address: AddressOut | null;
}

export interface ManualOrderItemIn {
  dish_id: number;
  qty: number;
  notes: string | null;
}

export interface ManualOrderAddressIn {
  apt_room: string;
  building: string;
  receiver_name: string;
  notes: string | null;
}

export interface ManualOrderIn {
  customer_phone: string;
  customer_name: string | null;
  items: ManualOrderItemIn[];
  address: ManualOrderAddressIn;
  delivery_fee_aed: string;
}

export async function lookupCustomer(
  phone: string,
): Promise<CustomerLookupOut | null> {
  try {
    return await apiClient.get<CustomerLookupOut>(
      `/api/v1/orders/manual/customer-lookup?phone=${encodeURIComponent(phone)}`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function createManualOrder(body: ManualOrderIn): Promise<OrderOut> {
  return apiClient.post<OrderOut>("/api/v1/orders/manual", body);
}
