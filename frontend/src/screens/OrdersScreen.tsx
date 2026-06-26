import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { CompactTable, type Column } from "../components/CompactTable";
import { StatusPill, STATUS_LABELS } from "../components/StatusPill";
import { PrepCountdown } from "../components/PrepCountdown";
import { fetchOrders } from "../lib/ordersApi";
import { usePollingRefresh } from "../lib/usePollingRefresh";
import type { OrderOut, OrderStatus } from "../lib/types";
import { OrderDetailDrawer } from "./OrderDetailDrawer";
import { PageHeader } from "../components/PageHeader";
import s from "./OrdersScreen.module.css";

const PAGE_SIZE = 20;

// Local YYYY-MM-DD (matches what <input type="date"> emits, so day-level
// comparisons are plain string compares in the restaurant's own timezone).
function toYMD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// Status options in FSM order (src/app/ordering/fsm.py), for the status filter.
const STATUS_OPTIONS: OrderStatus[] = [
  "draft", "pending_confirmation", "confirmed", "preparing", "ready", "assigned",
  "picked_up", "arriving", "delivered", "cancelled", "undeliverable",
  "on_resale", "resold", "written_off",
];

type PresetKey = "all" | "today" | "yesterday" | "7d" | "30d" | "month" | "custom";

const PRESETS: { key: Exclude<PresetKey, "custom">; label: string }[] = [
  { key: "all", label: "All" },
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "7d", label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
  { key: "month", label: "This month" },
];

// Resolve a preset to [from, to] day bounds (inclusive). "" means unbounded.
function presetRange(key: Exclude<PresetKey, "custom">, now: Date): [string, string] {
  const today = toYMD(now);
  switch (key) {
    case "today":
      return [today, today];
    case "yesterday": {
      const y = new Date(now);
      y.setDate(now.getDate() - 1);
      return [toYMD(y), toYMD(y)];
    }
    case "7d": {
      const f = new Date(now);
      f.setDate(now.getDate() - 6); // inclusive of today = 7 calendar days
      return [toYMD(f), today];
    }
    case "30d": {
      const f = new Date(now);
      f.setDate(now.getDate() - 29);
      return [toYMD(f), today];
    }
    case "month":
      return [toYMD(new Date(now.getFullYear(), now.getMonth(), 1)), today];
    case "all":
    default:
      return ["", ""];
  }
}

