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
  if (rem < 10 * 60_000) return "critical";
  if (rem < 15 * 60_000) return "warn";
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
