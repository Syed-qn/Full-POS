import type { OrderStatus } from "../lib/types";
import s from "./StatusPill.module.css";

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  pending_confirmation: "Pending",
  confirmed: "Confirmed",
  preparing: "Preparing",
  ready: "Ready",
  assigned: "Assigned",
  picked_up: "Picked Up",
  arriving: "Arriving",
  delivered: "Delivered",
  cancelled: "Cancelled",
  undeliverable: "Undeliverable",
  on_resale: "On Resale",
  resold: "Resold",
  written_off: "Written Off",
};

const COLOR: Record<string, string> = {
  pending_confirmation: "var(--status-pending)",
  confirmed: "var(--status-confirmed)",
  preparing: "var(--status-preparing)",
  ready: "var(--status-ready)",
  assigned: "var(--status-assigned)",
  picked_up: "var(--status-pickedup)",
  arriving: "var(--status-pickedup)",
  delivered: "var(--status-delivered)",
  cancelled: "var(--status-cancelled)",
  undeliverable: "var(--status-cancelled)",
  on_resale: "var(--status-resale)",
  resold: "var(--status-resale)",
};

/** Dine-in / takeaway / drive-thru have no delivery leg, so the delivery-centric
 *  status words are wrong. Collapse them to what a floor cashier actually sees:
 *  the tab is "Open" while eating, "Paid" once settled, or "Cancelled". */
const ON_PREMISE_TYPES = new Set(["dine_in", "takeaway", "drive_thru"]);
function onPremiseLabel(status: string): string | null {
  if (status === "delivered") return "Paid";
  if (status === "cancelled") return "Cancelled";
  if (
    ["draft", "pending_confirmation", "confirmed", "preparing", "ready"].includes(status)
  ) {
    return "Open";
  }
  return null;
}

export function StatusPill({
  status,
  label: labelOverride,
  orderType,
}: {
  status: OrderStatus;
  label?: string;
  /** When on-premise (dine-in/takeaway), the pill reads Open/Paid instead of Confirmed/Delivered. */
  orderType?: string | null;
}) {
  const onPremise =
    orderType != null && ON_PREMISE_TYPES.has(orderType)
      ? onPremiseLabel(status)
      : null;
  const label = labelOverride ?? onPremise ?? STATUS_LABELS[status] ?? status;
  // A merge-emptied order is "cancelled" internally but reads as "Merged" — show
  // it neutral, not cancelled-red.
  const color = label.startsWith("Merged")
    ? "var(--text-muted)"
    : COLOR[status] ?? "var(--text-muted)";
  return (
    <span className={s.pill} style={{ ["--pill" as string]: color }}>
      {label}
    </span>
  );
}
