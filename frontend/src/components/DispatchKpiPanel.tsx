import { useEffect, useState } from "react";
import { fetchDispatchKpis } from "../lib/dispatchApi";
import type { DispatchKpisOut } from "../lib/types";
import { KPITile } from "./KPITile";
import s from "./DispatchKpiPanel.module.css";

export function DispatchKpiPanel({ kpis: kpisProp }: { kpis?: DispatchKpisOut }) {
  const [kpis, setKpis] = useState<DispatchKpisOut | null>(kpisProp ?? null);
  const [loading, setLoading] = useState(kpisProp == null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (kpisProp != null) {
      setKpis(kpisProp);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchDispatchKpis()
      .then((data) => {
        if (!cancelled) setKpis(data);
      })
      .catch(() => {
        if (!cancelled) setError("Dispatch KPIs unavailable");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [kpisProp]);

  if (loading) {
    return (
      <div className={s.panel} aria-busy="true" aria-label="Loading dispatch KPIs">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className={s.skTile} />
        ))}
      </div>
    );
  }

  if (error || !kpis) {
    return (
      <p className={s.error} role="status">
        {error ?? "Dispatch KPIs unavailable"}
      </p>
    );
  }

  const windowLabel = kpis.window ? ` · ${kpis.window}` : "";

  return (
    <div className={s.panel} aria-label={`Dispatch KPIs${windowLabel}`}>
      <KPITile
        label={`Batch rate${windowLabel}`}
        value={`${kpis.batch_rate_pct.toFixed(0)}%`}
        accent="var(--chart-2, #7c3aed)"
      />
      <KPITile
        label="Avg stops / trip"
        value={kpis.avg_stops.toFixed(1)}
        accent="var(--accent-primary)"
      />
      <KPITile
        label="Engine fallback"
        value={`${kpis.engine_fallback_pct.toFixed(0)}%`}
        accent={kpis.engine_fallback_pct > 15 ? "var(--sla-warn)" : "var(--sla-safe)"}
      />
    </div>
  );
}