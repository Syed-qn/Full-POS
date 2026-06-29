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

export function StatusPill({
  status,
  label: labelOverride,
}: {
  status: OrderStatus;
  label?: string;
}) {
  const label = labelOverride ?? STATUS_LABELS[status] ?? status;
  const color = COLOR[status] ?? "var(--text-muted)";
  return (
    <span className={s.pill} style={{ ["--pill" as string]: color }}>
      {label}
    </span>
  );
}
