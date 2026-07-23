import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApprovalPinModal } from "../components/ApprovalPinModal";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button, TouchButton } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CountdownTimer } from "../components/CountdownTimer";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { MoneySummary } from "../components/MoneySummary";
import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import {
  DETAIL_INCLUDE_BY_TAB,
  fetchOrderDetail,
  orderOutFromDetail,
} from "../lib/orderDetailApi";
import { cancelOrder, setOrderPriority } from "../lib/ordersApi";
import { listOrderPayments } from "../lib/paymentsApi";
import { isWaiterRole } from "../lib/navAccess";
import { submitManagerPin } from "../lib/staffApi";
import type { OrderDetailOut, OrderOut, TimelineEventOut } from "../lib/types";
import s from "./OrderDetailScreen.module.css";

const ACTIVE_SLA = new Set([
  "pending_confirmation",
  "confirmed",
  "preparing",
  "ready",
  "assigned",
  "picked_up",
  "arriving",
]);

const KITCHEN_ADVANCEABLE = new Set(["confirmed", "preparing"]);
const ADVANCE_LABEL: Record<string, string> = {
  confirmed: "Start Preparing",
  preparing: "Mark as Ready",
};
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
const PAYABLE = new Set([
  "draft",
  "pending_confirmation",
  "confirmed",
  "preparing",
  "ready",
  "assigned",
  "picked_up",
  "arriving",
  "delivered",
]);

function timelineLabel(event: TimelineEventOut): string {
  const titleCase = (str: string) =>
    str.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const status = event.after?.status;
  if (typeof status === "string" && status) {
    return `Status → ${titleCase(status)}`;
  }
  return titleCase(event.action);
}

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString([], {
      hour: "2-digit",
      minute: "2-digit",
      day: "numeric",
      month: "short",
      timeZone: "Asia/Dubai",
    });
  } catch {
    return iso;
  }
}

