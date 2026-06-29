import type { OrderStatus } from "./types";
import { STATUS_LABELS } from "../components/StatusPill";

/** Human status for dashboard rows — distinguishes resale parent vs sellable copy. */
export function orderStatusLabel(
  status: OrderStatus | string,
  opts?: { resaleOfOrderId?: number | null; orderNumber?: string },
): string {
  if (status === "on_resale") {
    if (opts?.resaleOfOrderId != null) return "Resale offer";
    if (opts?.orderNumber?.endsWith("-RS")) return "Resale offer";
    return "Cancelled (resale)";
  }
  return STATUS_LABELS[status] ?? String(status);
}

export function isResaleCopy(order: {
  resale_of_order_id?: number | null;
  order_number?: string;
}): boolean {
  return (
    order.resale_of_order_id != null || (order.order_number?.endsWith("-RS") ?? false)
  );
}