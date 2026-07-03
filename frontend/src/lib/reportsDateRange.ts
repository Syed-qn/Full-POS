export type ReportsDatePreset = "today" | "7d" | "30d" | "all";

export interface DateRangeBounds {
  fromDate?: string;
  toDate?: string;
  label: string;
}

function toYMD(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDaysUTC(d: Date, days: number): Date {
  const next = new Date(d);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

const PRESET_LABELS: Record<ReportsDatePreset, string> = {
  today: "Today",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  all: "All time",
};

export const REPORTS_DATE_PRESETS: ReportsDatePreset[] = [
  "today",
  "7d",
  "30d",
  "all",
];

export function boundsForPreset(
  preset: ReportsDatePreset,
  now = new Date(),
): DateRangeBounds {
  const label = PRESET_LABELS[preset];
  if (preset === "all") {
    return { fromDate: undefined, toDate: undefined, label };
  }
  const toDate = toYMD(now);
  if (preset === "today") {
    return { fromDate: toDate, toDate, label };
  }
  const span = preset === "7d" ? 6 : 29;
  return { fromDate: toYMD(addDaysUTC(now, -span)), toDate, label };
}