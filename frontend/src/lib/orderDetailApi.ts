import { apiClient } from "./apiClient";
import type {
  AddressDetailOut,
  AddressPatchIn,
  CustomerDetailOut,
  CustomerPatchIn,
  OrderDetailOut,
  OrderOut,
} from "./types";

export async function fetchOrderDetail(
  orderId: number,
  opts?: { include?: string },
): Promise<OrderDetailOut> {
  const qs = opts?.include ? `?include=${encodeURIComponent(opts.include)}` : "";
  return apiClient.get<OrderDetailOut>(`/api/v1/orders/${orderId}/detail${qs}`);
}

/** Tab-specific include sets — overview first for ≤400ms open on Render. */
export const DETAIL_INCLUDE_BY_TAB = {
  overview: "overview",
  timeline: "overview,timeline,dispatch,route",
  chat: "overview,chat",
  customer: "overview",
} as const;

/** Merge progressive tab fetches — keep sections omitted from the latest include. */
export function mergeOrderDetail(
  prev: OrderDetailOut | null,
  next: OrderDetailOut,
  include: string,
): OrderDetailOut {
  if (!prev) return next;
  const sections = new Set(include.split(",").map((s) => s.trim()));
  return {
    ...next,
    timeline: sections.has("timeline") ? next.timeline : prev.timeline,
    chat: sections.has("chat") ? next.chat : prev.chat,
    route: sections.has("route") ? next.route : prev.route,
    dispatch_explain: sections.has("dispatch") ? next.dispatch_explain : prev.dispatch_explain,
    convo_summary: sections.has("chat") ? next.convo_summary : prev.convo_summary,
  };
}

/** Map the rich detail payload to the slim OrderOut shape used by list actions. */
export function orderOutFromDetail(d: OrderDetailOut): OrderOut {
  const addr = d.address;
  const addressStr = addr
    ? [addr.room_apartment, addr.building].filter(Boolean).join(", ") || null
    : null;
  return {
    id: d.id,
    order_number: d.order_number,
    status: d.status,
    customer_name: d.customer.name ?? "",
    customer_phone: d.customer.phone,
    items: d.items.map((i) => ({
      dish_number: i.dish_number,
      name: i.dish_name,
      qty: i.qty,
      price_aed: i.price_aed,
    })),
    total_aed: d.total,
    rider_id: d.rider?.id ?? null,
    rider_name: d.rider?.name ?? null,
    sla_started_at: d.sla_started_at ?? null,
    prep_deadline: d.prep_deadline,
    cook_estimate_minutes: d.cook_estimate_minutes,
    created_at: d.created_at,
    address: addressStr,
    lat: addr?.latitude ?? null,
    lng: addr?.longitude ?? null,
    batch_preview: d.batch_preview_label ?? null,
  };
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