import type { DiffOut } from "../lib/types";
import s from "./DiffPanel.module.css";

export function DiffPanel({ diff }: { diff: DiffOut }) {
  return (
    <div className={s.panel}>
      <div className={s.counts}>
        <span style={{ color: "var(--sla-warn)" }}>Changed: {diff.price_changes.length}</span>
        <span style={{ color: "var(--sla-safe)" }}>New: {diff.added.length}</span>
        <span style={{ color: "var(--sla-critical)" }}>Removed: {diff.removed.length}</span>
        <span style={{ color: "var(--sla-warn)" }}>Errors: {diff.conflicts.length}</span>
      </div>

      {diff.price_changes.map((c, i) => (
        <div key={`p${i}`} className={s.row}>
          <span className={s.num}>#{String(c.dish_number)}</span>
          <span>{String(c.name)}</span>
          <span className={s.old}>AED {String(c.old_price)}</span>
          <span className={s.arrow}>→</span>
          <span className={s.new}>AED {String(c.new_price)}</span>
        </div>
      ))}

      {diff.conflicts.map((c, i) => (
        <div key={`c${i}`} className={`${s.row} ${s.conflict}`}>
          <span className={s.num}>#{String(c.dish_number ?? "??")}</span>
          <span>{String(c.name)}</span>
          <span className={s.reason}>{String(c.reason ?? "extraction error")}</span>
        </div>
      ))}
    </div>
  );
}
