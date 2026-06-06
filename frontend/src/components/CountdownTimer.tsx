import { useEffect, useState } from "react";
import { formatCountdown, remainingMs, slaTier, tierColorVar } from "../lib/sla";
import s from "./CountdownTimer.module.css";

export function CountdownTimer({ slaStartedAt }: { slaStartedAt: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const rem = remainingMs(slaStartedAt, now);
  const tier = slaTier(slaStartedAt, now);
  const urgent = rem > 0 && rem < 5 * 60_000;

  return (
    <span
      data-testid="countdown"
      className={`${s.timer} ${urgent ? s.urgent : ""} ${tier === "breach" ? s.breach : ""}`}
      style={{ color: tierColorVar(tier) }}
    >
      {formatCountdown(rem)}
    </span>
  );
}
