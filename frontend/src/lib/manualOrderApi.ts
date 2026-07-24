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
  /** true parks the line: the KDS skips held items until /fire-course. */
  course_held?: boolean;
}

export interface ManualOrderAddressIn {
  apt_room: string;
  building: string;
  receiver_name: string;
  notes: string | null;
  // Exact pin from the map picker; omitted → backend geocodes the building text.
  latitude?: number | null;
  longitude?: number | null;
}

export interface ManualOrderIn {
  customer_phone: string;
  customer_name: string | null;
  items: ManualOrderItemIn[];
  address: ManualOrderAddressIn;
  delivery_fee_aed: string;
  /** Fulfillment type — defaults to "delivery" server-side. */
  order_type?: string;
  /** Cashier "KOT": fire the order to the kitchen atomically on create. Delivery
   *  orders are KOT-gated, so without this a Home Delivery would be created
   *  "confirmed" with no kitchen ticket. The server advances it to "preparing"
   *  in the same request, so a failed follow-up call can never strand it. */
  fire_to_kitchen?: boolean;
}

/** Unified POS create — used for order types that don't require a delivery address. */
export interface PosOrderIn {
  order_type: string;
  customer_phone: string;
  customer_name: string | null;
  items: ManualOrderItemIn[];
  table_id?: number | null;
  covers?: number | null;
  /** Waiter/cashier the sale is attributed to — drives per-staff sales + the
   *  floor plan's "waiter" column. */
  staff_id?: number | null;
  address?: ManualOrderAddressIn | null;
  delivery_fee_aed?: string;
  /** false parks the order as a DRAFT the kitchen cannot see yet — the waiter's
   *  "Save to Table". Fire it later with confirmOrder(). Defaults true. */
  auto_confirm?: boolean;
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

/** Unified POS create (dine-in / takeaway / drive-thru). Address optional. */
export async function createPosOrder(body: PosOrderIn): Promise<OrderOut> {
  return apiClient.post<OrderOut>("/api/v1/orders/pos", body);
}

/** Preview the next daily queue token (today, Asia/Dubai) for the token bar. */
export async function fetchNextToken(): Promise<number> {
  const r = await apiClient.get<{ next_token: number }>("/api/v1/orders/next-token");
  return r.next_token;
}

/** Fire a parked (draft) order to the kitchen — the waiter's KOT button.
 *  Idempotent: confirming an already-confirmed order is a no-op. */
export async function confirmOrder(orderId: number): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${orderId}/confirm`);
}

/** Release held (course_held) lines of a course to the kitchen. */
export async function fireCourse(orderId: number, courseNumber = 1): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${orderId}/fire-course`, {
    course_number: courseNumber,
  });
}

/** Update the dine-in party size on an open tab (guests joined / left). */
export async function setOrderCovers(orderId: number, covers: number): Promise<OrderOut> {
  return apiClient.patch<OrderOut>(`/api/v1/orders/${orderId}/covers`, { covers });
}

/** Flag a table's state — used for "request bill" (needs_bill). */
export async function setTableStatus(tableId: number, status: string): Promise<unknown> {
  return apiClient.patch(`/api/v1/tables/${tableId}/status`, { status });
}

/** Append another round of items to an already-open order (dine-in tab). */
export async function addOrderItems(
  orderId: number,
  items: ManualOrderItemIn[],
): Promise<OrderOut> {
  return apiClient.post<OrderOut>(`/api/v1/orders/${orderId}/items`, { items });
}
