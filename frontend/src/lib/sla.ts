export const SLA_WINDOW_MS = 40 * 60_000;

export type SlaTier = "safe" | "warn" | "critical" | "breach";

export function remainingMs(slaStartedAt: string | null, now: number = Date.now()): number {
  if (!slaStartedAt) return SLA_WINDOW_MS;
  const elapsed = now - Date.parse(slaStartedAt);
  return SLA_WINDOW_MS - elapsed;
}

export function slaTier(slaStartedAt: string | null, now: number = Date.now()): SlaTier {
  const rem = remainingMs(slaStartedAt, now);
  if (rem <= 0) return "breach";
  // Brief (dashboard-design-brief.md, SLA Board): red = last 5 min, yellow = 10–5 min remaining.
  if (rem < 5 * 60_000) return "critical";
  if (rem < 10 * 60_000) return "warn";
  return "safe";
}

export function tierColorVar(tier: SlaTier): string {
  switch (tier) {
    case "safe":
      return "var(--text-primary)";
    case "warn":
      return "var(--sla-warn)";
    case "critical":
      return "var(--sla-critical)";
    case "breach":
      return "var(--sla-breach)";
  }
}

export function formatCountdown(ms: number): string {
  const clamped = Math.max(0, ms);
  const totalSec = Math.floor(clamped / 1000);
  const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const ss = String(totalSec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/** Milliseconds remaining until an absolute deadline (negative once past it). */
export function remainingToDeadline(
  deadlineIso: string | null,
  now: number = Date.now()
): number | null {
  if (!deadlineIso) return null;
  return Date.parse(deadlineIso) - now;
}
