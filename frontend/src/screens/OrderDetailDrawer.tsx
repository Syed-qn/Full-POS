import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { SideDrawer } from "../components/SideDrawer";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/Button";
import { DispatchExplainSection } from "../components/DispatchExplainSection";
import { PrepCountdown } from "../components/PrepCountdown";
import { apiClient } from "../lib/apiClient";
import {
  DETAIL_INCLUDE_BY_TAB,
  fetchOrderDetail,
  mergeOrderDetail,
  orderOutFromDetail,
  patchAddress,
  patchCustomer,
} from "../lib/orderDetailApi";
import { perfMark, perfNow } from "../lib/perf";
import { useOrderDetailQuery } from "../lib/queries/dashboard";
import {
  assignOrder,
  cancelOrder,
  markDeliveryFailed,
  reassignOrder,
  setOrderPriority,
} from "../lib/ordersApi";
import { useManagerPinGate } from "../lib/requireManagerPin";
import { fetchRiders } from "../lib/ridersApi";
import type {
  AddressDetailOut,
  CustomerDetailOut,
  OrderDetailOut,
  OrderOut,
  RiderOut,
  TimelineEventOut,
} from "../lib/types";
import s from "./OrderDetailDrawer.module.css";

type Tab = "overview" | "timeline" | "chat" | "customer";

const KITCHEN_ADVANCEABLE = new Set(["confirmed", "preparing"]);
const ADVANCE_LABEL: Record<string, string> = {
  confirmed: "Start Preparing",
  preparing: "Mark as Ready",
};
// Restaurant may cancel any active order until delivery (not delivered/terminal).
const CANCELLABLE = new Set([
  "draft",
  "pending_confirmation",
  "confirmed",
  "preparing",
  "ready",
  "assigned",
  "picked_up",
  "arriving",
]);

