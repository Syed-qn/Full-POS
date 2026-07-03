import s from "./KPITile.module.css";

export function KPITile({
  label,
  value,
  delta,
  accent,
}: {
  label: string;
  value: string;
  delta?: number;
  accent?: string;
}) {
  return (
    <div className={s.tile}>
      <span className="label-upper">{label}</span>
      <span className={s.value} style={accent ? { color: accent } : undefined}>{value}</span>
      {delta !== undefined && delta !== 0 && (
        <span
          className={s.delta}
          style={{ color: delta > 0 ? "var(--sla-safe)" : "var(--sla-critical)" }}
        >
          {delta > 0 ? "↑" : "↓"} {Math.abs(delta)}%
        </span>
      )}
    </div>
  );
}
