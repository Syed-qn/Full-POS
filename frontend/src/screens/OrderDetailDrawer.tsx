import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { SideDrawer } from "../components/SideDrawer";
import { Spinner } from "../components/Spinner";
import { StatusPill } from "../components/StatusPill";
import { CountdownTimer } from "../components/CountdownTimer";
import { apiClient } from "../lib/apiClient";
import { fetchOrder } from "../lib/ordersApi";
import type { OrderOut } from "../lib/types";
import s from "./OrderDetailDrawer.module.css";

const KITCHEN_ADVANCEABLE = new Set(["confirmed", "preparing"]);

const ADVANCE_LABEL: Record<string, string> = {
  confirmed: "Start Preparing",
  preparing: "Mark as Ready",
};

export function OrderDetailDrawer({ orderId, onClose }: { orderId: number | null; onClose: () => void }) {
  const [order, setOrder] = useState<OrderOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [advancing, setAdvancing] = useState(false);

  useEffect(() => {
    if (orderId === null) {
      setOrder(null);
      return;
    }
    setLoading(true);
    fetchOrder(orderId)
      .then(setOrder)
      .finally(() => setLoading(false));
  }, [orderId]);

  async function advanceStatus() {
    if (!order) return;
    setAdvancing(true);
    try {
      const updated = await apiClient.post<OrderOut>(`/api/v1/orders/${order.id}/advance`);
      setOrder(updated);
    } finally {
      setAdvancing(false);
    }
  }

  return (
    <SideDrawer open={orderId !== null} title={order ? `Order ${order.order_number ?? `#${order.id}`}` : "Order"} onClose={onClose}>
      {loading || !order ? (
        <Spinner />
      ) : (
        <div className={s.detail}>
          <div className={s.head}>
            <StatusPill status={order.status} />
            <CountdownTimer slaStartedAt={order.sla_started_at} />
          </div>

          {KITCHEN_ADVANCEABLE.has(order.status) && (
            <div className={s.actionBar}>
              <Button onClick={advanceStatus} disabled={advancing}>
                {advancing ? "Saving…" : ADVANCE_LABEL[order.status]}
              </Button>
            </div>
          )}

          <Field label="Customer" value={`${order.customer_name ?? "—"} · ${order.customer_phone}`} />
          <Field label="Address" value={order.address ?? "—"} />
          <Field label="Rider" value={order.rider_name ?? "Unassigned"} />
          <div className={s.items}>
            <span className="label-upper">Items</span>
            {order.items.map((it, i) => (
              <div key={i} className={s.item}>
                <span>{it.qty}× {it.name}</span>
                <span className={s.price}>AED {it.price_aed}</span>
              </div>
            ))}
          </div>
          <Field label="Total" value={`AED ${order.total_aed}`} />
        </div>
      )}
    </SideDrawer>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.field}>
      <span className="label-upper">{label}</span>
      <span className={s.val}>{value}</span>
    </div>
  );
}
