import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "../components/Toaster";
import { WaiterTopBar } from "../components/WaiterTopBar";
import { fetchOrders } from "../lib/ordersApi";
import { chargePayment } from "../lib/paymentsApi";
import { usePosTheme } from "../lib/posTheme";
import type { OrderOut } from "../lib/types";
import s from "./CashierTakeawayScreen.module.css";

/**
 * Buckets shown as filter chips. These GROUP the real order FSM statuses —
 * no invented states. Anything unmapped falls into "all" only.
 */
type Bucket = "all" | "pending" | "preparing" | "ready" | "completed" | "cancelled";

const BUCKET_STATUSES: Record<Exclude<Bucket, "all">, readonly string[]> = {
  pending: ["draft", "pending_confirmation", "confirmed"],
  preparing: ["preparing"],
  ready: ["ready"],
  // A takeaway is finished once it leaves the counter.
  completed: ["picked_up", "delivered"],
  cancelled: ["cancelled", "undeliverable", "written_off"],
};


function bucketOf(status: string): Bucket | null {
  for (const [b, list] of Object.entries(BUCKET_STATUSES)) {
    if (list.includes(status)) return b as Bucket;
  }
  return null;
}

/**
 * On-premise (takeaway) order.status stays "confirmed" the whole time it's in
 * the kitchen — only the items advance. So for the pill/bucket, surface the real
 * kitchen stage (preparing → ready) while the order sits at a pre-kitchen
 * status; fall through to the order status for open (not yet fired) and terminal
 * (paid/cancelled) states. Without this the pill was stuck on PENDING even after
 * the kitchen marked it ready.
 */
function effStatus(o: OrderOut): string {
  const st = String(o.status);
  if (o.kitchen_stage && ["draft", "pending_confirmation", "confirmed"].includes(st)) {
    return o.kitchen_stage; // "preparing" | "ready"
  }
  return st;
}

/**
 * Filter chips the cashier sees: the whole live lifecycle (pending → preparing →
 * ready) lives under ACTIVE — each row still shows its exact stage via its pill,
 * so per-stage chips were just noise. Completed and Cancelled stay separate.
 */
type Filter = "active" | "completed" | "cancelled";
const FILTER_LABEL: Record<Filter, string> = {
  active: "ACTIVE",
  completed: "COMPLETED",
  cancelled: "CANCELLED",
};
const FILTER_CHIPS: Filter[] = ["active", "completed", "cancelled"];

/** Map an order onto one of the three filter groups (via its kitchen stage). */
function filterOf(o: OrderOut): Filter | null {
  const b = bucketOf(effStatus(o));
  if (b === null) return null;
  if (b === "completed") return "completed";
  if (b === "cancelled") return "cancelled";
  return "active"; // pending / preparing / ready
}