export function OrderDetailDrawer({
  orderId,
  onClose,
}: {
  orderId: number | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<OrderDetailOut | null>(null);
  const [basicOrder, setBasicOrder] = useState<OrderOut | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const paintMark = useRef<number | null>(null);
  const include = DETAIL_INCLUDE_BY_TAB[tab];
  const { data: queryDetail, isPending, isError } = useOrderDetailQuery(orderId, tab);
  const [advancing, setAdvancing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [riders, setRiders] = useState<RiderOut[]>([]);
  const [reassignTo, setReassignTo] = useState<number | "">("");
  const [reassigning, setReassigning] = useState(false);
  const { requestPin, pinGate, pinBusy } = useManagerPinGate();

  useEffect(() => {
    if (orderId === null) {
      setDetail(null);
      setBasicOrder(null);
      return;
    }
    setTab("overview");
    setDetail(null);
    setBasicOrder(null);
    setReassignTo("");
    paintMark.current = perfNow();
  }, [orderId]);

  useEffect(() => {
    if (!queryDetail) return;
    setDetail((prev) => mergeOrderDetail(prev, queryDetail, include));
    setBasicOrder(orderOutFromDetail(queryDetail));
    if (queryDetail.status === "assigned") {
      fetchRiders().then(setRiders).catch(() => setRiders([]));
    }
    if (paintMark.current != null && tab === "overview") {
      perfMark("order-detail-overview", paintMark.current);
      paintMark.current = null;
    }
  }, [queryDetail, include, tab]);

  async function refreshDetail(id: number) {
    await queryClient.invalidateQueries({ queryKey: ["orders", "detail", id] });
    const d = await fetchOrderDetail(id, { include: DETAIL_INCLUDE_BY_TAB[tab] });
    setDetail((prev) => mergeOrderDetail(prev, d, include));
    setBasicOrder(orderOutFromDetail(d));
  }

  const loading = isPending && detail === null;
  const error = isError && detail === null ? "Failed to load order details" : null;

  async function assignAction() {
    if (!basicOrder || reassignTo === "") return;
    setReassigning(true);
    setActionError(null);
    try {
      const updated = await assignOrder(basicOrder.id, Number(reassignTo));
      setBasicOrder(updated);
      await refreshDetail(basicOrder.id);
      setReassignTo("");
      fetchRiders().then(setRiders).catch(() => {});
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to assign");
    } finally {
      setReassigning(false);
    }
  }

  async function reassignAction() {
    if (!basicOrder || reassignTo === "") return;
    setReassigning(true);
    setActionError(null);
    try {
      const updated = await reassignOrder(basicOrder.id, Number(reassignTo));
      setBasicOrder(updated);
      await refreshDetail(basicOrder.id);
      setReassignTo("");
      fetchRiders().then(setRiders).catch(() => {});
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to reassign");
    } finally {
      setReassigning(false);
    }
  }

  async function advanceStatus() {
    if (!basicOrder) return;
    setAdvancing(true);
    try {
      const updated = await apiClient.post<OrderOut>(`/api/v1/orders/${basicOrder.id}/advance`);
      setBasicOrder(updated);
      await refreshDetail(basicOrder.id);
    } finally {
      setAdvancing(false);
    }
  }

  function requestCancelOrder() {
    if (!basicOrder || !detail) return;
    setActionError(null);
    const statusMsg =
      detail.status === "preparing"
        ? "It's already being cooked. Cancelling stops the order — the food won't be resold. This cannot be undone."
        : ["ready", "assigned", "picked_up", "arriving"].includes(detail.status)
          ? "The order is already in progress. Cancelling will notify the customer and free the rider. This cannot be undone."
          : "This cannot be undone.";
    requestPin({
      actionType: "void",
      actionLabel: "Cancel / void order",
      recordLabel: basicOrder.order_number || String(basicOrder.id),
      reasonRequired: true,
      orderId: basicOrder.id,
      amountAed: basicOrder.total_aed,
      confirmTitle: "Cancel this order?",
      confirmMessage: `${statusMsg} Manager PIN required.`,
      confirmLabel: "Continue to PIN",
      cancelLabel: "Keep order",
      execute: async ({ reason }) => {
        setCancelling(true);
        try {
          const updated = await cancelOrder(basicOrder.id, reason || "void");
          setBasicOrder(updated);
          await refreshDetail(basicOrder.id);
        } catch (e) {
          setActionError(e instanceof Error ? e.message : "Failed to cancel order");
          throw e;
        } finally {
          setCancelling(false);
        }
      },
    });
  }

  function onCustomerSaved(updated: CustomerDetailOut) {
    if (!detail) return;
    setDetail({ ...detail, customer: updated });
  }

  function onAddressSaved(updated: AddressDetailOut) {
    if (!detail) return;
    setDetail({ ...detail, address: updated });
  }

  const title = basicOrder
    ? `Order ${basicOrder.order_number ?? `#${basicOrder.id}`}`
    : "Order";

  // On-premise (dine-in/takeaway/drive-thru): no rider, no cashier-driven
  // kitchen FSM — hide that UI and offer add-items instead.
  const otype = String(basicOrder?.order_type ?? "");
  const isOnPremise =
    otype === "dine_in" || otype === "takeaway" || otype === "drive_thru";
  const isDineIn = otype === "dine_in";

  return (
    <SideDrawer open={orderId !== null} title={title} onClose={onClose} wide>
      {loading && !detail ? (
        error ? <p style={{ color: "var(--text-secondary)", padding: "16px" }}>{error}</p> : <DrawerSkeleton />
      ) : !detail || !basicOrder ? (
        error ? <p style={{ color: "var(--text-secondary)", padding: "16px" }}>{error}</p> : <DrawerSkeleton />
      ) : (
        <div className={s.detail}>
          <div className={s.head}>
            <StatusPill status={detail.status} orderType={basicOrder.order_type} />
            {/* The live SLA countdown was removed from this header on request. A
                delivered order still shows its finish stamp so the drawer records
                WHEN it closed; nothing counts down while it is in flight. */}
            {detail.status === "delivered" && detail.delivered_at ? (
              <span className={s.deliveredStamp}>
                ✓ {isOnPremise ? "Paid" : "Delivered"}{" "}
                {new Date(detail.delivered_at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Asia/Dubai",
                })}
              </span>
            ) : null}
          </div>

          {!isOnPremise &&
            (detail.status === "confirmed" || detail.status === "preparing") &&
            detail.prep_deadline && (
              <div
                style={{
                  display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
                  padding: "6px 16px",
                }}
              >
                {detail.status === "confirmed" && detail.cook_estimate_minutes != null ? (
                  <PrepCountdown
                    prepDeadline={new Date(
                      Date.parse(detail.prep_deadline) -
                        detail.cook_estimate_minutes * 60_000
                    ).toISOString()}
                    label="Start"
                  />
                ) : (
                  <PrepCountdown prepDeadline={detail.prep_deadline} label="Plate" />
                )}
                <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>
                  {detail.cook_estimate_minutes != null
                    ? `~${detail.cook_estimate_minutes} min cook · `
                    : ""}
                  plate by{" "}
                  {new Date(detail.prep_deadline).toLocaleTimeString([], {
                    hour: "2-digit", minute: "2-digit", timeZone: "Asia/Dubai",
                  })}
                </span>
              </div>
            )}

          {(KITCHEN_ADVANCEABLE.has(detail.status) ||
            CANCELLABLE.has(detail.status) ||
            isDineIn) && (
            <div className={s.actionBar}>
              {isDineIn && CANCELLABLE.has(detail.status) && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    onClose();
                    navigate(
                      basicOrder.table_id
                        ? `/new-order?table=${basicOrder.table_id}`
                        : "/new-order",
                    );
                  }}
                >
                  + Add items
                </Button>
              )}
              {isOnPremise && CANCELLABLE.has(detail.status) && (
                <Button
                  onClick={() => {
                    onClose();
                    navigate(`/orders/${basicOrder.id}/pay`);
                  }}
                >
                  💳 Pay bill
                </Button>
              )}
              {KITCHEN_ADVANCEABLE.has(detail.status) && !isOnPremise && (
                <Button onClick={advanceStatus} disabled={advancing || cancelling}>
                  {advancing ? "Saving…" : ADVANCE_LABEL[detail.status]}
                </Button>
              )}
              {CANCELLABLE.has(detail.status) && (
                <Button
                  variant="danger"
                  onClick={requestCancelOrder}
                  disabled={advancing || cancelling || pinBusy}
                >
                  {cancelling ? "Cancelling…" : "Cancel Order"}
                </Button>
              )}
              {actionError && (
                <span style={{ color: "var(--danger, #dc2626)", fontSize: "13px" }}>
                  {actionError}
                </span>
              )}
            </div>
          )}

          {!isOnPremise &&
            (detail.status === "ready" ||
              detail.status === "preparing" ||
              detail.status === "confirmed") &&
            !detail.rider && (
              <div className={s.actionBar}>
                <select
                  className={s.reassignSelect}
                  value={reassignTo}
                  onChange={(e) =>
                    setReassignTo(e.target.value === "" ? "" : Number(e.target.value))
                  }
                  disabled={reassigning}
                  aria-label="Assign to rider"
                >
                  <option value="">Assign rider…</option>
                  {riders
                    .filter((r) => r.status !== "deactivated")
                    .map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name} ({r.status.replace(/_/g, " ")})
                      </option>
                    ))}
                </select>
                <Button onClick={assignAction} disabled={reassigning || reassignTo === ""}>
                  {reassigning ? "Assigning…" : "Assign rider"}
                </Button>
                <Button
                  variant="ghost"
                  onClick={async () => {
                    if (!basicOrder) return;
                    try {
                      const updated = await setOrderPriority(basicOrder.id, "priority");
                      setBasicOrder(updated);
                      await refreshDetail(basicOrder.id);
                    } catch (e) {
                      setActionError(e instanceof Error ? e.message : "Priority failed");
                    }
                  }}
                >
                  Mark priority
                </Button>
                {actionError && (
                  <span style={{ color: "var(--danger, #dc2626)", fontSize: "13px" }}>
                    {actionError}
                  </span>
                )}
              </div>
            )}

          {detail.status === "assigned" && (
            <div className={s.actionBar}>
              <select
                className={s.reassignSelect}
                value={reassignTo}
                onChange={(e) =>
                  setReassignTo(e.target.value === "" ? "" : Number(e.target.value))
                }
                disabled={reassigning}
                aria-label="Reassign to rider"
              >
                <option value="">Reassign to…</option>
                {riders
                  .filter((r) => r.status !== "deactivated" && r.id !== detail.rider?.id)
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} ({r.status.replace(/_/g, " ")})
                    </option>
                  ))}
              </select>
              <Button onClick={reassignAction} disabled={reassigning || reassignTo === ""}>
                {reassigning ? "Reassigning…" : "Reassign rider"}
              </Button>
              <Button
                variant="ghost"
                onClick={async () => {
                  if (!basicOrder) return;
                  try {
                    const updated = await setOrderPriority(basicOrder.id, "priority");
                    setBasicOrder(updated);
                    await refreshDetail(basicOrder.id);
                  } catch (e) {
                    setActionError(e instanceof Error ? e.message : "Priority failed");
                  }
                }}
              >
                Priority
              </Button>
              {actionError && (
                <span style={{ color: "var(--danger, #dc2626)", fontSize: "13px" }}>
                  {actionError}
                </span>
              )}
            </div>
          )}

          {(detail.status === "picked_up" || detail.status === "arriving") && (
            <div className={s.actionBar}>
              <select
                className={s.reassignSelect}
                aria-label="Delivery failure reason"
                defaultValue="customer_unreachable"
                id="fail-reason"
              >
                <option value="customer_unreachable">Customer unreachable</option>
                <option value="wrong_address">Wrong address</option>
                <option value="refused">Refused</option>
                <option value="unsafe">Unsafe</option>
                <option value="other">Other</option>
              </select>
              <Button
                variant="ghost"
                onClick={async () => {
                  if (!basicOrder) return;
                  const sel = document.getElementById("fail-reason") as HTMLSelectElement | null;
                  try {
                    const updated = await markDeliveryFailed(
                      basicOrder.id,
                      sel?.value || "customer_unreachable",
                    );
                    setBasicOrder(updated);
                    await refreshDetail(basicOrder.id);
                  } catch (e) {
                    setActionError(e instanceof Error ? e.message : "Fail failed");
                  }
                }}
              >
                Mark undeliverable
              </Button>
            </div>
          )}

          {/* Dine-in/takeaway: no rider timeline / WhatsApp chat / delivery customer
              profile — just the bill. Show the tab bar only when there's more than one. */}
          {!isOnPremise && (
            <div className={s.tabs} role="tablist">
              {(["overview", "timeline", "chat", "customer"] as Tab[]).map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  className={`${s.tab} ${tab === t ? s.activeTab : ""}`}
                  onClick={() => setTab(t)}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          )}

          <div className={s.tabContent}>
            {tab === "overview" && <OverviewTab detail={detail} />}
            {tab === "timeline" && <TimelineTab detail={detail} />}
            {tab === "chat" && <ChatTab detail={detail} />}
            {tab === "customer" && (
              <CustomerTab
                detail={detail}
                onCustomerSaved={onCustomerSaved}
                onAddressSaved={onAddressSaved}
              />
            )}
          </div>
        </div>
      )}
      {pinGate}
    </SideDrawer>
  );
}

