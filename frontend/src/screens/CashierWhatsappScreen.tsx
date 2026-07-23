import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "../components/Toaster";
import { WaiterTopBar } from "../components/WaiterTopBar";
import { advanceOrder, fetchOrders } from "../lib/ordersApi";
import { usePosTheme } from "../lib/posTheme";
import type { OrderOut } from "../lib/types";
import s from "./CashierTakeawayScreen.module.css";

/**
 * Cashier WhatsApp queue. WhatsApp = the delivery/online channel (order_types.py:
 * "WhatsApp defaults use delivery"). Drafts and unconfirmed carts never appear —
 * the cashier only ever sees an order the customer has CONFIRMED in chat.
 *
 * Flow the cashier drives: a confirmed order gets a KOT ("send to kitchen"),
 * which advances it to PREPARING; the kitchen then bumps it to READY on the KDS,
 * and auto-dispatch hands it to a rider. This screen shows each step live.
 */
type Bucket = "new" | "preparing" | "ready" | "out" | "delivered" | "cancelled";

// Buckets GROUP the real order FSM statuses — no invented states. Draft and
// pending_confirmation are deliberately absent: an unconfirmed order is not the
// cashier's yet.
const BUCKET_STATUSES: Record<Bucket, readonly string[]> = {
  new: ["confirmed"],
  preparing: ["preparing"],
  ready: ["ready"],
  out: ["assigned", "picked_up", "arriving"],
  delivered: ["delivered"],
  cancelled: ["cancelled", "undeliverable", "written_off", "on_resale"],
};

const BUCKET_LABEL: Record<Bucket, string> = {
  new: "NEW",
  preparing: "PREPARING",
  ready: "READY",
  out: "OUT",
  delivered: "DELIVERED",
  cancelled: "CANCELLED",
};

// Reuse the takeaway pill colours (the css module only defines these five).
const PILL_CLASS: Record<Bucket, string> = {
  new: "p_pending",
  preparing: "p_preparing",
  ready: "p_ready",
  out: "p_preparing",
  delivered: "p_completed",
  cancelled: "p_cancelled",
};

function bucketOf(status: string): Bucket | null {
  for (const [b, list] of Object.entries(BUCKET_STATUSES)) {
    if (list.includes(status)) return b as Bucket;
  }
  return null;
}

function hhmm(iso?: string | null): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "n/a";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function itemCount(o: OrderOut): number {
  return (o.items ?? []).reduce((n, i) => n + (i.qty ?? 0), 0);
}

