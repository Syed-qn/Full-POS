import type { OrderOut } from "./types";

export interface OrderDeliveryKpis {
  orders: number;
  delivered: number;
  revenueAed: number;
  completionPct: number;
}

export function computeOrderDeliveryKpis(orders: OrderOut[]): OrderDeliveryKpis {
  const delivered = orders.filter((o) => o.status === "delivered").length;
  const cancelled = orders.filter((o) => o.status === "cancelled").length;
  const revenueAed = orders
    .filter((o) => o.status === "delivered")
    .reduce((sum, o) => sum + Number(o.total_aed), 0);
  const finished = delivered + cancelled;
  const completionPct =
    finished > 0 ? Math.round((delivered / finished) * 100) : 100;
  return {
    orders: orders.length,
    delivered,
    revenueAed,
    completionPct,
  };
}