// ── Loading skeleton (mirrors the drawer head/tabs/content) ──────────────────

function DrawerSkeleton() {
  return (
    <div className={s.detail} aria-busy="true" aria-label="Loading order">
      <div className={s.head}>
        <span className={`${s.sk} ${s.skPill}`} />
        <span className={`${s.sk} ${s.skTimer}`} />
      </div>
      <div className={s.tabs}>
        {Array.from({ length: 4 }).map((_, i) => (
          <span key={i} className={`${s.sk} ${s.skTab}`} />
        ))}
      </div>
      <div className={s.tabContent}>
        <div className={s.overview}>
          {Array.from({ length: 2 }).map((_, c) => (
            <section key={c} className={s.card}>
              <span className={`${s.sk} ${s.skCardTitle}`} />
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className={s.skRow}>
                  <span className={`${s.sk} ${s.skLine}`} style={{ width: "42%" }} />
                  <span className={`${s.sk} ${s.skLine}`} style={{ width: "22%" }} />
                </div>
              ))}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Overview Tab ─────────────────────────────────────────────────────────────

function OverviewTab({ detail }: { detail: OrderDetailOut }) {
  const t = String(detail.order_type ?? "");
  const isOnPremise = t === "dine_in" || t === "takeaway" || t === "drive_thru";
  return (
    <div className={s.overview}>
      {detail.convo_summary ? (
        <section className={`${s.card} ${s.summaryCard}`}>
          <h4 className={s.cardTitle}>📋 Conversation summary</h4>
          <div className={s.summaryBody}>
            {detail.convo_summary.split("\n").map((line, i) => (
              <div key={i} className={s.summaryLine}>{line}</div>
            ))}
          </div>
        </section>
      ) : null}
      <section className={s.card}>
        <h4 className={s.cardTitle}>Items</h4>
        <div className={s.items}>
          {detail.items.map((item, i) => (
            <div key={i} className={s.itemRow}>
              <span className={s.itemQtyBadge}>{item.qty}×</span>
              <span className={s.itemName}>
                {item.dish_name}
                {item.variant_name ? ` (${item.variant_name})` : ""}
                {item.notes ? (
                  <span className={s.itemNote}>📝 {item.notes}</span>
                ) : null}
              </span>
              <span className={s.itemPrice}>AED {item.line_total}</span>
            </div>
          ))}
        </div>
        {detail.customer?.phone && (
          <div className={s.customerContact}>
            <span className={s.customerContactLabel}>Customer</span>
            <a className={s.customerContactPhone} href={`tel:${detail.customer.phone}`}>
              📞 {detail.customer.phone}
            </a>
          </div>
        )}
        <div className={s.totals}>
          <div className={s.totalRow}>
            <span>Subtotal</span><span>AED {detail.subtotal}</span>
          </div>
          {!isOnPremise && (
            <div className={s.totalRow}>
              <span>Delivery</span><span>AED {detail.delivery_fee_aed}</span>
            </div>
          )}
          <div className={s.totalGrand}>
            <span>Total</span><span>AED {detail.total}</span>
          </div>
        </div>
        <div className={s.payRow}>
          <span className={s.payLabel}>Payment</span>
          {isOnPremise ? (
            detail.status === "delivered" ? (
              <span className={s.codBadge}>Paid</span>
            ) : (
              <span
                className={s.codBadge}
                style={{ background: "var(--sla-warn, #f79009)" }}
              >
                Unpaid
              </span>
            )
          ) : (
            <span className={s.codBadge}>COD</span>
          )}
        </div>
      </section>

      {!isOnPremise && (
        <section className={s.card}>
          <h4 className={s.cardTitle}>Delivery</h4>
          <div className={s.infoGrid}>
            {detail.address ? (
              <>
                <Field label="Receiver" value={detail.address.receiver_name ?? "—"} />
                <Field
                  label="Address"
                  value={
                    [detail.address.room_apartment, detail.address.building]
                      .filter(Boolean)
                      .join(", ") || "—"
                  }
                />
                {detail.address.additional_details && (
                  <Field label="Notes" value={detail.address.additional_details} />
                )}
              </>
            ) : (
              <p className={s.empty}>No address</p>
            )}
            <Field
              label="Rider"
              value={detail.rider ? `${detail.rider.name} · ${detail.rider.phone}` : "Unassigned"}
            />
          </div>
        </section>
      )}

      <ServiceRecord detail={detail} />

      {detail.dispatch_explain ? (
        <DispatchExplainSection
          explain={detail.dispatch_explain}
          batchPreviewLabel={detail.batch_preview_label}
          orderId={detail.id}
        />
      ) : null}
    </div>
  );
}

// ── Service record (A→Z) ─────────────────────────────────────────────────────

const TENDER_LABEL: Record<string, string> = {
  cash: "Cash",
  card: "Card",
  wallet: "Wallet",
  online: "Online",
  cod: "Cash on delivery",
  credit: "Store credit",
  voucher: "Voucher",
};

/** "7:14 AM" — the times a manager reconciles against, not ISO strings. */
function clock(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Gap between two stamps, e.g. "4 min" — blank when either is missing. */
function gap(fromIso?: string | null, toIso?: string | null): string | null {
  if (!fromIso || !toIso) return null;
  const ms = Date.parse(toIso) - Date.parse(fromIso);
  if (!Number.isFinite(ms) || ms < 0) return null;
  const mins = Math.round(ms / 60_000);
  if (mins < 1) return "<1 min";
  if (mins < 60) return `${mins} min`;
  return `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, "0")}m`;
}

type Step = {
  key: string;
  label: string;
  ts?: string | null;
  meta?: string | null;
  done: boolean;
  /** How many identical item-level rows this line collapses. */
  count?: number;
};

/** "cashier" → "Cashier". Audit actors are ROLES, which is what the log stores. */
const actorName = (a?: string | null) =>
  a ? a.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : null;

/**
 * Audit actions worth their own line on the journey. Everything else stays in
 * the collapsed trail — a manager needs to see interventions (voids, holds,
 * price changes, merges), not every internal state write.
 */
const JOURNEY_ACTIONS: Record<string, string> = {
  order_items_added: "Items added",
  order_item_edited: "Item edited",
  order_item_cancelled: "Item voided",
  order_modified: "Order modified",
  covers_changed: "Covers changed",
  held: "Order held",
  unheld: "Order resumed",
  recall: "Recalled from kitchen",
  priority_set: "Priority changed",
  order_merged: "Bill merged in",
  order_unmerged: "Merge undone",
  order_split_by_items: "Bill split",
  order_refunded: "Refunded",
  order_sla_acknowledged: "SLA breach acknowledged",
  order_staff_transferred: "Handed to another staff member",
  order_fired_to_kitchen: "Fired to kitchen",
  course_fired: "Course fired",
  // Kitchen-side, audited against the ITEM rather than the order.
  bump: "Item bumped by kitchen",
  missing_item_confirmed: "Missing item confirmed",
  scheduled_released: "Scheduled order released",
  resale_accepted: "Resale accepted",
  deleted: "Order deleted",
};

/**
 * The order's whole life on one card: who opened it, when the kitchen saw it,
 * when it was plated, how it was settled, and the raw audit trail underneath.
 * Every field comes from a real column — nothing here is inferred from status.
 */
function ServiceRecord({ detail }: { detail: OrderDetailOut }) {
  const payments = detail.payments ?? [];
  const settled = payments.filter((p) => p.status === "succeeded");
  const tips = settled.reduce((n, p) => n + Number(p.tip_aed || 0), 0);
  const paid = detail.paid_total_aed != null ? Number(detail.paid_total_aed) : null;
  const outstanding = paid != null ? Number(detail.total) - paid : null;
  const pending = detail.kitchen_pending_items ?? 0;
  const cancelled = detail.status === "cancelled" || !!detail.cancelled_at;
  const closedAt = cancelled ? detail.cancelled_at : detail.delivered_at;
  // The audit row that carried the order into its terminal state names the actor.
  const closingEvent = detail.timeline
    .filter((e) => {
      const st = e.after?.status;
      return typeof st === "string" && (st === "delivered" || st === "cancelled");
    })
    .at(-1);
  const closedBy = closingEvent?.actor_name ?? actorName(closingEvent?.actor);

  // Interventions — anything a manager or staff member DID to this order after
  // it was placed, interleaved with the milestones by time.
  // Item-level actions log one row PER LINE, so bumping a two-dish ticket
  // writes two identical rows a fraction of a second apart. Collapse a burst of
  // the same action by the same person into one line with a count — it was one
  // gesture, and printing it twice reads like a bug.
  const BURST_MS = 10_000;
  const interventions: Step[] = [];
  for (const e of detail.timeline) {
    const label = JOURNEY_ACTIONS[e.action];
    if (!label) continue;
    const who = e.actor_name ?? actorName(e.actor);
    const reason =
      typeof e.after?.reason === "string" && e.after.reason ? e.after.reason : null;
    const prev = interventions.at(-1);
    if (
      prev &&
      prev.key.startsWith(`audit-${e.action}-${who ?? ""}-`) &&
      Date.parse(e.ts) - Date.parse(prev.ts!) < BURST_MS
    ) {
      prev.count = (prev.count ?? 1) + 1;
      prev.label = `${label} ×${prev.count}`;
      prev.ts = e.ts;
      continue;
    }
    interventions.push({
      key: `audit-${e.action}-${who ?? ""}-${e.ts}`,
      label,
      ts: e.ts,
      meta: [who ? `by ${who}` : null, reason].filter(Boolean).join(" · "),
      done: true,
      count: 1,
    });
  }

  const milestones: Step[] = [
    {
      key: "placed",
      label: "Order placed",
      ts: detail.created_at,
      meta: detail.staff_name ? `by ${detail.staff_name}` : null,
      done: true,
    },
    {
      key: "kot",
      label: "Sent to kitchen (KOT)",
      ts: detail.kitchen_sent_at,
      meta: detail.kitchen_sent_at ? gap(detail.created_at, detail.kitchen_sent_at) : null,
      done: !!detail.kitchen_sent_at,
    },
    {
      key: "ready",
      label: "Kitchen ready",
      ts: detail.kitchen_ready_at,
      meta: detail.kitchen_ready_at
        ? [
            `cooked in ${gap(detail.kitchen_sent_at, detail.kitchen_ready_at) ?? "—"}`,
            detail.kitchen_ready_by ? `bumped by ${detail.kitchen_ready_by}` : null,
          ]
            .filter(Boolean)
            .join(" · ")
        : pending > 0
          ? `${pending} item${pending === 1 ? "" : "s"} still on the pass`
          : null,
      done: !!detail.kitchen_ready_at,
    },
    ...settled.map((p, i) => ({
      key: `pay-${p.id}`,
      label: `Paid — ${TENDER_LABEL[p.tender_type] ?? p.tender_type}`,
      ts: p.created_at,
      meta: `AED ${p.amount_aed}${Number(p.tip_aed) > 0 ? ` + ${p.tip_aed} tip` : ""}${
        settled.length > 1 ? ` · split ${i + 1}/${settled.length}` : ""
      } · ${p.channel}`,
      done: true,
    })),
    {
      key: "closed",
      label: cancelled ? "Cancelled" : "Order closed",
      ts: closedAt,
      // Who closed it comes from the audit row for that transition — the actor
      // is a ROLE (manager / cashier), which is what the audit log records.
      meta: closedAt
        ? [
            closedBy ? `by ${closedBy}` : null,
            detail.cancellation_reason || null,
            `open for ${gap(detail.created_at, closedAt)}`,
          ]
            .filter(Boolean)
            .join(" · ")
        : null,
      done: !!closedAt,
    },
  ];

  // One chronological rail: everything that happened, in the order it happened.
  // Steps still to come keep their canonical order at the bottom — but a
  // cancelled order has no future, so "Kitchen ready · pending" is dropped
  // rather than left dangling under the cancellation.
  const steps: Step[] = [
    ...[...milestones.filter((st) => st.done && st.ts), ...interventions].sort(
      (a, b) => Date.parse(a.ts!) - Date.parse(b.ts!),
    ),
    ...(cancelled ? [] : milestones.filter((st) => !st.done || !st.ts)),
  ];

  return (
    <section className={s.card}>
      <h4 className={s.cardTitle}>Service record</h4>

      <div className={s.infoGrid}>
        {detail.table_label && <Field label="Table" value={detail.table_label} />}
        {detail.covers != null && <Field label="Covers" value={String(detail.covers)} />}
        {detail.daily_token != null && (
          <Field label="Token" value={`#${detail.daily_token}`} />
        )}
        <Field label="Taken by" value={detail.staff_name ?? "—"} />
      </div>

      <ol className={s.journey}>
        {steps.map((st) => (
          <li
            key={st.key}
            className={`${s.journeyStep} ${st.done ? s.journeyDone : s.journeyPending}`}
          >
            <span className={s.journeyDot} aria-hidden="true" />
            <span className={s.journeyLabel}>{st.label}</span>
            <span className={s.journeyTime}>{st.done ? clock(st.ts) : "pending"}</span>
            {st.meta && <span className={s.journeyMeta}>{st.meta}</span>}
          </li>
        ))}
      </ol>

      {payments.length > 0 && (
        <div className={s.totals}>
          <div className={s.totalRow}>
            <span>Paid</span>
            <span>AED {paid?.toFixed(2) ?? "0.00"}</span>
          </div>
          {tips > 0 && (
            <div className={s.totalRow}>
              <span>Tips</span><span>AED {tips.toFixed(2)}</span>
            </div>
          )}
          {outstanding != null && Math.abs(outstanding) >= 0.01 && (
            <div className={s.totalRow}>
              <span>{outstanding > 0 ? "Outstanding" : "Change / overpaid"}</span>
              <span>AED {Math.abs(outstanding).toFixed(2)}</span>
            </div>
          )}
        </div>
      )}

      {detail.timeline.length > 0 && (
        <details className={s.auditWrap}>
          <summary className={s.auditSummary}>
            Full audit trail ({detail.timeline.length})
          </summary>
          <ul className={s.auditList}>
            {detail.timeline.map((e, i) => (
              <li key={i} className={s.auditRow}>
                <span className={s.auditTime}>{clock(e.ts)}</span>
                <span className={s.auditAction}>{timelineLabel(e)}</span>
                <span className={s.auditActor}>{e.actor_name ?? e.actor}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// ── Timeline Tab ──────────────────────────────────────────────────────────────

// Status-changing audit rows (order_status_transition, dispatch/delivery
// state_transition) all carry the new status in `after.status`. Surface it
// ("Status → Ready", "Status → Assigned") instead of a generic action label.
function timelineLabel(event: TimelineEventOut): string {
  const titleCase = (s: string) =>
    s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const status = event.after?.status;
  if (typeof status === "string" && status) {
    return `Status → ${titleCase(status)}`;
  }
  return titleCase(event.action);
}

function TimelineTab({ detail }: { detail: OrderDetailOut }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<import("leaflet").Map | null>(null);

  useEffect(() => {
    if (!mapRef.current || detail.route.length === 0) return;

    import("leaflet").then((L) => {
      // Remove any previous instance cleanly
      if (leafletMapRef.current) {
        leafletMapRef.current.remove();
        leafletMapRef.current = null;
      }

      const map = L.map(mapRef.current!, { zoomControl: true });
      leafletMapRef.current = map;

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap contributors",
      }).addTo(map);

      const coords: [number, number][] = detail.route.map((p) => [p.latitude, p.longitude]);
      const polyline = L.polyline(coords, { color: "#0ea5e9", weight: 3 }).addTo(map);
      map.fitBounds(polyline.getBounds(), { padding: [20, 20] });

      L.circleMarker(coords[0], {
        radius: 7,
        color: "#f59e0b",
        fillColor: "#f59e0b",
        fillOpacity: 1,
      })
        .bindTooltip("Pickup")
        .addTo(map);

      const last = coords[coords.length - 1];
      L.circleMarker(last, {
        radius: 7,
        color: "#22c55e",
        fillColor: "#22c55e",
        fillOpacity: 1,
      })
        .bindTooltip("Delivered")
        .addTo(map);
    });

    return () => {
      leafletMapRef.current?.remove();
      leafletMapRef.current = null;
    };
  }, [detail.route]);

  return (
    <div className={s.timeline}>
      <section className={s.card}>
        <h4 className={s.cardTitle}>Activity</h4>
        {detail.timeline.length === 0 ? (
          <p className={s.empty}>No timeline events</p>
        ) : (
          <ol className={s.timelineList}>
            {detail.timeline.map((event, i) => (
              <li
                key={i}
                className={`${s.timelineEvent} ${i === detail.timeline.length - 1 ? s.timelineLatest : ""}`}
              >
                <span className={s.timelineDot} />
                <div className={s.timelineBody}>
                  <span className={s.timelineAction}>{timelineLabel(event)}</span>
                  <span className={s.timelineMeta}>
                    {new Date(event.ts).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                      timeZone: "Asia/Dubai",
                    })}{" "}
                    · {event.actor}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {detail.route.length > 0 ? (
        <section className={s.card}>
          <h4 className={s.cardTitle}>Delivery Route</h4>
          <div ref={mapRef} className={s.map} />
        </section>
      ) : (
        detail.rider && (
          <section className={s.card}>
            <p className={s.empty}>No GPS pings recorded for this order</p>
          </section>
        )
      )}
    </div>
  );
}

// ── Chat Tab ──────────────────────────────────────────────────────────────────

function ChatTab({ detail }: { detail: OrderDetailOut }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "instant" });
  }, [detail.chat]);

  if (detail.chat.length === 0) {
    return <p className={s.empty}>No WhatsApp conversation found for this order</p>;
  }

  return (
    <div className={s.chatContainer}>
      {detail.chat.map((msg, i) => (
        <div
          key={i}
          className={`${s.bubble} ${msg.direction === "inbound" ? s.inbound : s.outbound}`}
        >
          <span className={s.bubbleText}>
            {msg.text ??
              (msg.direction === "inbound" ? "[📍 location / media]" : "[📤 automated]")}
          </span>
          <span className={s.bubbleTime}>
            {new Date(msg.ts * 1000).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
              timeZone: "Asia/Dubai",
            })}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

// ── Customer Tab ──────────────────────────────────────────────────────────────

function CustomerTab({
  detail,
  onCustomerSaved,
  onAddressSaved,
}: {
  detail: OrderDetailOut;
  onCustomerSaved: (c: CustomerDetailOut) => void;
  onAddressSaved: (a: AddressDetailOut) => void;
}) {
  const { customer, address } = detail;
  const [name, setName] = useState(customer.name ?? "");
  const [phone, setPhone] = useState(customer.phone);
  const [optIn, setOptIn] = useState(customer.marketing_opted_in);
  const [aptRoom, setAptRoom] = useState(address?.room_apartment ?? "");
  const [building, setBuilding] = useState(address?.building ?? "");
  const [receiverName, setReceiverName] = useState(address?.receiver_name ?? "");
  const [addrNotes, setAddrNotes] = useState(address?.additional_details ?? "");
  const [saving, setSaving] = useState(false);

  const dirty =
    name !== (customer.name ?? "") ||
    phone !== customer.phone ||
    optIn !== customer.marketing_opted_in ||
    aptRoom !== (address?.room_apartment ?? "") ||
    building !== (address?.building ?? "") ||
    receiverName !== (address?.receiver_name ?? "") ||
    addrNotes !== (address?.additional_details ?? "");

  async function save() {
    setSaving(true);
    try {
      const [updatedCustomer, updatedAddress] = await Promise.all([
        patchCustomer(customer.id, {
          name: name || null,
          phone: phone || null,
          marketing_opted_in: optIn,
        }),
        address
          ? patchAddress(customer.id, address.id, {
              room_apartment: aptRoom || null,
              building: building || null,
              receiver_name: receiverName || null,
              additional_details: addrNotes || null,
            })
          : Promise.resolve(null),
      ]);
      onCustomerSaved(updatedCustomer);
      if (updatedAddress) onAddressSaved(updatedAddress);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={s.customerTab}>
      <div className={s.statTiles}>
        <Stat label="Orders" value={String(customer.total_orders)} />
        <Stat label="Spend" value={`AED ${customer.total_spend}`} />
        <Stat
          label="First Order"
          value={
            customer.first_order_at
              ? new Date(customer.first_order_at).toLocaleDateString()
              : "—"
          }
        />
      </div>

      <Link to={`/customers/${customer.id}`} className={s.openProfile}>
        Open Full Profile →
      </Link>

      <section className={s.card}>
        <h4 className={s.cardTitle}>Identity</h4>
        <FormField label="Name">
          <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} />
        </FormField>
        <FormField label="Phone">
          <input className={s.input} value={phone} onChange={(e) => setPhone(e.target.value)} />
        </FormField>
        <div className={s.toggleRow}>
          <span className={s.formLabel}>Marketing (WhatsApp)</span>
          <button
            className={`${s.toggle} ${optIn ? s.toggleOn : s.toggleOff}`}
            onClick={() => setOptIn(!optIn)}
            aria-label={optIn ? "Opt out" : "Opt in"}
          >
            {optIn ? "OPT-IN" : "OPT-OUT"}
          </button>
        </div>
      </section>

      {address && (
        <section className={s.card}>
          <h4 className={s.cardTitle}>Address</h4>
          <FormField label="Apt / Room">
            <input className={s.input} value={aptRoom} onChange={(e) => setAptRoom(e.target.value)} />
          </FormField>
          <FormField label="Building">
            <input className={s.input} value={building} onChange={(e) => setBuilding(e.target.value)} />
          </FormField>
          <FormField label="Receiver Name">
            <input className={s.input} value={receiverName} onChange={(e) => setReceiverName(e.target.value)} />
          </FormField>
          <FormField label="Notes">
            <input className={s.input} value={addrNotes} onChange={(e) => setAddrNotes(e.target.value)} />
          </FormField>
        </section>
      )}

      <div className={s.saveRow}>
        <Button onClick={save} disabled={!dirty || saving}>
          {saving ? "Saving…" : "Save Changes"}
        </Button>
      </div>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={s.formField}>
      <label className={s.formLabel}>{label}</label>
      {children}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.field}>
      <span className={s.fieldLabel}>{label}</span>
      <span className={s.val}>{value}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.stat}>
      <span className={s.statValue}>{value}</span>
      <span className={s.statLabel}>{label}</span>
    </div>
  );
}