/** Short clock for the list rows (order creation time). */
function hhmm(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function itemCount(o: OrderOut): number {
  return (o.items ?? []).reduce((n, i) => n + (i.qty ?? 0), 0);
}

/**
 * Cashier Take Away — the pickup order list. Left: searchable, status-filtered
 * list of takeaway orders. Right: the selected order, or an empty prompt.
 * "+ New Order" opens the takeaway till (the order terminal).
 */
export function CashierTakeawayScreen() {
  const navigate = useNavigate();
  const theme = usePosTheme();
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Open on the live queue, not the full history.
  const [bucket, setBucket] = useState<Filter>("active");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [codOpen, setCodOpen] = useState(false);
  const [paying, setPaying] = useState(false);

  // The list is only worth showing when there is something in it. On the FIRST
  // load, an empty list skips straight to the takeaway till (replace: so Back
  // still leaves the section instead of bouncing here again). Guarded by a ref
  // so the 20s poll can never yank the cashier away mid-work.
  // ...unless the cashier came here ON PURPOSE from the till ("‹ Orders"), in
  // which case bouncing them back would make the button look broken.
  const [params] = useSearchParams();
  const firstLoadDone = useRef(params.get("from") === "till");

  const load = useCallback(async () => {
    try {
      const rows = await fetchOrders({
        orderType: "takeaway",
        limit: 100,
        previewBatch: false,
      });
      const list = Array.isArray(rows) ? rows : [];
      setOrders(list);
      setError(null);
      if (!firstLoadDone.current) {
        firstLoadDone.current = true;
        if (list.length === 0) {
          navigate("/cashier/new-order?type=takeaway", { replace: true });
          return; // stay on the spinner — we are leaving this screen
        }
      }
    } catch (e) {
      firstLoadDone.current = true;
      setError(e instanceof Error ? e.message : "Could not load takeaway orders");
    }
    setLoading(false);
  }, [navigate]);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 20_000);
    return () => clearInterval(id);
  }, [load]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { active: 0, completed: 0, cancelled: 0 };
    for (const o of orders) {
      const f = filterOf(o);
      if (f) c[f] += 1;
    }
    return c;
  }, [orders]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = orders.filter((o) => {
      if (filterOf(o) !== bucket) return false;
      if (!q) return true;
      return (
        (o.order_number ?? "").toLowerCase().includes(q) ||
        (o.customer_name ?? "").toLowerCase().includes(q) ||
        (o.customer_phone ?? "").includes(q) ||
        String(o.daily_token ?? "").includes(q)
      );
    });
    // The API returns newest-first, which is what a cashier wants almost
    // everywhere: the order just rung up sits on top and is auto-selected. In
    // the ACTIVE queue, a READY order (someone standing at the counter) floats
    // to the top so whoever is waiting on food is served first.
    if (bucket === "active") {
      return [...rows].sort((a, b) => {
        const aReady = bucketOf(effStatus(a)) === "ready" ? 0 : 1;
        const bReady = bucketOf(effStatus(b)) === "ready" ? 0 : 1;
        if (aReady !== bReady) return aReady - bReady;
        return Date.parse(a.created_at ?? "") - Date.parse(b.created_at ?? "");
      });
    }
    return rows;
  }, [orders, bucket, search]);

  const selected = useMemo(
    () => visible.find((o) => o.id === selectedId) ?? null,
    [visible, selectedId],
  );

  /** Picked up / delivered / cancelled — the order is closed, so it is read-only. */
  const settled = useMemo(() => {
    if (!selected) return false;
    const b = bucketOf(effStatus(selected));
    return b === "completed" || b === "cancelled";
  }, [selected]);

  // Land on the top order so the right pane is useful immediately — and keep it
  // valid when a filter or the poll drops the current pick out of the list.
  useEffect(() => {
    if (visible.length === 0) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!visible.some((o) => o.id === selectedId)) setSelectedId(visible[0].id);
  }, [visible, selectedId]);

  function newOrder() {
    navigate("/cashier/new-order?type=takeaway");
  }

  /** Same stub as the till — there is no printer integration yet, so say so. */
  function printBill() {
    toast(
      selected ? "Bill print queued (when printer configured)." : "Select an order first.",
    );
  }

  /** Card / wallet / split — the full checkout screen handles those. */
  function otherPay() {
    if (!selected) return;
    navigate(`/orders/${selected.id}/pay?tender=card`);
  }

  /** COD quick-collect: charge the whole order as cash and settle in place. */
  async function collectCod() {
    if (!selected) return;
    const amount = Number(selected.total_aed ?? 0) || 0;
    setPaying(true);
    try {
      await chargePayment({
        order_id: selected.id,
        tender_type: "cash",
        amount_aed: amount.toFixed(2),
        channel: "pos_cod",
        terminal_id: "cashier-cod",
      });
      toast(`Collected AED ${amount.toFixed(2)} · ${selected.order_number} settled.`);
      setCodOpen(false);
      await load(); // pull the new status back into the list
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not collect payment", "error");
    } finally {
      setPaying(false);
    }
  }

  return (
    <div className={s.root} data-theme={theme} data-testid="cashier-takeaway-screen">
      <WaiterTopBar active="takeaway" />

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
                aria-label="Search takeaway orders"
                data-testid="takeaway-search"
              />
            </label>
            <button
              type="button"
              className={s.newBtn}
              onClick={newOrder}
              data-testid="takeaway-new-order"
            >
              + New Order
            </button>
          </div>

          <div className={s.chips} role="tablist" aria-label="Order status">
            {FILTER_CHIPS.map((b) => (
              <button
                key={b}
                type="button"
                role="tab"
                aria-selected={bucket === b}
                className={`${s.chip} ${bucket === b ? s.chipActive : ""}`}
                onClick={() => setBucket(b)}
              >
                {FILTER_LABEL[b]} ({counts[b]})
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
                  ? "No takeaway orders yet — start one with + New Order."
                  : "No orders match this filter."}
              </p>
            ) : (
              visible.map((o) => {
                const b = bucketOf(effStatus(o));
                return (
                  <button
                    key={o.id}
                    type="button"
                    className={`${s.row} ${selectedId === o.id ? s.rowActive : ""}`}
                    onClick={() => setSelectedId(o.id)}
                    data-testid={`takeaway-row-${o.id}`}
                  >
                    <span className={s.rowTop}>
                      <span className={s.ref}>{o.order_number}</span>
                      <span className={`${s.pill} ${b ? s[`p_${b}`] : ""}`}>
                        {(b ?? String(o.status)).toUpperCase()}
                      </span>
                      <span className={s.time}>{hhmm(o.created_at)}</span>
                    </span>
                    <span className={s.rowName}>
                      {o.customer_name?.trim() || o.customer_phone || "Walk-in"}
                    </span>
                    <span className={s.rowFoot}>
                      <span className={s.rowMeta}>
                        {o.daily_token != null ? `Token ${o.daily_token} · ` : ""}
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
                🛍
              </span>
              <p>Select an order or create a new one</p>
              <button type="button" className={s.newBtnGhost} onClick={newOrder}>
                + New Order
              </button>
            </div>
          ) : (
            <div className={s.detailInner}>
              <div className={s.detailHead}>
                <div>
                  <h2 className={s.detailRef}>{selected.order_number}</h2>
                  <p className={s.detailSub}>
                    {selected.customer_name?.trim() || selected.customer_phone || "Walk-in"}
                    {selected.daily_token != null ? ` · Token ${selected.daily_token}` : ""}
                  </p>
                </div>
                <span
                  className={`${s.pill} ${
                    bucketOf(effStatus(selected))
                      ? s[`p_${bucketOf(effStatus(selected))}`]
                      : ""
                  }`}
                >
                  {(bucketOf(effStatus(selected)) ?? String(selected.status)).toUpperCase()}
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

              {/* Same payment cluster as the till's bottom-right corner. */}
              <div className={s.detailActions}>
                {/* Reopens this ticket in the till so the next round APPENDS.
                    Hidden once the order is done — you cannot cook more food
                    onto an order that has already left or been cancelled. */}
                {!settled && (
                  <button
                    type="button"
                    className={s.act}
                    onClick={() =>
                      navigate(`/cashier/new-order?type=takeaway&order=${selected.id}`)
                    }
                    data-testid="takeaway-add-item"
                  >
                    ➕ Add Item
                  </button>
                )}
                <button
                  type="button"
                  className={s.act}
                  onClick={printBill}
                  data-testid="takeaway-print-bill"
                >
                  🧾 Print Bill
                </button>
                <button
                  type="button"
                  className={s.act}
                  disabled={paying || settled}
                  onClick={otherPay}
                  data-testid="takeaway-other-pay"
                >
                  💳 Other Pay
                </button>
                {/* Last = closest to the screen edge: the fastest target for the
                    button pressed on nearly every takeaway order. */}
                <button
                  type="button"
                  className={`${s.act} ${s.actPay}`}
                  disabled={paying || settled}
                  onClick={() => setCodOpen(true)}
                  data-testid="takeaway-cod"
                >
                  💵 Cash
                </button>
              </div>
            </div>
          )}
        </section>
      </div>

      {codOpen && selected && (
        <div
          className={s.modalBack}
          role="dialog"
          aria-modal="true"
          aria-label="Collect cash payment"
          onClick={() => !paying && setCodOpen(false)}
        >
          <div className={s.modal} onClick={(e) => e.stopPropagation()}>
            <div className={s.modalHead}>💵 Collect Cash · {selected.order_number}</div>

            <div className={s.codList}>
              {(selected.items ?? []).map((i, idx) => (
                <div className={s.codRow} key={`${i.dish_number ?? i.name}-${idx}`}>
                  <span className={s.codName}>
                    {i.qty}× {i.name}
                  </span>
                  <span className={s.codAmt}>{i.price_aed}</span>
                </div>
              ))}
            </div>

            <div className={s.codTotal}>
              <span>Total to collect</span>
              <strong data-testid="takeaway-cod-total">AED {selected.total_aed}</strong>
            </div>

            <div className={s.codActions}>
              <button
                type="button"
                className={s.codCancel}
                disabled={paying}
                onClick={() => setCodOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={s.codCollect}
                disabled={paying}
                onClick={() => void collectCod()}
                data-testid="takeaway-cod-collect"
              >
                {paying ? "Collecting…" : `✔ Collect AED ${selected.total_aed} (Cash)`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
