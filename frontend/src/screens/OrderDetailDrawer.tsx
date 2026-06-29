import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { SideDrawer } from "../components/SideDrawer";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CountdownTimer } from "../components/CountdownTimer";
import { PrepCountdown } from "../components/PrepCountdown";
import { apiClient } from "../lib/apiClient";
import { fetchOrderDetail, patchAddress, patchCustomer } from "../lib/orderDetailApi";
import { cancelOrder, fetchOrder, reassignOrder } from "../lib/ordersApi";
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

// The SLA clock only counts down while the order is in flight. For delivered
// or other terminal states the timer is meaningless (it would freeze at 00:00).
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
// Cancellation is only legal before the order leaves the kitchen (FSM): pre-cook
// states transition to "cancelled"; "preparing" (already cooking) goes to
// "on_resale" so the food is auto-resold. Ready/assigned/out-for-delivery and
// terminal states are not cancellable — the button is hidden for them.
const CANCELLABLE = new Set([
  "draft",
  "pending_confirmation",
  "confirmed",
  "preparing",
]);

export function OrderDetailDrawer({
  orderId,
  onClose,
}: {
  orderId: number | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<OrderDetailOut | null>(null);
  const [basicOrder, setBasicOrder] = useState<OrderOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [advancing, setAdvancing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [riders, setRiders] = useState<RiderOut[]>([]);
  const [reassignTo, setReassignTo] = useState<number | "">("");
  const [reassigning, setReassigning] = useState(false);

  useEffect(() => {
    if (orderId === null) {
      setDetail(null);
      setBasicOrder(null);
      return;
    }
    setLoading(true);
    setTab("overview");
    setError(null);
    setReassignTo("");
    Promise.all([fetchOrderDetail(orderId), fetchOrder(orderId)])
      .then(([d, b]) => {
        setDetail(d);
        setBasicOrder(b);
        // Riders are only needed for the reassign control on an assigned order.
        if (d.status === "assigned") {
          fetchRiders().then(setRiders).catch(() => setRiders([]));
        }
      })
      .catch(() => setError("Failed to load order details"))
      .finally(() => setLoading(false));
  }, [orderId]);

  async function reassignAction() {
    if (!basicOrder || reassignTo === "") return;
    setReassigning(true);
    setActionError(null);
    try {
      const updated = await reassignOrder(basicOrder.id, Number(reassignTo));
      setBasicOrder(updated);
      setDetail(await fetchOrderDetail(basicOrder.id));
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
      const d = await fetchOrderDetail(basicOrder.id);
      setDetail(d);
    } finally {
      setAdvancing(false);
    }
  }

  async function cancelOrderAction() {
    if (!basicOrder) return;
    setCancelling(true);
    setActionError(null);
    try {
      const updated = await cancelOrder(basicOrder.id);
      setBasicOrder(updated);
      const d = await fetchOrderDetail(basicOrder.id);
      setDetail(d);
      setConfirmCancel(false);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to cancel order");
    } finally {
      setCancelling(false);
    }
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

  return (
    <SideDrawer open={orderId !== null} title={title} onClose={onClose} wide>
      {loading || !detail || !basicOrder ? (
        error ? <p style={{ color: "var(--text-secondary)", padding: "16px" }}>{error}</p> : <DrawerSkeleton />
      ) : (
        <div className={s.detail}>
          <div className={s.head}>
            <StatusPill status={detail.status} />
            {ACTIVE_SLA.has(detail.status) ? (
              <CountdownTimer slaStartedAt={basicOrder.sla_started_at} />
            ) : detail.status === "delivered" && detail.delivered_at ? (
              <span className={s.deliveredStamp}>
                ✓ Delivered{" "}
                {new Date(detail.delivered_at).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Asia/Dubai",
                })}
              </span>
            ) : null}
          </div>

          {(detail.status === "confirmed" || detail.status === "preparing") &&
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

          {(KITCHEN_ADVANCEABLE.has(detail.status) || CANCELLABLE.has(detail.status)) && (
            <div className={s.actionBar}>
              {KITCHEN_ADVANCEABLE.has(detail.status) && (
                <Button onClick={advanceStatus} disabled={advancing || cancelling}>
                  {advancing ? "Saving…" : ADVANCE_LABEL[detail.status]}
                </Button>
              )}
              {CANCELLABLE.has(detail.status) && (
                <Button
                  variant="danger"
                  onClick={() => { setActionError(null); setConfirmCancel(true); }}
                  disabled={advancing || cancelling}
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
              {actionError && (
                <span style={{ color: "var(--danger, #dc2626)", fontSize: "13px" }}>
                  {actionError}
                </span>
              )}
            </div>
          )}

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
      {confirmCancel && (
        <ConfirmDialog
          title="Cancel this order?"
          message={
            detail?.status === "preparing"
              ? "It's already being cooked, so the food will be put up for auto-resale. This cannot be undone."
              : "This cannot be undone."
          }
          confirmLabel="Cancel order"
          cancelLabel="Keep order"
          danger
          busy={cancelling}
          onConfirm={cancelOrderAction}
          onCancel={() => setConfirmCancel(false)}
        />
      )}
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
  return (
    <div className={s.overview}>
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
          <div className={s.totalRow}>
            <span>Delivery</span><span>AED {detail.delivery_fee_aed}</span>
          </div>
          <div className={s.totalGrand}>
            <span>Total</span><span>AED {detail.total}</span>
          </div>
        </div>
        <div className={s.payRow}>
          <span className={s.payLabel}>Payment</span>
          <span className={s.codBadge}>COD</span>
        </div>
      </section>

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
    </div>
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
