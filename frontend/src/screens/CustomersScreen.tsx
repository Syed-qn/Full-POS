import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CompactTable, type Column } from "../components/CompactTable";
import { listCustomers } from "../lib/customerApi";
import type { CustomerDetailOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import s from "./OrdersScreen.module.css";

const PAGE_SIZE = 20;

export function CustomersScreen() {
  const [customers, setCustomers] = useState<CustomerDetailOut[]>([]);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const navigate = useNavigate();

  useEffect(() => {
    listCustomers().then((r) => setCustomers(r.items));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return customers;
    return customers.filter(
      (c) =>
        (c.name ?? "").toLowerCase().includes(q) ||
        c.phone.includes(q),
    );
  }, [customers, search]);

  // Reset to the first page whenever the search changes.
  useEffect(() => { setPage(1); }, [search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const columns: Column<CustomerDetailOut>[] = [
    { key: "name", header: "Name", render: (c) => c.name ?? "—" },
    { key: "phone", header: "Phone", render: (c) => c.phone },
    { key: "orders", header: "Orders", render: (c) => String(c.total_orders) },
    { key: "spend", header: "Spend", render: (c) => `AED ${c.total_spend}` },
    { key: "opt", header: "Marketing", render: (c) => c.marketing_opted_in ? "Opted In" : "Opted Out" },
  ];

  return (
    <div className={s.screen}>
      <PageHeader title="Customers" subtitle="Your customer directory" />
      <div className={s.filterBar}>
        <input
          className={s.search}
          placeholder="Search name / phone"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className={s.tableCard}>
        <CompactTable<CustomerDetailOut>
          columns={columns}
          rows={pageRows}
          rowKey={(c) => c.id}
          onRowClick={(c) => navigate(`/customers/${c.id}`)}
          emptyText="No customers found"
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
    </div>
  );
}