export function CashierWhatsappScreen() {
  const theme = usePosTheme();
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bucket, setBucket] = useState<Bucket>("new");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [kotBusy, setKotBusy] = useState(false);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const rows = await fetchOrders({
        orderType: "delivery,online",
        limit: 100,
        previewBatch: false,
      });
      const list = Array.isArray(rows) ? rows : [];
      // "after confirmed, no draft": hide anything the customer hasn't confirmed.
      setOrders(list.filter((o) => bucketOf(String(o.status)) !== null));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load WhatsApp orders");
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    // 10s: the KOT -> preparing -> ready hops are what the cashier is watching.
    const id = setInterval(() => void load(), 10_000);
    return () => clearInterval(id);
  }, [load]);

  const counts = useMemo(() => {
    const c = { new: 0, preparing: 0, ready: 0, out: 0, delivered: 0, cancelled: 0 } as Record<
      Bucket,
      number
    >;
    for (const o of orders) {
      const b = bucketOf(String(o.status));
      if (b) c[b] += 1;
    }
    return c;
  }, [orders]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = orders.filter((o) => {
      if (bucketOf(String(o.status)) !== bucket) return false;
      if (!q) return true;
      return (
        (o.order_number ?? "").toLowerCase().includes(q) ||
        (o.customer_name ?? "").toLowerCase().includes(q) ||
        (o.customer_phone ?? "").includes(q)
      );
    });
    // Oldest-first inside a bucket: the order that has waited longest is the one
    // to KOT / hand out next.
    return [...rows].sort(
      (a, b) => Date.parse(a.created_at ?? "") - Date.parse(b.created_at ?? ""),
    );
  }, [orders, bucket, search]);

  const selected = useMemo(
    () => orders.find((o) => o.id === selectedId) ?? null,
    [orders, selectedId],
  );

  useEffect(() => {
    if (visible.length === 0) {
      if (selectedId !== null && !visible.some((o) => o.id === selectedId)) {
        // keep a selection from another bucket if it still exists in `orders`
        if (!orders.some((o) => o.id === selectedId)) setSelectedId(null);
      }
      return;
    }
    if (!visible.some((o) => o.id === selectedId)) setSelectedId(visible[0].id);
  }, [visible, selectedId, orders]);

  async function sendKot() {
    if (!selected || selected.status !== "confirmed") return;
    setKotBusy(true);
    try {
      const updated = await advanceOrder(selected.id);
      setOrders((prev) => prev.map((o) => (o.id === updated.id ? { ...o, ...updated } : o)));
      toast(`KOT sent · ${selected.order_number} is now preparing.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not send KOT", "error");
    } finally {
      setKotBusy(false);
    }
  }

  const selBucket = selected ? bucketOf(String(selected.status)) : null;

  return (
    <div className={s.root} data-theme={theme} data-testid="cashier-whatsapp-screen">
      <WaiterTopBar active="whatsapp" />

      <div className={s.body}>
        {/* ── LEFT: order list ─────────────────────────────────────────── */}
        <section className={s.list}>
          <div className={s.listHead}>
            <label className={s.searchWrap}>
              <span aria-hidden>🔍</span>
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search orders…"
                aria-label="Search WhatsApp orders"
                data-testid="whatsapp-search"
              />
            </label>
          </div>

          <div className={s.chips} role="tablist" aria-label="Order status">
            {(Object.keys(BUCKET_LABEL) as Bucket[]).map((b) => (
              <button
                key={b}
                type="button"
                role="tab"
                aria-selected={bucket === b}
                className={`${s.chip} ${bucket === b ? s.chipActive : ""}`}
                onClick={() => setBucket(b)}
              >
                {BUCKET_LABEL[b]} ({counts[b]})
              </button>
            ))}
          </div>

          <div className={s.rows}>
            {loading ? (
              <p className={s.msg}>Loading orders…</p>
            ) : error ? (
              <p className={s.msg}>{error}</p>
            ) : visible.length === 0 ? (
              <p className={s.msg}>
                {orders.length === 0
                  ? "No confirmed WhatsApp orders yet."
                  : "No orders in this status."}
              </p>
            ) : (
              visible.map((o) => {
                const b = bucketOf(String(o.status));
                return (
                  <button
                    key={o.id}
                    type="button"
                    className={`${s.row} ${selectedId === o.id ? s.rowActive : ""}`}
                    onClick={() => setSelectedId(o.id)}
                    data-testid={`whatsapp-row-${o.id}`}
                  >
                    <span className={s.rowTop}>
                      <span className={s.ref}>{o.order_number}</span>
                      <span className={`${s.pill} ${b ? s[PILL_CLASS[b]] : ""}`}>
                        {b ? BUCKET_LABEL[b] : String(o.status).toUpperCase()}
                      </span>
                      <span className={s.time}>{hhmm(o.created_at)}</span>
                    </span>
                    <span className={s.rowName}>
                      {o.customer_name?.trim() || o.customer_phone || "WhatsApp"}
                    </span>
                    <span className={s.rowFoot}>
                      <span className={s.rowMeta}>
                        {itemCount(o)} item{itemCount(o) === 1 ? "" : "s"}
                      </span>
                      <span className={s.rowTotal}>AED {o.total_aed}</span>
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </section>

        {/* ── RIGHT: selected order ────────────────────────────────────── */}
        <section className={s.detail}>
          {!selected ? (
            <div className={s.empty}>
              <span className={s.emptyIcon} aria-hidden>
                💬
              </span>
              <p>Select a WhatsApp order</p>
            </div>
          ) : (
            <div className={s.detailInner}>
              <div className={s.detailHead}>
                <div>
                  <h2 className={s.detailRef}>{selected.order_number}</h2>
                  <p className={s.detailSub}>
                    {selected.customer_name?.trim() || selected.customer_phone || "WhatsApp"}
                    {selected.rider_name ? ` · Rider ${selected.rider_name}` : ""}
                  </p>
                </div>
                <span className={`${s.pill} ${selBucket ? s[PILL_CLASS[selBucket]] : ""}`}>
                  {selBucket ? BUCKET_LABEL[selBucket] : String(selected.status).toUpperCase()}
                </span>
              </div>

              <div className={s.itemList}>
                {(selected.items ?? []).map((i, idx) => (
                  <div className={s.itemRow} key={`${i.dish_number ?? i.name}-${idx}`}>
                    <span className={s.itemName}>
                      {i.qty}× {i.name}
                      {i.notes ? <em className={s.itemNote}>📝 {i.notes}</em> : null}
                    </span>
                    <span className={s.itemAmt}>{i.price_aed}</span>
                  </div>
                ))}
              </div>

              <div className={s.detailTotal}>
                <span>Order total</span>
                <strong>AED {selected.total_aed}</strong>
              </div>

              <div className={s.detailActions}>
                {selected.status === "confirmed" ? (
                  // KOT: the one action the cashier takes here. Advances the order
                  // to PREPARING (confirmed -> preparing) and prints/sends to the KDS.
                  <button
                    type="button"
                    className={`${s.act} ${s.actPay}`}
                    disabled={kotBusy}
                    onClick={() => void sendKot()}
                    data-testid="whatsapp-kot"
                  >
                    {kotBusy ? "Sending…" : "🧾 KOT · Send to Kitchen"}
                  </button>
                ) : selected.status === "preparing" ? (
                  <span className={s.actState} role="status" data-testid="whatsapp-state">
                    👨‍🍳 In the kitchen, waiting for Ready
                  </span>
                ) : selected.status === "ready" ? (
                  <span className={s.actState} role="status" data-testid="whatsapp-state">
                    ✅ Ready, dispatching to a rider
                  </span>
                ) : (
                  <span className={s.actState} role="status" data-testid="whatsapp-state">
                    {selBucket ? BUCKET_LABEL[selBucket] : String(selected.status).toUpperCase()}
                  </span>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
