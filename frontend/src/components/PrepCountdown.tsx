import { useEffect, useState } from "react";
import { formatCountdown, remainingToDeadline } from "../lib/sla";
import s from "./CountdownTimer.module.css";

/**
 * Kitchen "plate by" countdown. The deadline is distance-driven (computed server-side
 * from the delivery drive leg), so plating later than this leaves too little of the
 * 40-min SLA to drive the order. Renders nothing when there's no deadline (no drop-off
 * pin). Goes urgent under 5 min and flips to "Plate now" once past.
 */
export function PrepCountdown({
  prepDeadline,
  label = "Plate",
  compact = false,
}: {
  prepDeadline: string | null;
  /** Verb shown in the badge — "Plate" (cooking) or "Start" (not started yet). */
  label?: string;
  /** Smaller type for inline use (e.g. an orders-table cell) vs the hero timer. */
  compact?: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const rem = remainingToDeadline(prepDeadline, now);
  if (rem === null) return null;

  const late = rem <= 0;
  const urgent = !late && rem < 5 * 60_000;

  return (
    <span
      data-testid="prep-countdown"
      className={`${s.timer} ${compact ? s.compact : ""} ${urgent ? s.urgent : ""} ${late ? s.breach : ""}`}
      title="Kitchen deadline (distance-driven)"
    >
      {late ? `${label} now` : `${label} in ${formatCountdown(rem)}`}
    </span>
  );
}
