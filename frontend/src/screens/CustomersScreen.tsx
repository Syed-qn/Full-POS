import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CompactTable, type Column } from "../components/CompactTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { QueryRefreshNote } from "../components/QueryRefreshNote";
import { perfMark, perfNow } from "../lib/perf";
import { useCustomersQuery } from "../lib/queries/dashboard";
import type { CustomerDetailOut } from "../lib/types";
import s from "./OrdersScreen.module.css";
import f from "./CustomersScreen.module.css";

const PAGE_SIZE = 20;

/** Avatar initials: first two letters of name, else last 2 phone digits. */
function initials(name?: string | null, phone?: string): string {
  const n = (name ?? "").trim();
  if (n) {
    const parts = n.split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  const digits = (phone ?? "").replace(/\D/g, "");
  return digits.slice(-2) || "•";
}

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
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [marketing, setMarketing] = useState<Marketing>("all");
  const [activity, setActivity] = useState<Activity>("all");
  const [minSpend, setMinSpend] = useState("");
  const [page, setPage] = useState(1);
  const navigate = useNavigate();

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, marketing, activity, minSpend]);

  const { data, isLoading, isFetching, isError } = useCustomersQuery(page, debouncedSearch);
  const customers = data?.items ?? [];
  const loading = isLoading && customers.length === 0;
  const paintMark = useRef<number | null>(null);

  useEffect(() => {
    paintMark.current = perfNow();
  }, [page, debouncedSearch]);

  useEffect(() => {
    if (!loading && customers.length > 0 && paintMark.current != null) {
      perfMark("customers-first-paint", paintMark.current);
      paintMark.current = null;
    }
  }, [loading, customers.length]);

  const filtered = useMemo(() => {
    const min = parseFloat(minSpend);
    return customers.filter((c) => {
      if (marketing === "in" && !c.marketing_opted_in) return false;
      if (marketing === "out" && c.marketing_opted_in) return false;
      if (activity === "none" && c.total_orders !== 0) return false;
      if (activity === "has" && c.total_orders < 1) return false;
      if (activity === "repeat" && c.total_orders < 2) return false;
      if (!Number.isNaN(min) && parseFloat(c.total_spend) < min) return false;
      return true;
    });
  }, [customers, marketing, activity, minSpend]);

  const hasNextPage = customers.length === PAGE_SIZE;
  const showPagination = page > 1 || hasNextPage;

  const columns: Column<CustomerDetailOut>[] = [
    {
      key: "name",
      header: "Customer",
      render: (c) => (
        <div className={f.nameCell}>
          <span className={f.avatar} aria-hidden="true">
            {initials(c.name, c.phone)}
          </span>
          <div className={f.nameStack}>
            <span className={f.custName}>{c.name?.trim() || "Guest"}</span>
            <span className={f.phoneCell}>{c.phone}</span>
          </div>
        </div>
      ),
    },
    {
      key: "orders",
      header: "Orders",
      render: (c) => <span className={f.numCell}>{c.total_orders}</span>,
    },
    {
      key: "spend",
      header: "Spend",
      render: (c) => <span className={f.spendCell}>AED {c.total_spend}</span>,
    },
    {
      key: "opt",
      header: "Marketing",
      render: (c) => (
        <span className={`${f.mktPill} ${c.marketing_opted_in ? f.mktIn : f.mktOut}`}>
          {c.marketing_opted_in ? "Opted in" : "Opted out"}
        </span>
      ),
    },
    {
      key: "open",
      header: "",
      render: (c) => (
        <button
          type="button"
          className={f.rowOpen}
          aria-label={`View ${c.name?.trim() || c.phone}`}
          title="View customer"
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/customers/${c.id}`);
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
          </svg>
        </button>
      ),
    },
  ];

  return (
    <div className={s.screen}>
      <PageHeader title="Customers" subtitle="Find guests by phone, spend, or marketing status" />
      <div className={f.filterBar}>
        <div className={f.phoneSearchBlock}>
          <span className={f.phoneSearchLabel}>Phone search</span>
          <div className={f.searchWrap}>
            <span className={f.searchIcon} aria-hidden="true">📞</span>
            <input
              className={`${f.search} ${f.phoneSearch}`}
              type="search"
              inputMode="tel"
              autoComplete="tel"
              placeholder="Search by phone number or name"
              aria-label="Search customers by phone or name"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <span className={f.phoneSearchHint}>Primary lookup for returning guests at the counter</span>
        </div>
        <div className={f.groups}>
          <div className={f.filterGroup}>
            <span className={f.filterLabel}>Min spend (AED)</span>
            <input
              className={f.minSpend}
              type="number"
              min="0"
              inputMode="decimal"
              aria-label="Minimum spend in AED"
              placeholder="0"
              value={minSpend}
              onChange={(e) => setMinSpend(e.target.value)}
            />
          </div>
          <div className={f.filterGroup}>
            <span className={f.filterLabel}>Marketing</span>
            <div className={f.segment} role="group" aria-label="Marketing filter">
              {MARKETING_TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  className={`${f.chip} ${marketing === t.key ? f.chipActive : ""}`}
                  aria-pressed={marketing === t.key}
                  onClick={() => setMarketing(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <div className={f.filterGroup}>
            <span className={f.filterLabel}>Orders</span>
            <div className={f.segment} role="group" aria-label="Order activity filter">
              {ACTIVITY_TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  className={`${f.chip} ${activity === t.key ? f.chipActive : ""}`}
                  aria-pressed={activity === t.key}
                  onClick={() => setActivity(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className={s.tableCard}>
        <div className={s.tableHead}>
          <span className={s.tableTitle}>Customer list</span>
          <span className={s.tableCount}>
            {filtered.length} on this page{isFetching && !loading ? " · refreshing…" : ""}{" "}
            <QueryRefreshNote show={isError && customers.length > 0} />
          </span>
        </div>
        {isError && customers.length === 0 && !loading ? (
          <ErrorState
            title="Could not load customers"
            description="Check your connection and try again."
          />
        ) : !loading && filtered.length === 0 ? (
          <EmptyState
            title="No customers found"
            description={
              debouncedSearch
                ? "Try another phone number or clear filters."
                : "Customers appear here after their first order."
            }
          />
        ) : (
          <CompactTable<CustomerDetailOut>
            columns={columns}
            rows={filtered}
            rowKey={(c) => c.id}
            onRowClick={(c) => navigate(`/customers/${c.id}`)}
            emptyText="No customers found"
            loading={loading}
          />
        )}
      </div>
      {showPagination && (
        <div className={s.pagination}>
          <span className={s.pageInfo}>
            Page {page}
            {filtered.length > 0
              ? ` · ${(page - 1) * PAGE_SIZE + 1}–${(page - 1) * PAGE_SIZE + filtered.length}`
              : ""}
          </span>
          <div className={s.pageBtns}>
            <button className={s.pageBtn} disabled={page <= 1} onClick={() => setPage(page - 1)}>
              ‹ Prev
            </button>
            <span className={s.pageNum}>Page {page}</span>
            <button className={s.pageBtn} disabled={!hasNextPage} onClick={() => setPage(page + 1)}>
              Next ›
            </button>
          </div>
        </div>
      )}
    </div>
  );
}