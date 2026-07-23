import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { RiderCard } from "../components/RiderCard";
import { RiderAddModal } from "../components/RiderAddModal";
import { AppInviteModal } from "../components/AppInviteModal";
import { BottomActionBar } from "../components/BottomActionBar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LiveOpsMap } from "../components/LiveOpsMap";
import { PageHeader } from "../components/PageHeader";
import { Button, TouchButton } from "../components/Button";
import { toast } from "../components/Toaster";
import { ApiError, apiClient } from "../lib/apiClient";
import { assignOrder } from "../lib/ordersApi";
import { useLiveOpsOrdersQuery, useRidersQuery } from "../lib/queries/dashboard";
import { reconcileRiderCod } from "../lib/dispatchApi";
import { deleteRider, setRiderDuty, setRiderStatus } from "../lib/ridersApi";
import {
  formatCountdown,
  remainingMs,
  slaTier,
  type SlaTier,
} from "../lib/sla";
import type { OrderOut, RestaurantOut, RiderOut, RiderStatus } from "../lib/types";
import s from "./RidersScreen.module.css";

type RemoveFlow =
  | { step: "confirm"; id: number; name: string }
  | { step: "deactivate-instead"; id: number; name: string };

const DISPATCHABLE: OrderOut["status"][] = ["confirmed", "preparing", "ready"];

function queueTierClass(tier: SlaTier): string {
  if (tier === "breach") return s.queueCardBreach;
  if (tier === "critical") return s.queueCardCritical;
  if (tier === "warn") return s.queueCardWarn;
  return s.queueCardSafe;
}

function slaTextClass(tier: SlaTier): string {
  if (tier === "breach") return s.queueSlaBreach;
  if (tier === "critical") return s.queueSlaCritical;
  if (tier === "warn") return s.queueSlaWarn;
  return "";
}

