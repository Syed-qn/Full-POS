import type { DispatchRejectionReason } from "./types";

const REJECTION_LABELS: Record<DispatchRejectionReason, string> = {
  sla_risk: "SLA risk — projected delivery over 40 min",
  proximity: "Too far from batch mate",
  max_per_batch: "Batch full (max 3 orders)",
  no_rider: "No rider available",
  no_geo: "Missing delivery coordinates",
  priority_solo: "Priority order — solo delivery",
  hold_matured_solo: "Hold window expired — riding solo",
};

export function formatRejectionReason(reason: string): string {
  return REJECTION_LABELS[reason as DispatchRejectionReason] ?? reason.replace(/_/g, " ");
}

export function formatEngineLabel(engine: string, fallback?: boolean): string {
  const base = engine === "ortools" ? "OR-Tools optimizer" : "Greedy (nearest rider)";
  return fallback ? `${base} · fallback` : base;
}

export function formatBatchReason(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return reason.replace(/_/g, " ");
}