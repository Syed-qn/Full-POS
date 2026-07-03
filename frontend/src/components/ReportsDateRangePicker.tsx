import {
  boundsForPreset,
  REPORTS_DATE_PRESETS,
  type ReportsDatePreset,
} from "../lib/reportsDateRange";
import s from "./ReportsDateRangePicker.module.css";

const PRESET_LABELS: Record<ReportsDatePreset, string> = {
  today: "Today",
  "7d": "7 days",
  "30d": "30 days",
  all: "All time",
};

export function ReportsDateRangePicker({
  value,
  onChange,
}: {
  value: ReportsDatePreset;
  onChange: (preset: ReportsDatePreset) => void;
}) {
  const bounds = boundsForPreset(value);
  return (
    <div className={s.wrap}>
      <span className={s.label}>Period</span>
      <div className={s.pills} role="group" aria-label="Report date range">
        {REPORTS_DATE_PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            className={`${s.pill} ${value === preset ? s.pillActive : ""}`}
            aria-pressed={value === preset}
            onClick={() => onChange(preset)}
          >
            {PRESET_LABELS[preset]}
          </button>
        ))}
      </div>
      <span className={s.hint}>{bounds.label}</span>
    </div>
  );
}