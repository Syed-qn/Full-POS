import { CountdownTimer } from "./CountdownTimer";
import { StatusPill } from "./StatusPill";
import { slaTier } from "../lib/sla";
import type { OrderOut } from "../lib/types";
import s from "./SLAOrderCard.module.css";

export function SLAOrderCard({
  order,
  onClick,
  onDismiss,
}: {
  order: OrderOut;
  onClick?: () => void;
  onDismiss?: () => void;
}) {
  const tier = slaTier(order.sla_started_at);
  const itemsSummary = order.items
    .map((i) => `${i.qty}× ${i.name}`)
    .join(", ");
  return (
    <div
      data-testid="sla-card"
      className={`${s.card} ${s[tier]}`}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick?.();
        }
      }}
      role="button"
      tabIndex={0}
    >
      <span className={s.id}>#{order.id}</span>

      <div className={s.who}>
        <span className={s.cust}>{order.customer_name}</span>
        <span className={s.items}>{itemsSummary}</span>
      </div>

      {order.rider_name && <span className={s.rider}>{order.rider_name}</span>}
      <StatusPill status={order.status} />

      {/* A breached order's clock is frozen at 00:00 — show a clear "Overdue"
          chip instead of the meaningless countdown. */}
      {tier === "breach" ? (
        <span className={`${s.timerChip} ${s.chipBreach}`}>⏱ Overdue</span>
      ) : (
        <span className={`${s.timerChip} ${tier === "critical" ? s.chipCritical : s.chipWarn}`}>
          <CountdownTimer slaStartedAt={order.sla_started_at} />
        </span>
      )}

      {onDismiss && (
        <button
          type="button"
          className={s.dismiss}
          aria-label={`Dismiss alert for order #${order.id}`}
          // Stop the click from bubbling to the card (which would navigate).
          onClick={(e) => {
            e.stopPropagation();
            onDismiss();
          }}
          onKeyDown={(e) => e.stopPropagation()}
        >
          ✕
        </button>
      )}
    </div>
  );
}
