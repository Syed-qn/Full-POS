import {
  formatBatchReason,
  formatEngineLabel,
  formatRejectionReason,
} from "../lib/dispatchDisplay";
import type { DispatchExplainOut, DispatchPerStopOut } from "../lib/types";
import s from "./DispatchExplainSection.module.css";

export function DispatchExplainSection({
  explain,
  batchPreviewLabel,
  orderId,
}: {
  explain: DispatchExplainOut;
  batchPreviewLabel?: string | null;
  orderId: number;
}) {
  const perStop: DispatchPerStopOut[] =
    explain.per_stop ??
    (explain.projected_min
      ? Object.entries(explain.projected_min).map(([oid, projected_min]) => ({
          order_id: Number(oid),
          projected_min,
        }))
      : []);

  const thisStop = perStop.find((p) => p.order_id === orderId);
  const totalEst =
    explain.total_est_min ??
    (perStop.length > 0
      ? Math.max(...perStop.map((p) => p.projected_min))
      : thisStop?.projected_min);

  const rejections = explain.rejections ?? [];
  const batchReason = formatBatchReason(explain.batch_reason);

  return (
    <section className={s.section} aria-label="Dispatch explainability">
      <h4 className={s.title}>Dispatch</h4>

      <div className={s.metaGrid}>
        <Meta label="Engine" value={formatEngineLabel(explain.engine, explain.engine_fallback)} />
        {totalEst != null && (
          <Meta label="Trip est." value={`${totalEst.toFixed(1)} min`} />
        )}
        {batchPreviewLabel && <Meta label="Preview batch" value={batchPreviewLabel} />}
        {explain.zone && <Meta label="Zone" value={explain.zone} />}
        {batchReason && <Meta label="Batch reason" value={batchReason} />}
      </div>

      {explain.route_sequence && explain.route_sequence.length > 0 && (
        <p className={s.sequence}>
          Stop order:{" "}
          {explain.route_sequence.map((id, i) => (
            <span key={id} className={id === orderId ? s.sequenceHighlight : undefined}>
              {i > 0 ? " → " : ""}
              #{id}
            </span>
          ))}
        </p>
      )}

      {perStop.length > 0 && (
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>Stop</th>
                <th>Projected</th>
                <th>Route</th>
                <th>Buffer</th>
              </tr>
            </thead>
            <tbody>
              {perStop.map((stop) => (
                <tr
                  key={stop.order_id}
                  className={stop.order_id === orderId ? s.rowCurrent : undefined}
                >
                  <td>#{stop.order_id}</td>
                  <td>{stop.projected_min.toFixed(1)} min</td>
                  <td>
                    {stop.route_min != null ? `${stop.route_min.toFixed(1)} min` : "—"}
                  </td>
                  <td>
                    {stop.buffer_min != null ? `${stop.buffer_min} min` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rejections.length > 0 && (
        <div className={s.rejections}>
          <span className={s.rejectTitle}>Not batched with</span>
          <ul className={s.rejectList}>
            {rejections.map((r) => (
              <li key={`${r.order_id}-${r.reason}`}>
                <span className={s.rejectOrder}>#{r.order_id}</span>
                <span className={s.rejectReason}>{formatRejectionReason(r.reason)}</span>
                {r.projected_min != null && (
                  <span className={s.rejectEta}>{r.projected_min.toFixed(1)} min projected</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.meta}>
      <span className={s.metaLabel}>{label}</span>
      <span className={s.metaValue}>{value}</span>
    </div>
  );
}