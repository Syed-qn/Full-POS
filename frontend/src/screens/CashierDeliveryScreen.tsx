import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "../components/Toaster";
import { WaiterTopBar } from "../components/WaiterTopBar";
import { assignOrder, fetchOrders, reassignOrder } from "../lib/ordersApi";
import { chargePayment } from "../lib/paymentsApi";
import { fetchRiders } from "../lib/ridersApi";
import { usePosTheme } from "../lib/posTheme";
import type { OrderOut, RiderOut } from "../lib/types";
import s from "./CashierTakeawayScreen.module.css";

/**
 * Buckets shown as filter chips. These GROUP the real order FSM statuses —
 * no invented states. Anything unmapped falls into "all" only.
 */
type Bucket =
  | "all"
  | "pending"
  | "preparing"
  | "ready"
  | "assigned"
  | "picked"
  | "completed"
  | "cancelled";

const BUCKET_STATUSES: Record<Exclude<Bucket, "all">, readonly string[]> = {
  pending: ["draft", "pending_confirmation", "confirmed"],
  preparing: ["preparing"],
  // Cooked and waiting for a rider (auto-dispatch or the cashier's manual pick).
  ready: ["ready"],
  // A rider is on the order but has not collected it yet.
  assigned: ["assigned"],
  // Rider has the food and is heading to / at the customer.
  picked: ["picked_up", "out_for_delivery", "arriving"],
  // Delivered = handed to the customer, the delivery is done.
  completed: ["delivered"],
  cancelled: ["cancelled", "undeliverable", "written_off"],
};

/** Key order IS the chip order — the delivery lifecycle left to right, ALL last:
 *  Pending → Preparing → Ready → Assigned → Picked Up → Completed → Cancelled. */
const BUCKET_LABEL: Record<Bucket, string> = {
  pending: "PENDING",
  preparing: "PREPARING",
  ready: "READY",
  assigned: "ASSIGNED",
  picked: "PICKED UP",
  completed: "COMPLETED ORDERS",
  cancelled: "CANCELLED ORDERS",
  all: "ACTIVE ORDERS",
};

/**
 * Filter chips the cashier actually sees. The whole live lifecycle (pending →
 * preparing → ready → assigned → picked up) lives under ALL — each order's ROW
 * still shows its exact stage via its status pill, so separate per-stage chips
 * were just noise. Completed and Cancelled stay as their own quick filters.
 */
const FILTER_CHIPS: Bucket[] = ["all", "completed", "cancelled"];

function bucketOf(status: string): Bucket | null {
  for (const [b, list] of Object.entries(BUCKET_STATUSES)) {
    if (list.includes(status)) return b as Bucket;
  }
  return null;
}

/** Friendly pill text for the REAL status (finer than the filter bucket) so the
 *  row shows the lifecycle step: Preparing → Ready → Assigned → On the way →
 *  Delivered, matching the rider/kitchen hops. */
const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  pending_confirmation: "Pending",
  confirmed: "Confirmed",
  preparing: "Preparing",
  ready: "Ready",
  assigned: "Assigned",
  picked_up: "Picked Up",
  out_for_delivery: "On the way",
  arriving: "Arriving",
  delivered: "Delivered",
  cancelled: "Cancelled",
  undeliverable: "Undeliverable",
  written_off: "Written off",
};
function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status.replace(/_/g, " ");
}

/** Short clock for the list rows (order creation time). */
function hhmm(iso?: string | null): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "n/a";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function itemCount(o: OrderOut): number {
  return (o.items ?? []).reduce((n, i) => n + (i.qty ?? 0), 0);
}

/**
 * Cashier Home Delivery — the delivery order list. Left: searchable,
 * status-filtered list of delivery orders. Right: the selected order, or an
 * empty prompt. "+ New Order" opens the till in delivery mode.
 *
 * Mirrors the Take Away till (same layout, chips, and payment cluster); the
 * only difference is the channel it lists and creates (order_type=delivery).
 */