export function OrdersScreen() {
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | OrderStatus>("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [preset, setPreset] = useState<PresetKey>("all");
  const [openId, setOpenId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchOrders()
      .then(setOrders)
      .finally(() => setLoading(false));
  }, []);

  // Live updates: new orders + status/SLA changes appear without a refresh.
  // Filters are applied client-side (useMemo), so they survive each poll.
  usePollingRefresh(() => {
    fetchOrders().then(setOrders).catch(() => {});
  });

  function applyPreset(key: Exclude<PresetKey, "custom">) {
    const [from, to] = presetRange(key, new Date());
    setFromDate(from);
    setToDate(to);
    setPreset(key);
  }

  function setBound(which: "from" | "to", value: string) {
    if (which === "from") setFromDate(value);
    else setToDate(value);
    setPreset("custom");
  }

  // Open the native date picker on a click anywhere in the field (not just the
  // tiny calendar glyph). showPicker() is a no-op/throws on older browsers, so
  // guard it — they keep the default click-the-icon behaviour.
  function openPicker(e: MouseEvent<HTMLInputElement>) {
    try {
      e.currentTarget.showPicker?.();
    } catch {
      /* not supported / blocked — fall back to native behaviour */
    }
  }

  const filtered = useMemo(() => {
    const q = search.trim().replace(/^#/, "").toLowerCase();
    let base = [...orders].sort((a, b) => b.id - a.id); // newest first
    if (statusFilter !== "all") {
      base = base.filter((o) => o.status === statusFilter);
    }
    if (fromDate || toDate) {
      base = base.filter((o) => {
        const day = o.created_at ? toYMD(new Date(o.created_at)) : "";
        if (!day) return false;
        if (fromDate && day < fromDate) return false;
        if (toDate && day > toDate) return false;
        return true;
      });
    }
    if (!q) return base;
    return base.filter(
      (o) =>
        String(o.id).includes(q) ||
        o.customer_name.toLowerCase().includes(q) ||
        o.customer_phone.includes(q),
    );
  }, [orders, search, statusFilter, fromDate, toDate]);

  // Reset to the first page whenever any filter changes.
  useEffect(() => { setPage(1); }, [search, statusFilter, fromDate, toDate]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const columns: Column<OrderOut>[] = [
    { key: "id", header: "#", render: (o) => <span className={s.mono}>#{o.id}</span> },
    { key: "cust", header: "Customer", render: (o) => o.customer_name },
    { key: "items", header: "Items", render: (o) => o.items.map((i) => `${i.qty}× ${i.name}`).join(", ") },
    { key: "total", header: "Total", render: (o) => <span className={s.mono}>AED {o.total_aed}</span> },
    {
      key: "rider",
      header: "Rider",
      render: (o) => (
        <span className={s.riderCell}>
          {o.rider_name ?? "—"}
          {o.batch_size && o.batch_size > 1 ? (
            <span
              className={s.batchTag}
              title={`Batched on one rider trip. Prepare these together to protect the shared 40-min SLA: ${(o.batch_order_numbers ?? []).join(", ")}`}
            >
              🔗 {o.batch_size} together
            </span>
          ) : o.batch_preview ? (
            <span
              className={s.batchPreviewTag}
              title={`Will likely batch together (group ${o.batch_preview}) — nearby drop-offs. Prepare them together so they ride out on one trip.`}
            >
              🔗 will batch · {o.batch_preview}
            </span>
          ) : null}
        </span>
      ),
    },
    { key: "status", header: "Status", render: (o) => <StatusPill status={o.status} /> },
    {
      key: "kitchen",
      header: "Kitchen",
      render: (o) => {
        if (o.status === "preparing") {
          return <PrepCountdown prepDeadline={o.prep_deadline} label="Plate" />;
        }
        if (o.status === "confirmed") {
          // Not started yet → show "start cooking by" = plate-by − cook estimate.
          const startBy =
            o.prep_deadline && o.cook_estimate_minutes != null
              ? new Date(
                  Date.parse(o.prep_deadline) - o.cook_estimate_minutes * 60_000
                ).toISOString()
              : o.prep_deadline;
          return <PrepCountdown prepDeadline={startBy} label="Start" />;
        }
        return <span className={s.mono}>—</span>;
      },
    },
  ];

  return (
    <div className={s.screen}>
      <PageHeader title="Orders" subtitle="All delivery orders, live and past" />
      <div className={s.filterBar}>
        <div className={s.topRow}>
          <div className={`${s.filterGroup} ${s.grow}`}>
            <span className={s.filterLabel}>Search</span>
            <div className={s.searchWrap}>
              <span className={s.searchIcon} aria-hidden="true">🔍</span>
              <input
                className={s.search}
                placeholder="Search #ID, name or phone"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
          <div className={s.filterGroup}>
            <span className={s.filterLabel}>Status</span>
            <select
              className={s.statusSelect}
              aria-label="Filter by status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as "all" | OrderStatus)}
            >
              <option value="all">All statuses</option>
              {STATUS_OPTIONS.map((st) => (
                <option key={st} value={st}>
                  {STATUS_LABELS[st] ?? st}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className={s.groups}>
          <div className={s.filterGroup}>
            <span className={s.filterLabel}>Date range</span>
            <div className={s.dateRow}>
              <div className={s.presets} role="group" aria-label="Date range presets">
                {PRESETS.map((p) => (
                  <button
                    key={p.key}
                    type="button"
                    className={`${s.chip} ${preset === p.key ? s.chipActive : ""}`}
                    aria-pressed={preset === p.key}
                    onClick={() => applyPreset(p.key)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <div className={s.dateGroup}>
                <input
                  type="date"
                  aria-label="From date"
                  className={s.date}
                  value={fromDate}
                  max={toDate || undefined}
                  onClick={openPicker}
                  onChange={(e) => setBound("from", e.target.value)}
                />
                <span className={s.arrow} aria-hidden="true">→</span>
                <input
                  type="date"
                  aria-label="To date"
                  className={s.date}
                  value={toDate}
                  min={fromDate || undefined}
                  onClick={openPicker}
                  onChange={(e) => setBound("to", e.target.value)}
                />
                {(fromDate || toDate) && (
                  <button
                    type="button"
                    className={s.clearBtn}
                    aria-label="Clear dates"
                    title="Clear dates"
                    onClick={() => applyPreset("all")}
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className={s.tableCard}>
        <div className={s.tableHead}>
          <span className={s.tableTitle}>Order list</span>
          <span className={s.tableCount}>{filtered.length} {filtered.length === 1 ? "order" : "orders"}</span>
        </div>
        <CompactTable<OrderOut>
          columns={columns}
          rows={pageRows}
          rowKey={(o) => o.id}
          onRowClick={(o) => setOpenId(o.id)}
          emptyText="No orders match these filters"
          loading={loading}
          rowClassName={(o) => (o.batch_size && o.batch_size > 1 ? s.batchRow : undefined)}
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
