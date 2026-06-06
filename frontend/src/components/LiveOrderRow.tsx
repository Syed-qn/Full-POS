import { CountdownTimer } from "./CountdownTimer";
import { StatusPill } from "./StatusPill";
import type { OrderOut } from "../lib/types";
import s from "./LiveOrderRow.module.css";

export function LiveOrderRow({
  order,
  onOpen,
  isNew = false,
}: {
  order: OrderOut;
  onOpen: (id: number) => void;
  isNew?: boolean;
}) {
  const items = order.items.map((i) => `${i.qty}× ${i.name}`).join(", ");
  return (
    <div
      className={`${s.row} ${isNew ? s.new : ""}`}
      onClick={() => onOpen(order.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(order.id);
        }
      }}
      role="button"
      tabIndex={0}
    >
      <span className={s.id}>#{order.id}</span>
      <span className={s.cust}>{order.customer_name}</span>
      <span className={s.items}>{items}</span>
      <StatusPill status={order.status} />
      <span className={s.rider}>{order.rider_name ?? "—"}</span>
      <span className={s.timer}>
        <CountdownTimer slaStartedAt={order.sla_started_at} />
      </span>
    </div>
  );
}
