import type { OrderStatus } from "./types";
import { STATUS_LABELS } from "../components/StatusPill";

/** Human status for dashboard rows — distinguishes resale parent vs sellable copy. */
const ON_PREMISE_TYPES = new Set(["dine_in", "takeaway", "drive_thru"]);

export function orderStatusLabel(
  status: OrderStatus | string,
  opts?: {
    resaleOfOrderId?: number | null;
    orderNumber?: string;
    orderType?: string | null;
    cancellationReason?: string | null;
  },
): string {
  if (status === "on_resale") {
    if (opts?.resaleOfOrderId != null) return "Resale offer";
    if (opts?.orderNumber?.endsWith("-RS")) return "Resale offer";
    return "Cancelled (resale)";
  }
  // An order emptied by a table merge is cancelled internally but should read
  // as "Merged → <target order>", not "Cancelled" — it wasn't a real cancellation.
  if (status === "cancelled" && opts?.cancellationReason?.startsWith("Merged")) {
    const m = opts.cancellationReason.match(/Merged into order (.+)$/);
    return m ? `Merged → ${m[1]}` : "Merged";
  }
  // Dine-in/takeaway have no delivery leg: the tab is just Open, Paid, or Cancelled.
  if (opts?.orderType && ON_PREMISE_TYPES.has(opts.orderType)) {
    if (status === "delivered") return "Paid";
    if (status === "cancelled") return "Cancelled";
    if (
      ["draft", "pending_confirmation", "confirmed", "preparing", "ready"].includes(
        String(status),
      )
    ) {
      return "Open";
    }
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