export function RidersScreen() {
  const queryClient = useQueryClient();
  const { data: riders = [], isLoading } = useRidersQuery();
  const { data: orders = [] } = useLiveOpsOrdersQuery();
  const loaded = !isLoading || riders.length > 0;

  function patchRiders(patch: (rs: RiderOut[]) => RiderOut[]) {
    queryClient.setQueryData<RiderOut[]>(["riders", "list"], (prev) => patch(prev ?? []));
  }

  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<RiderOut | null>(null);
  const [inviteFor, setInviteFor] = useState<RiderOut | null>(null);
  const [restaurantPhone, setRestaurantPhone] = useState<string | null>(null);
  const [removeFlow, setRemoveFlow] = useState<RemoveFlow | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [settleBusy, setSettleBusy] = useState<number | null>(null);
  const [assignBusy, setAssignBusy] = useState(false);
  const [selectedOrderId, setSelectedOrderId] = useState<number | null>(null);
  const [selectedRiderId, setSelectedRiderId] = useState<number | null>(null);
  const [, forceTick] = useState(0);

  useEffect(() => {
    const t = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    apiClient
      .get<RestaurantOut>("/api/v1/me")
      .then((me) => setRestaurantPhone(me.phone))
      .catch(() => {});
  }, []);

  const counts = useMemo(() => {
    const c = { available: 0, on_delivery: 0, off_shift: 0, deactivated: 0 };
    for (const r of riders) c[r.status]++;
    return c;
  }, [riders]);

  const unassignedQueue = useMemo(() => {
    return orders
      .filter((o) => DISPATCHABLE.includes(o.status) && o.rider_id == null)
      .slice()
      .sort((a, b) => remainingMs(a.sla_started_at) - remainingMs(b.sla_started_at));
  }, [orders]);

  const lateRiskCount = useMemo(() => {
    return unassignedQueue.filter((o) => {
      const tier = slaTier(o.sla_started_at);
      return tier === "warn" || tier === "critical" || tier === "breach";
    }).length;
  }, [unassignedQueue]);

  const activeDeliveries = useMemo(
    () => orders.filter((o) => o.rider_id != null && ["assigned", "picked_up", "arriving"].includes(o.status)).length,
    [orders],
  );

  const selectedOrder = unassignedQueue.find((o) => o.id === selectedOrderId) ?? null;
  const selectedRider = riders.find((r) => r.id === selectedRiderId) ?? null;
  const canAssign =
    selectedOrder != null &&
    selectedRider != null &&
    selectedRider.status === "available" &&
    selectedRider.on_duty !== false;

  async function onStatusChange(id: number, status: RiderStatus) {
    const updated = await setRiderStatus(id, status);
    patchRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  async function onDutyChange(id: number, on_duty: boolean) {
    const updated = await setRiderDuty(id, on_duty);
    patchRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  function onInviteApp(id: number) {
    const rider = riders.find((r) => r.id === id);
    if (rider) setInviteFor(rider);
  }

  function onDelete(id: number) {
    const rider = riders.find((r) => r.id === id);
    if (!rider) return;
    setRemoveFlow({ step: "confirm", id, name: rider.name });
  }

  async function onSettleCod(id: number) {
    setSettleBusy(id);
    try {
      const rec = await reconcileRiderCod(id);
      toast(
        `COD settle ${rec.status}: expected ${rec.expected_total_aed}, collected ${rec.collected_total_aed}, variance ${rec.variance_aed}`,
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "COD settle failed", "error");
    } finally {
      setSettleBusy(null);
    }
  }

  async function onManualAssign() {
    if (!canAssign || !selectedOrder || !selectedRider) return;
    setAssignBusy(true);
    try {
      await assignOrder(selectedOrder.id, selectedRider.id);
      toast(`Assigned #${selectedOrder.order_number ?? selectedOrder.id} → ${selectedRider.name}`);
      setSelectedOrderId(null);
      await queryClient.invalidateQueries({ queryKey: ["orders"] });
      await queryClient.invalidateQueries({ queryKey: ["riders"] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Assign failed", "error");
    } finally {
      setAssignBusy(false);
    }
  }

  async function confirmRemove() {
    if (!removeFlow || removeFlow.step !== "confirm") return;
    const { id, name } = removeFlow;
    setRemoveBusy(true);
    try {
      await deleteRider(id);
      patchRiders((rs) => rs.filter((r) => r.id !== id));
      toast(`${name} removed.`);
      setRemoveFlow(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setRemoveFlow({ step: "deactivate-instead", id, name });
      } else {
        toast(e instanceof Error ? e.message : "Could not remove this rider.", "error");
        setRemoveFlow(null);
      }
    } finally {
      setRemoveBusy(false);
    }
  }

  async function confirmDeactivateInstead() {
    if (!removeFlow || removeFlow.step !== "deactivate-instead") return;
    const { id, name } = removeFlow;
    setRemoveBusy(true);
    try {
      const updated = await setRiderStatus(id, "deactivated");
      patchRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
      toast(`${name} deactivated. Payment records stay on file.`);
      setRemoveFlow(null);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not deactivate this rider.", "error");
      setRemoveFlow(null);
    } finally {
      setRemoveBusy(false);
    }
  }

  return (
    <div className={s.root} data-testid="riders-screen">
      <PageHeader
        title="Rider Dispatch"
        subtitle="Queue · map · fleet — assign before SLA risk turns late"
        right={<Button onClick={() => setShowAdd(true)}>+ Add Rider</Button>}
      />

      {(riders.length > 0 || unassignedQueue.length > 0) && (
        <div className={s.stats} data-testid="riders-stats">
          <span className={s.stat}>
            <span className={s.statNum}>{riders.length}</span> riders
          </span>
          <span className={s.statDivider} />
          <span className={s.stat}>
            <span className={s.statDot} style={{ background: "var(--sla-safe)" }} /> {counts.available}{" "}
            available
          </span>
          <span className={s.stat}>
            <span className={s.statDot} style={{ background: "var(--accent-rider)" }} />{" "}
            {counts.on_delivery} on delivery
          </span>
          <span className={s.stat}>
            <span className={s.statDot} style={{ background: "var(--accent-dispatch)" }} />{" "}
            {activeDeliveries} active runs
          </span>
          <span className={s.stat}>
            <span className={s.statDot} style={{ background: "var(--text-muted)" }} /> {counts.off_shift}{" "}
            off shift
          </span>
          {counts.deactivated > 0 && (
            <span className={s.stat}>
              <span className={s.statDot} style={{ background: "var(--sla-critical)" }} />{" "}
              {counts.deactivated} deactivated
            </span>
          )}
          <span
            className={`${s.statRisk} ${lateRiskCount > 0 ? s.statRiskCritical : ""}`}
            data-testid="riders-late-risk"
          >
            {lateRiskCount > 0
              ? `${lateRiskCount} late risk in queue`
              : "No late risk in queue"}
          </span>
        </div>
      )}

      {!loaded && <RidersSkeleton />}

      {loaded && riders.length === 0 && unassignedQueue.length === 0 && (
        <div className={s.empty}>No riders yet — click "+ Add Rider" to register your first rider.</div>
      )}

      {loaded && (riders.length > 0 || unassignedQueue.length > 0) && (
        <div className={s.ops} data-testid="riders-ops-layout">
          <aside className={s.pane} aria-label="Unassigned dispatch queue">
            <div className={s.paneHead}>
              <span>Unassigned</span>
              <span className={s.paneSub}>{unassignedQueue.length}</span>
            </div>
            <div className={s.queue}>
              {unassignedQueue.length === 0 ? (
                <div className={s.empty}>No orders waiting for a rider</div>
              ) : (
                unassignedQueue.map((o) => {
                  const tier = slaTier(o.sla_started_at);
                  const rem = remainingMs(o.sla_started_at);
                  return (
                    <button
                      key={o.id}
                      type="button"
                      className={`${s.queueCard} ${queueTierClass(tier)} ${
                        selectedOrderId === o.id ? s.queueCardSelected : ""
                      }`}
                      onClick={() =>
                        setSelectedOrderId((prev) => (prev === o.id ? null : o.id))
                      }
                      data-testid={`dispatch-queue-${o.id}`}
                    >
                      <div className={s.queueTop}>
                        <span className={s.queueOrder}>#{o.order_number ?? o.id}</span>
                        <span className={`${s.queueSla} ${slaTextClass(tier)}`}>
                          {rem <= 0 ? "LATE" : formatCountdown(rem)}
                        </span>
                      </div>
                      <div className={s.queueMeta}>
                        {o.customer_name} · AED {o.total_aed}
                      </div>
                      <div className={s.queueStatus}>{o.status.replace(/_/g, " ")}</div>
                    </button>
                  );
                })
              )}
            </div>
          </aside>

          <section className={`${s.pane} ${s.mapPane}`} aria-label="Dispatch map">
            <LiveOpsMap fillHeight />
          </section>

          <aside className={s.pane} aria-label="Fleet">
            <div className={s.paneHead}>
              <span>Fleet</span>
              <span className={s.paneSub}>{counts.available} free</span>
            </div>
            <div className={s.fleet}>
              {riders.length === 0 ? (
                <div className={s.empty}>No riders registered</div>
              ) : (
                riders.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    className={`${s.fleetItem} ${
                      selectedRiderId === r.id ? s.fleetItemSelected : ""
                    }`}
                    onClick={() =>
                      setSelectedRiderId((prev) => (prev === r.id ? null : r.id))
                    }
                    data-testid={`fleet-rider-${r.id}`}
                  >
                    <span className={s.fleetName}>{r.name}</span>
                    <span className={s.fleetMeta}>{r.phone}</span>
                    <span className={s.fleetStatus}>
                      {r.status.replace(/_/g, " ")}
                      {r.on_duty === false ? " · off duty" : ""}
                      {r.status === "on_delivery" ? ` · ${r.delivered_24h} today` : ""}
                    </span>
                  </button>
                ))
              )}
            </div>
          </aside>
        </div>
      )}

      {selectedRider && (
        <div className={s.detail} data-testid="riders-selected-detail">
          <div className={s.grid}>
            <RiderCard
              key={selectedRider.id}
              rider={selectedRider}
              onStatusChange={onStatusChange}
              onDutyChange={onDutyChange}
              onDelete={onDelete}
              onEdit={setEditing}
              onInviteApp={onInviteApp}
              onSettleCod={onSettleCod}
              settleBusy={settleBusy === selectedRider.id}
            />
          </div>
        </div>
      )}

      {!selectedRider && loaded && riders.length > 0 && (
        <div className={s.detail}>
          <div className={s.grid} style={{ gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))" }}>
            {riders.map((r) => (
              <RiderCard
                key={r.id}
                rider={r}
                onStatusChange={onStatusChange}
                onDutyChange={onDutyChange}
                onDelete={onDelete}
                onEdit={setEditing}
                onInviteApp={onInviteApp}
                onSettleCod={onSettleCod}
                settleBusy={settleBusy === r.id}
              />
            ))}
          </div>
        </div>
      )}

      <BottomActionBar>
        <span className={s.barHint} data-testid="riders-assign-hint">
          {canAssign ? (
            <>
              Assign{" "}
              <span className={s.barHintStrong}>
                #{selectedOrder?.order_number ?? selectedOrder?.id}
              </span>{" "}
              → <span className={s.barHintStrong}>{selectedRider?.name}</span>
            </>
          ) : selectedOrder && selectedRider ? (
            "Selected rider cannot take new orders (status / duty)"
          ) : (
            "Select an unassigned order and an available rider"
          )}
        </span>
        <TouchButton
          onClick={onManualAssign}
          disabled={!canAssign || assignBusy}
          data-testid="riders-manual-assign"
        >
          {assignBusy ? "Assigning…" : "Manual Assign"}
        </TouchButton>
        {/* Settle COD lives on the rider CARD, not here: the bar copy needed a
            rider selected first, so it sat greyed out next to an identical
            always-live button and left "which one do I press?" unanswered. The
            card version also makes the rider it applies to unmistakable. */}
        <Button variant="ghost" size="touch" onClick={() => setShowAdd(true)}>
          + Add Rider
        </Button>
      </BottomActionBar>

      {showAdd && (
        <RiderAddModal
          onClose={() => setShowAdd(false)}
          onSaved={(rider) => patchRiders((rs) => [...rs, rider])}
        />
      )}

      {editing && (
        <RiderAddModal
          rider={editing}
          onClose={() => setEditing(null)}
          onSaved={(rider) =>
            patchRiders((rs) => rs.map((r) => (r.id === rider.id ? rider : r)))
          }
        />
      )}

      {inviteFor && (
        <AppInviteModal
          rider={inviteFor}
          restaurantPhone={restaurantPhone}
          onClose={() => setInviteFor(null)}
        />
      )}

      {removeFlow?.step === "confirm" && (
        <ConfirmDialog
          title={`Remove ${removeFlow.name}?`}
          message="This permanently deletes the rider account. It cannot be undone."
          confirmLabel="Remove rider"
          cancelLabel="Keep rider"
          danger
          busy={removeBusy}
          onConfirm={confirmRemove}
          onCancel={() => !removeBusy && setRemoveFlow(null)}
        />
      )}

      {removeFlow?.step === "deactivate-instead" && (
        <ConfirmDialog
          title={`Can't remove ${removeFlow.name}`}
          message="This rider has payment records on file (COD collections or shift reconciliations). Deactivate them instead? They'll stay in your list but won't receive new orders."
          confirmLabel="Deactivate rider"
          cancelLabel="Cancel"
          busy={removeBusy}
          onConfirm={confirmDeactivateInstead}
          onCancel={() => !removeBusy && setRemoveFlow(null)}
        />
      )}
    </div>
  );
}

function RidersSkeleton() {
  return (
    <>
      <div className={s.stats} aria-busy="true" aria-label="Loading riders">
        {[70, 96, 104, 80].map((w, i) => (
          <span key={i} className={`${s.sk} ${s.skStat}`} style={{ width: w }} />
        ))}
      </div>
      <div className={s.ops}>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className={s.pane}>
            <div className={s.skCard}>
              <span className={`${s.sk} ${s.skLineLg}`} style={{ width: "55%" }} />
              <span className={`${s.sk} ${s.skLine}`} style={{ width: "40%" }} />
              <span className={`${s.sk} ${s.skLine}`} style={{ width: "70%" }} />
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
