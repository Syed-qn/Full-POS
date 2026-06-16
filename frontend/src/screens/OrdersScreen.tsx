import { useEffect, useMemo, useState } from "react";
import { CompactTable, type Column } from "../components/CompactTable";
import { StatusPill } from "../components/StatusPill";
import { fetchOrders } from "../lib/ordersApi";
import type { OrderOut } from "../lib/types";
import { OrderDetailDrawer } from "./OrderDetailDrawer";
import { PageHeader } from "../components/PageHeader";
import s from "./OrdersScreen.module.css";

const PAGE_SIZE = 20;

export function OrdersScreen() {
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    fetchOrders().then(setOrders);
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().replace(/^#/, "").toLowerCase();
    const base = [...orders].sort((a, b) => b.id - a.id); // newest first
    if (!q) return base;
    return base.filter(
      (o) =>
        String(o.id).includes(q) ||
        o.customer_name.toLowerCase().includes(q) ||
        o.customer_phone.includes(q),
    );
  }, [orders, search]);

  // Reset to the first page whenever the search changes.
  useEffect(() => { setPage(1); }, [search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

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
      <PageHeader title="Orders" subtitle="All delivery orders — live and past" />
      <div className={s.filterBar}>
        <input
          className={s.search}
          placeholder="Search #ID / name / phone"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className={s.tableCard}>
        <CompactTable<OrderOut>
          columns={columns}
          rows={pageRows}
          rowKey={(o) => o.id}
          onRowClick={(o) => setOpenId(o.id)}
          emptyText="No orders match these filters"
        />
      </div>
      {filtered.length > PAGE_SIZE && (
        <div className={s.pagination}>
          <span className={s.pageInfo}>
            {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length}
          </span>
          <div className={s.pageBtns}>
            <button className={s.pageBtn} disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}>
              ‹ Prev
            </button>
            <span className={s.pageNum}>Page {safePage} / {totalPages}</span>
            <button className={s.pageBtn} disabled={safePage >= totalPages} onClick={() => setPage(safePage + 1)}>
              Next ›
            </button>
          </div>
        </div>
      )}
      <OrderDetailDrawer orderId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}
