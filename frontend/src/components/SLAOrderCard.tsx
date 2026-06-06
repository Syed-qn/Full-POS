import { CountdownTimer } from "./CountdownTimer";
import { StatusPill } from "./StatusPill";
import { slaTier } from "../lib/sla";
import type { OrderOut } from "../lib/types";
import s from "./SLAOrderCard.module.css";

export function SLAOrderCard({ order, onClick }: { order: OrderOut; onClick?: () => void }) {
  const tier = slaTier(order.sla_started_at);
  const itemsSummary = order.items
    .map((i) => `${i.qty}× ${i.name}`)
    .join(", ");
  return (
    <div
      data-testid="sla-card"
      className={`${s.card} ${s[tier]}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
    >
      <div className={s.top}>
        <span className={s.id}>#{order.id}</span>
        <CountdownTimer slaStartedAt={order.sla_started_at} />
      </div>
      <div className={s.cust}>{order.customer_name}</div>
      <div className={s.items}>{itemsSummary}</div>
      <div className={s.foot}>
        <StatusPill status={order.status} />
        {order.rider_name && <span className={s.rider}>{order.rider_name}</span>}
      </div>
    </div>
  );
}
