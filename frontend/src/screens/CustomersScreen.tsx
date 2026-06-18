import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CompactTable, type Column } from "../components/CompactTable";
import { listCustomers } from "../lib/customerApi";
import { usePollingRefresh } from "../lib/usePollingRefresh";
import type { CustomerDetailOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import s from "./OrdersScreen.module.css";

const PAGE_SIZE = 20;

type Marketing = "all" | "in" | "out";
type Activity = "all" | "has" | "repeat" | "none";

const MARKETING_TABS: { key: Marketing; label: string }[] = [
  { key: "all", label: "All" },
  { key: "in", label: "Opted In" },
  { key: "out", label: "Opted Out" },
];

const ACTIVITY_TABS: { key: Activity; label: string }[] = [
  { key: "all", label: "All" },
  { key: "has", label: "Has orders" },
  { key: "repeat", label: "Repeat (2+)" },
  { key: "none", label: "No orders" },
];

export function CustomersScreen() {
  const [customers, setCustomers] = useState<CustomerDetailOut[]>([]);
  const [search, setSearch] = useState("");
  const [marketing, setMarketing] = useState<Marketing>("all");
  const [activity, setActivity] = useState<Activity>("all");
  const [minSpend, setMinSpend] = useState("");
  const [page, setPage] = useState(1);
  const navigate = useNavigate();

  usePollingRefresh(() => {
    listCustomers().then((r) => setCustomers(r.items)).catch(() => {});
  });

  useEffect(() => {
    listCustomers().then((r) => setCustomers(r.items));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const min = parseFloat(minSpend);
    return customers.filter((c) => {
      if (q && !((c.name ?? "").toLowerCase().includes(q) || c.phone.includes(q))) return false;
      if (marketing === "in" && !c.marketing_opted_in) return false;
      if (marketing === "out" && c.marketing_opted_in) return false;
      if (activity === "none" && c.total_orders !== 0) return false;
      if (activity === "has" && c.total_orders < 1) return false;
      if (activity === "repeat" && c.total_orders < 2) return false;
      if (!Number.isNaN(min) && parseFloat(c.total_spend) < min) return false;
      return true;
    });
  }, [customers, search, marketing, activity, minSpend]);

  // Reset to the first page whenever any filter changes.
  useEffect(() => { setPage(1); }, [search, marketing, activity, minSpend]);

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
        <div className={s.filterGroup}>
          <span className={s.filterLabel}>Marketing</span>
          <div className={s.presets} role="group" aria-label="Marketing filter">
            {MARKETING_TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                className={`${s.chip} ${marketing === t.key ? s.chipActive : ""}`}
                aria-pressed={marketing === t.key}
                onClick={() => setMarketing(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <div className={s.filterGroup}>
          <span className={s.filterLabel}>Orders</span>
          <div className={s.presets} role="group" aria-label="Order activity filter">
            {ACTIVITY_TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                className={`${s.chip} ${activity === t.key ? s.chipActive : ""}`}
                aria-pressed={activity === t.key}
                onClick={() => setActivity(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <input
          className={s.minSpend}
          type="number"
          min="0"
          inputMode="decimal"
          aria-label="Minimum spend in AED"
          placeholder="Min spend (AED)"
          value={minSpend}
          onChange={(e) => setMinSpend(e.target.value)}
        />
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
