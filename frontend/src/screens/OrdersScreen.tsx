import { useEffect, useMemo, useState } from "react";
import { CompactTable, type Column } from "../components/CompactTable";
import { StatusPill } from "../components/StatusPill";
import { fetchOrders } from "../lib/ordersApi";
import type { OrderOut } from "../lib/types";
import { OrderDetailDrawer } from "./OrderDetailDrawer";
import s from "./OrdersScreen.module.css";

export function OrdersScreen() {
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    fetchOrders().then(setOrders);
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().replace(/^#/, "").toLowerCase();
    if (!q) return orders;
    return orders.filter(
      (o) =>
        String(o.id).includes(q) ||
        o.customer_name.toLowerCase().includes(q) ||
        o.customer_phone.includes(q),
    );
  }, [orders, search]);

  const columns: Column<OrderOut>[] = [
    { key: "id", header: "#", render: (o) => <span className={s.mono}>#{o.id}</span> },
    { key: "cust", header: "Customer", render: (o) => o.customer_name },
    { key: "items", header: "Items", render: (o) => o.items.map((i) => `${i.qty}× ${i.name}`).join(", ") },
    { key: "total", header: "Total", render: (o) => <span className={s.mono}>AED {o.total_aed}</span> },
    { key: "rider", header: "Rider", render: (o) => o.rider_name ?? "—" },
    { key: "status", header: "Status", render: (o) => <StatusPill status={o.status} /> },
  ];

  return (
    <div className={s.screen}>
      <div className={s.filterBar}>
        <input
          className={s.search}
          placeholder="Search #ID / name / phone"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <CompactTable<OrderOut>
        columns={columns}
        rows={filtered}
        rowKey={(o) => o.id}
        onRowClick={(o) => setOpenId(o.id)}
        emptyText="No orders match these filters"
      />
      <OrderDetailDrawer orderId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}
