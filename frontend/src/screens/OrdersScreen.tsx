import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { QueryRefreshNote } from "../components/QueryRefreshNote";
import { StatusPill, STATUS_LABELS } from "../components/StatusPill";
import { PrepCountdown } from "../components/PrepCountdown";
import { EmptyState } from "../components/EmptyState";
import { Button } from "../components/Button";
import { orderStatusLabel } from "../lib/orderDisplay";
import { perfMark, perfNow } from "../lib/perf";
import { useOrdersQuery } from "../lib/queries/dashboard";
import type { OrderOut, OrderStatus } from "../lib/types";
import { OrderDetailDrawer } from "./OrderDetailDrawer";
import { PageHeader } from "../components/PageHeader";
import { OfflineLimitsBanner } from "../components/OfflineLimitsBanner";
import s from "./OrdersScreen.module.css";

const PAGE_SIZE = 20;

function toYMD(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

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
      f.setDate(now.getDate() - 6);
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

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function OrderCard({
  order,
  onOpen,
}: {
  order: OrderOut;
  onOpen: () => void;
}) {
  const items = order.items.map((i) => `${i.qty}× ${i.name}`);
  const itemsLabel =
    items.length <= 1 ? items[0] ?? "—" : `${items[0]} +${items.length - 1} more`;
  const batched = !!(order.batch_size && order.batch_size > 1);
  // Dine-in / takeaway have no rider, batching, or delivery SLA — skip that footer.
  const isOnPremise = ["dine_in", "takeaway", "drive_thru"].includes(
    String(order.order_type ?? ""),
  );
  // Clean, human order-type label instead of the raw "dine_in" channel string.
  // A "delivery" order is a customer WhatsApp order (order_types.py: "WhatsApp
  // defaults use delivery"), so the pill reads WhatsApp to match the Type filter.
  const TYPE_LABELS: Record<string, string> = {
    dine_in: "Dine-in",
    takeaway: "Take away",
    drive_thru: "Drive-thru",
    delivery: "WhatsApp",
    online: "Online",
  };
  const typeLabel =
    TYPE_LABELS[String(order.order_type ?? "")] ??
    order.source_channel ??
    order.aggregator_source ??
    "Order";
  // Hide the walk-in placeholder phone; show a friendly tag instead.
  const realPhone =
    order.customer_phone && order.customer_phone.replace(/0/g, "") !== ""
      ? order.customer_phone
      : null;

  return (
    <button
      type="button"
      className={`${s.orderCard} ${batched ? s.orderCardBatch : ""}`}
      onClick={onOpen}
    >
      <div className={s.cardTop}>
        <span className={s.cardId} title={order.order_number}>
          #{order.id}
        </span>
        <StatusPill
          status={order.status}
          label={orderStatusLabel(order.status, {
            resaleOfOrderId: order.resale_of_order_id,
            orderNumber: order.order_number,
            orderType: order.order_type,
            cancellationReason: order.cancellation_reason,
          })}
        />
      </div>
      <div className={s.cardName}>{order.customer_name || "Walk-in"}</div>
      {realPhone && <div className={s.cardPhone}>{realPhone}</div>}
      <div className={s.cardItems} title={items.join(", ")}>
        {itemsLabel}
      </div>
      <div className={s.cardMeta}>
        <span className={s.cardChannel}>{typeLabel}</span>
        <span className={s.cardTime}>{formatTime(order.created_at)}</span>
        <span className={s.cardTotal}>AED {order.total_aed}</span>
      </div>
      {!isOnPremise && (
      <div className={s.cardFoot}>
        <span className={s.cardRider}>
          {order.rider_name ?? "No rider"}
          {batched ? (
            <span
              className={s.batchTag}
              title={`Batched on one rider trip. Prepare these together to protect the shared 40-min SLA: ${(order.batch_order_numbers ?? []).join(", ")}`}
            >
              🔗 {order.batch_size} together
            </span>
          ) : order.batch_preview ? (
            <span
              className={s.batchPreviewTag}
              title={`Will likely batch together (group ${order.batch_preview}) — nearby drop-offs. Prepare them together so they ride out on one trip.`}
            >
              Batch {order.batch_preview}
            </span>
          ) : null}
        </span>
        <span className={s.cardKitchen}>
          {order.status === "preparing" ? (
            <PrepCountdown prepDeadline={order.prep_deadline} label="Plate" compact />
          ) : order.status === "confirmed" ? (
            <PrepCountdown
              prepDeadline={
                order.prep_deadline && order.cook_estimate_minutes != null
                  ? new Date(
                      Date.parse(order.prep_deadline) - order.cook_estimate_minutes * 60_000,
                    ).toISOString()
                  : order.prep_deadline
              }
              label="Start"
              compact
            />
          ) : (
            <span className={s.mono}>—</span>
          )}
        </span>
      </div>
      )}
    </button>
  );
}

/** Fulfilment filter. Each chip covers a FAMILY of order types — a tableside
 *  or QR order is still dine-in to a manager — sent as one comma-separated
 *  order_type so the server does the filtering across all pages. */
const TYPE_FILTERS = [
  { key: "all", label: "All", types: undefined },
  { key: "dine", label: "Dine In", types: "dine_in,tableside,qr" },
  { key: "takeaway", label: "Take Away", types: "takeaway,drive_thru" },
  // A customer WhatsApp order is a delivery order — order_types.py: "WhatsApp
  // defaults use delivery". `online` is the same self-service channel on the web.
  // Aggregator orders (Talabat etc.) are order_type "aggregator", so they stay
  // out of this tab on purpose.
  { key: "whatsapp", label: "WhatsApp", types: "delivery,online" },
] as const;
type TypeFilterKey = (typeof TYPE_FILTERS)[number]["key"];

/** Coarse status buckets, worded the way the cards read: a dine-in or take-away
 *  tab is Open until it is settled, then Paid. Sent as a comma-separated status
 *  list so the server filters across every page. */
const STATUS_BUCKETS: { key: string; label: string; statuses: string }[] = [
  { key: "bucket_open", label: "Open", statuses: "draft,pending_confirmation,confirmed,preparing,ready" },
  { key: "bucket_paid", label: "Paid", statuses: "delivered" },
];

export function OrdersScreen() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  // Either a bucket key from STATUS_BUCKETS or a single raw OrderStatus.
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<TypeFilterKey>("all");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [preset, setPreset] = useState<PresetKey>("all");
  const [openId, setOpenId] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const paintMark = useRef<number | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const listFilters = useMemo(
    () => ({
      previewBatch: true as const,
      status:
        statusFilter === "all"
          ? undefined
          : (STATUS_BUCKETS.find((b) => b.key === statusFilter)?.statuses ?? statusFilter),
      fromDate: fromDate || undefined,
      toDate: toDate || undefined,
      q: debouncedSearch.trim() || undefined,
      orderType: TYPE_FILTERS.find((t) => t.key === typeFilter)?.types,
      page,
      limit: PAGE_SIZE,
    }),
    [statusFilter, fromDate, toDate, debouncedSearch, typeFilter, page],
  );

  const { data: orders = [], isLoading, isFetching, isError } = useOrdersQuery(listFilters);
  const loading = isLoading && orders.length === 0;

  useEffect(() => {
    if (!loading && orders.length > 0 && paintMark.current != null) {
      perfMark("orders-first-paint", paintMark.current);
      paintMark.current = null;
    }
  }, [loading, orders.length]);

  useEffect(() => {
    paintMark.current = perfNow();
  }, [listFilters]);

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

  function openPicker(e: MouseEvent<HTMLInputElement>) {
    try {
      e.currentTarget.showPicker?.();
    } catch {
      /* not supported */
    }
  }

  // Every filter is server-side now; the list renders exactly what came back.
  const filtered = orders;

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, statusFilter, fromDate, toDate, typeFilter]);

  const hasNextPage = orders.length === PAGE_SIZE;
  const pageRows = filtered;

  return (
    <div className={s.screen}>
      <PageHeader title="Orders" subtitle="Card board · search by phone or order # · open for detail" />
      <OfflineLimitsBanner surface="orders" />
      {/* Every control is labelled and on the surface — no "More" drawer. A
          filter you cannot see is a filter you forget is applied. */}
      <div className={s.filterBar}>
        <div className={s.field}>
          <span className={s.filterLabel}>Search</span>
          <div className={s.searchWrap}>
            <span className={s.searchIcon} aria-hidden="true">🔍</span>
            <input
              className={s.search}
              placeholder="Search #ID, name or phone"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search orders"
            />
          </div>
        </div>
        <div className={s.field}>
          <span className={s.filterLabel}>Date</span>
          <div className={s.presets} role="group" aria-label="Date range">
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
        </div>
        <div className={s.field}>
          <span className={s.filterLabel}>Type</span>
          <div className={s.presets} role="group" aria-label="Fulfilment type">
            {TYPE_FILTERS.map((t) => (
              <button
                key={t.key}
                type="button"
                className={`${s.chip} ${typeFilter === t.key ? s.chipActive : ""}`}
                aria-pressed={typeFilter === t.key}
                onClick={() => setTypeFilter(t.key)}
                data-testid={`orders-type-${t.key}`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <label className={s.field}>
          <span className={s.filterLabel}>Status</span>
          <select
            className={s.statusSelect}
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All statuses</option>
            {STATUS_BUCKETS.map((b) => (
              <option key={b.key} value={b.key}>
                {b.label}
              </option>
            ))}
            {STATUS_OPTIONS.map((st) => (
              <option key={st} value={st}>
                {STATUS_LABELS[st] ?? st}
              </option>
            ))}
          </select>
        </label>
        {/* Kept from the old More drawer — the presets cannot express "these two
            days", and channel / batching only ever mattered for delivery. */}
        <div className={s.field}>
          <span className={s.filterLabel}>Custom range</span>
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

      <div className={s.listCard}>
        <div className={s.tableHead}>
          <span className={s.tableTitle}>Orders</span>
          <span className={s.tableCount}>
            {filtered.length} {filtered.length === 1 ? "order" : "orders"}
            {isFetching && !loading ? " · refreshing…" : ""}
            {" "}
            <QueryRefreshNote show={isError && orders.length > 0} />
          </span>
        </div>

        {loading ? (
          <div className={s.cardGrid} aria-busy="true" aria-label="Loading rows">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className={s.skCard} />
            ))}
          </div>
        ) : pageRows.length === 0 ? (
          <EmptyState
            title="No orders match these filters"
            description="Try another date, status, channel, or clear search."
          />
        ) : (
          <div className={s.cardGrid}>
            {pageRows.map((o) => (
              <OrderCard key={o.id} order={o} onOpen={() => setOpenId(o.id)} />
            ))}
          </div>
        )}
      </div>

      {(page > 1 || hasNextPage) && (
        <div className={s.pagination}>
          <span className={s.pageInfo}>
            Page {page}
            {hasNextPage ? "" : " (last)"}
          </span>
          <div className={s.pageBtns}>
            <Button
              type="button"
              variant="ghost"
              size="lg"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              ‹ Prev
            </Button>
            <span className={s.pageNum}>Page {page}</span>
            <Button
              type="button"
              variant="ghost"
              size="lg"
              disabled={!hasNextPage}
              onClick={() => setPage(page + 1)}
            >
              Next ›
            </Button>
          </div>
        </div>
      )}
      <OrderDetailDrawer orderId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}
