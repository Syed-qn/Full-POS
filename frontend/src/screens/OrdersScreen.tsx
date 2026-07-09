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
  const channel = order.source_channel || order.aggregator_source || order.order_type || "—";
  const batched = !!(order.batch_size && order.batch_size > 1);

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
          })}
        />
      </div>
      <div className={s.cardName}>{order.customer_name}</div>
      <div className={s.cardPhone}>{order.customer_phone || "—"}</div>
      <div className={s.cardItems} title={items.join(", ")}>
        {itemsLabel}
      </div>
      <div className={s.cardMeta}>
        <span className={s.cardChannel}>{channel}</span>
        <span className={s.cardTime}>{formatTime(order.created_at)}</span>
        <span className={s.cardTotal}>AED {order.total_aed}</span>
      </div>
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
    </button>
  );
}

export function OrdersScreen() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | OrderStatus>("all");
  const [batchFilter, setBatchFilter] = useState<string>("all");
  const [channelFilter, setChannelFilter] = useState("all");
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
      status: statusFilter === "all" ? undefined : statusFilter,
      fromDate: fromDate || undefined,
      toDate: toDate || undefined,
      q: debouncedSearch.trim() || undefined,
      channel: channelFilter === "all" ? undefined : channelFilter,
      page,
      limit: PAGE_SIZE,
    }),
    [statusFilter, fromDate, toDate, debouncedSearch, channelFilter, page],
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

  const filtered = useMemo(() => {
    let base = [...orders];
    if (batchFilter === "single") {
      base = base.filter((o) => !o.batch_preview && !(o.batch_size != null && o.batch_size > 1));
    } else if (batchFilter !== "all") {
      base = base.filter((o) => o.batch_preview === batchFilter);
    }
    return base;
  }, [orders, batchFilter]);

  const batchLabels = useMemo(
    () =>
      Array.from(
        new Set(orders.map((o) => o.batch_preview).filter((b): b is string => !!b)),
      ).sort(),
    [orders],
  );

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, statusFilter, fromDate, toDate, channelFilter]);

  const hasNextPage = orders.length === PAGE_SIZE;
  const pageRows = filtered;

  return (
    <div className={s.screen}>
      <PageHeader title="Orders" subtitle="Card board · search by phone or order # · open for detail" />
      <OfflineLimitsBanner surface="orders" />
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
                aria-label="Search orders"
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
          <div className={s.filterGroup}>
            <span className={s.filterLabel}>Batching</span>
            <select
              className={s.statusSelect}
              aria-label="Filter by batch"
              value={batchFilter}
              onChange={(e) => setBatchFilter(e.target.value)}
            >
              <option value="all">All orders</option>
              <option value="single">Single orders</option>
              {batchLabels.map((b) => (
                <option key={b} value={b}>🔗 Batch {b}</option>
              ))}
            </select>
          </div>
          <div className={s.filterGroup}>
            <span className={s.filterLabel}>Channel</span>
            <select
              className={s.statusSelect}
              aria-label="Filter by channel"
              value={channelFilter}
              onChange={(e) => setChannelFilter(e.target.value)}
            >
              <option value="all">All channels</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="talabat">Talabat</option>
              <option value="deliveroo">Deliveroo</option>
              <option value="careem">Careem</option>
              <option value="ubereats">Uber Eats</option>
              <option value="noon">Noon</option>
              <option value="zomato">Zomato</option>
              <option value="website">Website</option>
              <option value="mobile_app">Mobile app</option>
              <option value="instagram">Instagram</option>
              <option value="google_business">Google Business</option>
              <option value="qr">QR table</option>
              <option value="kiosk">Kiosk</option>
              <option value="call_center">Call center</option>
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