export function CashierDeliveryScreen() {
  const navigate = useNavigate();
  const theme = usePosTheme();
  const [orders, setOrders] = useState<OrderOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Open on the live queue, not the full history.
  const [bucket, setBucket] = useState<Bucket>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [codOpen, setCodOpen] = useState(false);
  const [paying, setPaying] = useState(false);
  // Manual rider assignment (cashier override of the auto-dispatch on Ready).
  const [riders, setRiders] = useState<RiderOut[]>([]);
  const [assignTo, setAssignTo] = useState<number | "">("");
  const [assigning, setAssigning] = useState(false);

  // On the FIRST load, an empty list skips straight to the delivery till
  // (replace: so Back still leaves the section). Guarded by a ref so the 20s
  // poll can never yank the cashier away mid-work — unless they came here ON
  // PURPOSE from the till ("‹ Orders"), in which case we stay put.
  const [params] = useSearchParams();
  const firstLoadDone = useRef(params.get("from") === "till");

  const load = useCallback(async () => {
    try {
      const rows = await fetchOrders({
        orderType: "delivery",
        limit: 100,
        previewBatch: false,
      });
      // Only cashier-entered (POS) deliveries live here; customer WhatsApp
      // orders — same order_type — belong to the WhatsApp queue.
      const list = (Array.isArray(rows) ? rows : []).filter(
        (o) => o.source_channel === "pos",
      );
      setOrders(list);
      setError(null);
      if (!firstLoadDone.current) {
        firstLoadDone.current = true;
        if (list.length === 0) {
          navigate("/cashier/new-order?type=delivery", { replace: true });
          return; // stay on the spinner — we are leaving this screen
        }
      }
    } catch (e) {
      firstLoadDone.current = true;
      setError(e instanceof Error ? e.message : "Could not load delivery orders");
    }
    setLoading(false);
  }, [navigate]);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 20_000);
    return () => clearInterval(id);
  }, [load]);

  const counts = useMemo(() => {
    const c: Record<Bucket, number> = {
      all: 0,
      pending: 0,
      preparing: 0,
      ready: 0,
      assigned: 0,
      picked: 0,
      completed: 0,
      cancelled: 0,
    };
    for (const o of orders) {
      const b = bucketOf(String(o.status));
      if (b) c[b] += 1;
      // ALL = the live queue only: everything that isn't finished or cancelled.
      if (b !== "completed" && b !== "cancelled") c.all += 1;
    }
    return c;
  }, [orders]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = orders.filter((o) => {
      const b = bucketOf(String(o.status));
      // ALL shows the live lifecycle only (pending → picked up); Completed and
      // Cancelled are their own chips, so they're excluded from ALL.
      if (bucket === "all") {
        if (b === "completed" || b === "cancelled") return false;
      } else if (b !== bucket) {
        return false;
      }
      if (!q) return true;
      return (
        (o.order_number ?? "").toLowerCase().includes(q) ||
        (o.customer_name ?? "").toLowerCase().includes(q) ||
        (o.customer_phone ?? "").includes(q) ||
        String(o.daily_token ?? "").includes(q)
      );
    });
    // Newest-first almost everywhere: the order just rung up sits on top. READY
    // is the exception — those are people waiting on food, oldest served first.
    if (bucket === "ready") {
      return [...rows].sort(
        (a, b) => Date.parse(a.created_at ?? "") - Date.parse(b.created_at ?? ""),
      );
    }
    return rows;
  }, [orders, bucket, search]);

  const selected = useMemo(
    () => visible.find((o) => o.id === selectedId) ?? null,
    [visible, selectedId],
  );

  /** Once a rider has the order (assigned/picked) or it is delivered/cancelled,
   *  it is read-only — no more items can be rung onto it (the kitchen is done). */
  const settled = useMemo(() => {
    if (!selected) return false;
    const b = bucketOf(String(selected.status));
    return b === "assigned" || b === "picked" || b === "completed" || b === "cancelled";
  }, [selected]);

  /** Cooked (or beyond) and not yet out the door — a rider can be assigned. */
  const canAssign = useMemo(() => {
    const st = String(selected?.status ?? "");
    return st === "ready" || st === "assigned";
  }, [selected]);

  // Pull the rider roster while an order is waiting on a rider, and sync the
  // dropdown to whoever is already on it.
  useEffect(() => {
    if (!canAssign) {
      setRiders([]);
      setAssignTo("");
      return;
    }
    let cancelled = false;
    fetchRiders()
      .then((r) => !cancelled && setRiders(Array.isArray(r) ? r : []))
      .catch(() => !cancelled && setRiders([]));
    setAssignTo(selected?.rider_id ?? "");
    return () => {
      cancelled = true;
    };
  }, [canAssign, selected?.id, selected?.rider_id]);

  /** Assign (or reassign) the picked rider — sends the run to their app. */
  async function assignRider() {
    if (!selected || assignTo === "") return;
    setAssigning(true);
    try {
      const already = selected.rider_id != null;
      const updated = already
        ? await reassignOrder(selected.id, Number(assignTo))
        : await assignOrder(selected.id, Number(assignTo));
      toast(`${updated.order_number} assigned to ${updated.rider_name ?? "rider"}.`);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not assign rider", "error");
    } finally {
      setAssigning(false);
    }
  }

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
    navigate("/cashier/new-order?type=delivery");
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
    <div className={s.root} data-theme={theme} data-testid="cashier-delivery-screen">
      <WaiterTopBar active="delivery" />

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
                aria-label="Search delivery orders"
                data-testid="delivery-search"
              />
            </label>
            <button
              type="button"
              className={s.newBtn}
              onClick={newOrder}
              data-testid="delivery-new-order"
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
                  ? "No home delivery orders yet. Start one with + New Order."
                  : "No orders match this filter."}
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
                    data-testid={`delivery-row-${o.id}`}
                  >
                    <span className={s.rowTop}>
                      <span className={s.ref}>{o.order_number}</span>
                      <span className={`${s.pill} ${b ? s[`p_${b}`] : ""}`}>
                        {statusLabel(String(o.status)).toUpperCase()}
                      </span>
                      <span className={s.time}>{hhmm(o.created_at)}</span>
                    </span>
                    <span className={s.rowName}>
                      {o.customer_name?.trim() || o.customer_phone || "Walk in"}
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
                🛵
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
                    {selected.customer_name?.trim() || selected.customer_phone || "Walk in"}
                    {selected.daily_token != null ? ` · Token ${selected.daily_token}` : ""}
                  </p>
                </div>
                <span
                  className={`${s.pill} ${
                    bucketOf(String(selected.status))
                      ? s[`p_${bucketOf(String(selected.status))}`]
                      : ""
                  }`}
                >
                  {statusLabel(String(selected.status)).toUpperCase()}
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

              {/* Manual rider assignment. Ready orders auto-dispatch, but the
                  cashier can pick or swap the rider here — assigning sends the
                  run to that rider's app. */}
              {canAssign && (
                <div className={s.assignRow} data-testid="delivery-assign">
                  <span className={s.assignLabel}>
                    {selected.rider_name
                      ? `🛵 Rider: ${selected.rider_name}`
                      : "🛵 No rider yet"}
                  </span>
                  <select
                    className={s.assignSelect}
                    value={assignTo}
                    onChange={(e) =>
                      setAssignTo(e.target.value === "" ? "" : Number(e.target.value))
                    }
                    disabled={assigning}
                    aria-label="Assign to rider"
                  >
                    <option value="">
                      {selected.rider_id ? "Reassign rider…" : "Assign rider…"}
                    </option>
                    {riders
                      .filter((r) => r.status !== "deactivated")
                      .map((r) => {
                        // Unpaired riders have no app, so they can't receive the
                        // run — visible but disabled so the cashier sees why.
                        const unpaired = r.app_paired === false;
                        return (
                          <option key={r.id} value={r.id} disabled={unpaired}>
                            {r.name}{" "}
                            {unpaired ? "(not paired)" : `(${r.status.replace(/_/g, " ")})`}
                          </option>
                        );
                      })}
                  </select>
                  <button
                    type="button"
                    className={`${s.act} ${s.actPay}`}
                    disabled={assigning || assignTo === "" || assignTo === selected.rider_id}
                    onClick={() => void assignRider()}
                    data-testid="delivery-assign-btn"
                  >
                    {assigning
                      ? "Assigning…"
                      : selected.rider_id
                        ? "Reassign"
                        : "Assign rider"}
                  </button>
                </div>
              )}

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
                      navigate(`/cashier/new-order?type=delivery&order=${selected.id}`)
                    }
                    data-testid="delivery-add-item"
                  >
                    ➕ Add Item
                  </button>
                )}
                <button
                  type="button"
                  className={s.act}
                  onClick={printBill}
                  data-testid="delivery-print-bill"
                >
                  🧾 Print Bill
                </button>
                <button
                  type="button"
                  className={s.act}
                  disabled={paying || settled}
                  onClick={otherPay}
                  data-testid="delivery-other-pay"
                >
                  💳 Other Pay
                </button>
                {/* Last = closest to the screen edge: the fastest target for the
                    button pressed on nearly every COD delivery order. */}
                <button
                  type="button"
                  className={`${s.act} ${s.actPay}`}
                  disabled={paying || settled}
                  onClick={() => setCodOpen(true)}
                  data-testid="delivery-cod"
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
              <strong data-testid="delivery-cod-total">AED {selected.total_aed}</strong>
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
                data-testid="delivery-cod-collect"
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