export function OrderDetailScreen() {
  const { id: idParam } = useParams<{ id: string }>();
  const orderId = Number(idParam);
  const navigate = useNavigate();
  const waiterMode = isWaiterRole();

  const [detail, setDetail] = useState<OrderDetailOut | null>(null);
  const [basic, setBasic] = useState<OrderOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [advancing, setAdvancing] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [voidPinOpen, setVoidPinOpen] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [paidAed, setPaidAed] = useState<string | null>(null);

  async function load() {
    if (!Number.isFinite(orderId) || orderId <= 0) {
      setError("Invalid order id");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const d = await fetchOrderDetail(orderId, {
        include: DETAIL_INCLUDE_BY_TAB.timeline,
      });
      setDetail(d);
      setBasic(orderOutFromDetail(d));
      try {
        const pay = await listOrderPayments(orderId);
        setPaidAed(pay.total_paid_aed ?? "0.00");
      } catch {
        setPaidAed(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load order");
      setDetail(null);
      setBasic(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when route id changes
  }, [orderId]);

  const channel = useMemo(() => {
    if (!basic) return "—";
    return (
      basic.source_channel ||
      basic.aggregator_source ||
      basic.order_type ||
      "POS / WhatsApp"
    );
  }, [basic]);

  // On-premise (dine-in / takeaway / drive-thru) orders have NO rider, NO
  // delivery address, and the cashier doesn't drive the kitchen FSM — so we hide
  // all of that and show table + add-items + bill/pay instead.
  const isOnPremise = useMemo(() => {
    const t = String(basic?.order_type ?? "");
    return t === "dine_in" || t === "takeaway" || t === "drive_thru";
  }, [basic]);
  const isDineIn = String(basic?.order_type ?? "") === "dine_in";

  async function advanceStatus() {
    if (!basic) return;
    setAdvancing(true);
    setActionError(null);
    try {
      const updated = await apiClient.post<OrderOut>(`/api/v1/orders/${basic.id}/advance`);
      setBasic(updated);
      await load();
      toast("Order advanced");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Advance failed");
    } finally {
      setAdvancing(false);
    }
  }

  async function markPriority() {
    if (!basic) return;
    setActionError(null);
    try {
      const updated = await setOrderPriority(basic.id, "priority");
      setBasic(updated);
      toast("Marked priority");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Priority failed");
    }
  }

  async function voidWithPin(payload: { pin: string; reason: string }) {
    if (!basic) return;
    await submitManagerPin({
      pin: payload.pin,
      action_type: "void",
      order_id: basic.id,
      amount_aed: basic.total_aed,
      reason: payload.reason,
    });
    setCancelling(true);
    try {
      const updated = await cancelOrder(basic.id, payload.reason || "void");
      setBasic(updated);
      setVoidPinOpen(false);
      setConfirmCancel(false);
      toast("Order voided");
      await load();
    } finally {
      setCancelling(false);
    }
  }

  if (!Number.isFinite(orderId) || orderId <= 0) {
    return (
      <ErrorState
        title="Invalid order"
        description="Order id must be a positive number."
        action={
          <Link to="/orders">
            <Button>Back to orders</Button>
          </Link>
        }
      />
    );
  }

  if (loading && !detail) {
    return (
      <div className={s.root} data-testid="order-detail-screen">
        <PageHeader title="Order Detail" />
        <EmptyState title="Loading order…" description={`Fetching #${orderId}`} />
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className={s.root} data-testid="order-detail-screen">
        <PageHeader title="Order Detail" />
        <ErrorState
          title="Could not load order"
          description={error}
          action={
            <Button type="button" onClick={() => void load()}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  if (!detail || !basic) {
    return (
      <div className={s.root} data-testid="order-detail-screen">
        <EmptyState title="Order not found" />
      </div>
    );
  }

  const addr = detail.address
    ? [detail.address.room_apartment, detail.address.building].filter(Boolean).join(", ")
    : null;

  return (
    <div className={s.root} data-testid="order-detail-screen">
      <PageHeader
        title={`Order ${detail.order_number || `#${detail.id}`}`}
        subtitle="Full order page · timeline · kitchen · payment"
        right={
          <Link to="/orders">
            <Button variant="ghost" size="lg">
              All orders
            </Button>
          </Link>
        }
      />

      <div className={s.header}>
        <h2 className={s.orderTitle}>{detail.order_number || `#${detail.id}`}</h2>
        <div className={s.metaChips}>
          <StatusPill status={detail.status} orderType={basic.order_type} />
          <span className={s.chip}>{channel}</span>
          {ACTIVE_SLA.has(detail.status) && (
            <CountdownTimer slaStartedAt={basic.sla_started_at} />
          )}
          <span className={s.chip}>
            Paid: {paidAed != null ? `AED ${paidAed}` : "—"}
          </span>
        </div>
      </div>

      {actionError && (
        <p className={s.error} role="alert">
          {actionError}
        </p>
      )}

      <div className={s.layout}>
        <section className={s.card} aria-label="Customer and delivery">
          <h3 className={s.cardTitle}>
            {isOnPremise ? "Customer / table" : "Customer / delivery"}
          </h3>
          {detail.customer.allergy_notes && (
            <div className={s.allergy} data-testid="allergy-warning">
              Allergy: {detail.customer.allergy_notes}
            </div>
          )}
          <div className={s.field}>
            <span className={s.fieldLabel}>Name</span>
            <span className={s.fieldValue}>{detail.customer.name || "—"}</span>
          </div>
          <div className={s.field}>
            <span className={s.fieldLabel}>Phone</span>
            <span className={s.fieldValue}>
              <a href={`tel:${detail.customer.phone}`}>{detail.customer.phone}</a>
            </span>
          </div>
          {isDineIn ? (
            <div className={s.field}>
              <span className={s.fieldLabel}>Table</span>
              <span className={s.fieldValue}>
                {basic.table_id ? `Table #${basic.table_id}` : "—"}
              </span>
            </div>
          ) : (
            <div className={s.field}>
              <span className={s.fieldLabel}>Address</span>
              <span className={s.fieldValue}>{addr || "—"}</span>
            </div>
          )}
          <div className={s.field}>
            <span className={s.fieldLabel}>Notes</span>
            <span className={s.fieldValue}>{detail.customer.notes || "—"}</span>
          </div>
          {!isOnPremise && (
            <div className={s.field}>
              <span className={s.fieldLabel}>Rider</span>
              <span className={s.fieldValue}>
                {detail.rider
                  ? `${detail.rider.name} · ${detail.rider.phone}`
                  : "Unassigned"}
              </span>
            </div>
          )}
        </section>

        <section className={s.card} aria-label="Order items">
          <h3 className={s.cardTitle}>Items</h3>
          <div className={s.items}>
            {detail.items.map((item, i) => (
              <div key={i} className={s.itemRow}>
                <span className={s.itemQty}>{item.qty}×</span>
                <span className={s.itemName}>
                  {item.dish_name}
                  {item.variant_name ? ` (${item.variant_name})` : ""}
                  {item.notes ? <span className={s.itemNote}>📝 {item.notes}</span> : null}
                </span>
                <span className={s.itemPrice}>AED {item.line_total}</span>
              </div>
            ))}
          </div>
          <div className={s.totals}>
            <div className={s.totalRow}>
              <span>Subtotal</span>
              <span>AED {detail.subtotal}</span>
            </div>
            {!isOnPremise && (
              <div className={s.totalRow}>
                <span>Delivery</span>
                <span>AED {detail.delivery_fee_aed}</span>
              </div>
            )}
            <div className={s.totalGrand}>
              <span>Total</span>
              <span>AED {detail.total}</span>
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <MoneySummary label="Amount due" amount={detail.total} size="md" />
          </div>
        </section>

        <section className={s.card} aria-label="Timeline and kitchen">
          <h3 className={s.cardTitle}>Timeline</h3>
          {detail.timeline?.length ? (
            <ul className={s.timeline}>
              {detail.timeline.map((ev, i) => (
                <li key={i} className={s.timelineItem}>
                  <span className={s.dot} aria-hidden />
                  <div>
                    <div className={s.tlAction}>{timelineLabel(ev)}</div>
                    <div className={s.tlMeta}>
                      {ev.actor || "system"} · {formatTs(ev.ts)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className={s.emptyMuted}>No timeline events yet.</p>
          )}
          <h3 className={s.cardTitle} style={{ marginTop: 20 }}>
            {isOnPremise ? "Order status" : "Kitchen / rider"}
          </h3>
          <div className={s.field}>
            <span className={s.fieldLabel}>Status</span>
            <span className={s.fieldValue}>{detail.status}</span>
          </div>
          {!isOnPremise && (
            <div className={s.field}>
              <span className={s.fieldLabel}>Prep deadline</span>
              <span className={s.fieldValue}>
                {detail.prep_deadline ? formatTs(detail.prep_deadline) : "—"}
              </span>
            </div>
          )}
          <div className={s.field}>
            <span className={s.fieldLabel}>Priority</span>
            <span className={s.fieldValue}>{basic.priority || "normal"}</span>
          </div>
        </section>
      </div>

      <BottomActionBar>
        {/* Dine-in: add another round to this tab (table stays reserved). */}
        {isDineIn && CANCELLABLE.has(detail.status) && (
          <TouchButton
            type="button"
            data-testid="order-detail-add-items"
            onClick={() =>
              navigate(basic.table_id ? `/new-order?table=${basic.table_id}` : "/new-order")
            }
          >
            + Add items
          </TouchButton>
        )}
        {/* Kitchen advance is delivery/kitchen-driven — hidden for on-premise. */}
        {KITCHEN_ADVANCEABLE.has(detail.status) && !waiterMode && !isOnPremise && (
          <TouchButton type="button" onClick={() => void advanceStatus()} disabled={advancing}>
            {advancing ? "Saving…" : ADVANCE_LABEL[detail.status] || "Advance"}
          </TouchButton>
        )}
        {PAYABLE.has(detail.status) && !waiterMode && (
          <Link to={`/orders/${detail.id}/pay`}>
            <TouchButton type="button" data-testid="order-detail-pay">
              {isOnPremise ? "Bill & Pay" : "Pay"}
            </TouchButton>
          </Link>
        )}
        {waiterMode && PAYABLE.has(detail.status) && (
          <Button type="button" variant="ghost" size="lg" disabled title="Payment is handled at cashier">
            Bill at cashier
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="lg"
          onClick={() => navigate(`/new-order?reorder=${detail.id}`)}
        >
          {waiterMode ? "Edit items / qty / notes" : "Edit / re-order"}
        </Button>
        {!isOnPremise && (
          <Button type="button" variant="ghost" size="lg" onClick={() => void markPriority()}>
            Rush / Priority
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="lg"
          onClick={() => toast("Receipt sent to printer (when configured).")}
        >
          Print
        </Button>
        <div className={s.moreMenu}>
          <Button
            type="button"
            variant="ghost"
            size="lg"
            aria-expanded={showMore}
            onClick={() => setShowMore((v) => !v)}
          >
            More
          </Button>
          {showMore && (
            <div className={s.morePanel} role="menu">
              {!waiterMode && (
                <button
                  type="button"
                  className={`${s.moreBtn} ${s.moreDanger}`}
                  role="menuitem"
                  disabled={!CANCELLABLE.has(detail.status)}
                  onClick={() => {
                    setShowMore(false);
                    setConfirmCancel(true);
                  }}
                >
                  Void order…
                </button>
              )}
              {waiterMode && (
                <button type="button" className={s.moreBtn} role="menuitem" disabled>
                  Void — ask manager (PIN)
                </button>
              )}
              {!waiterMode && !isOnPremise && (
                <button
                  type="button"
                  className={s.moreBtn}
                  role="menuitem"
                  onClick={() => {
                    setShowMore(false);
                    navigate(`/orders`);
                  }}
                >
                  Assign rider (list)
                </button>
              )}
            </div>
          )}
        </div>
      </BottomActionBar>

      {confirmCancel && (
        <ConfirmDialog
          title="Void this order?"
          message="Void requires manager PIN. This cannot be undone and notifies the customer when configured."
          confirmLabel="Continue to PIN"
          cancelLabel="Keep order"
          danger
          busy={cancelling}
          onCancel={() => setConfirmCancel(false)}
          onConfirm={() => {
            setConfirmCancel(false);
            setVoidPinOpen(true);
          }}
        />
      )}

      <ApprovalPinModal
        open={voidPinOpen}
        actionLabel="Void order"
        recordLabel={detail.order_number || String(detail.id)}
        reasonRequired
        onCancel={() => setVoidPinOpen(false)}
        onApprove={voidWithPin}
      />
    </div>
  );
}
