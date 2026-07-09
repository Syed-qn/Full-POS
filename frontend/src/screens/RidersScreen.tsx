import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { RiderCard } from "../components/RiderCard";
import { RiderAddModal } from "../components/RiderAddModal";
import { AppInviteModal } from "../components/AppInviteModal";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/Button";
import { toast } from "../components/Toaster";
import { ApiError, apiClient } from "../lib/apiClient";
import { useRidersQuery } from "../lib/queries/dashboard";
import { reconcileRiderCod } from "../lib/dispatchApi";
import { deleteRider, setRiderDuty, setRiderStatus } from "../lib/ridersApi";
import type { RestaurantOut, RiderOut, RiderStatus } from "../lib/types";
import s from "./RidersScreen.module.css";

type RemoveFlow =
  | { step: "confirm"; id: number; name: string }
  | { step: "deactivate-instead"; id: number; name: string };

export function RidersScreen() {
  const queryClient = useQueryClient();
  const { data: riders = [], isLoading } = useRidersQuery();
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

  async function onStatusChange(id: number, status: RiderStatus) {
    const updated = await setRiderStatus(id, status);
    patchRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  async function onDutyChange(id: number, on_duty: boolean) {
    const updated = await setRiderDuty(id, on_duty);
    patchRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  function onInviteApp(id: number) {
    // Open a confirmation dialog (the rider must message the restaurant first so
    // WhatsApp's 24h window is open) instead of sending immediately.
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
        // COD / shift records must stay on file — offer deactivation instead of
        // leaving the manager stuck after a blocked hard-delete.
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
    <div className={s.root}>
      <PageHeader
        title="Riders"
        subtitle="Your own delivery fleet: shifts, status & live tracking"
        right={<Button onClick={() => setShowAdd(true)}>+ Add Rider</Button>}
      />

      {riders.length > 0 && (
        <div className={s.stats}>
          <span className={s.stat}>
            <span className={s.statNum}>{riders.length}</span> riders
          </span>
          <span className={s.statDivider} />
          <span className={s.stat}>
            <span className={s.statDot} style={{ background: "var(--sla-safe)" }} /> {counts.available} available
          </span>
          <span className={s.stat}>
            <span className={s.statDot} style={{ background: "var(--accent-rider)" }} /> {counts.on_delivery} on delivery
          </span>
          <span className={s.stat}>
            <span className={s.statDot} style={{ background: "var(--text-muted)" }} /> {counts.off_shift} off shift
          </span>
          {counts.deactivated > 0 && (
            <span className={s.stat}>
              <span className={s.statDot} style={{ background: "var(--sla-critical)" }} /> {counts.deactivated} deactivated
            </span>
          )}
        </div>
      )}

      {!loaded && <RidersSkeleton />}

      {loaded && riders.length === 0 && (
        <div className={s.empty}>No riders yet — click "+ Add Rider" to register your first rider.</div>
      )}

      <div className={s.grid}>
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

// Skeleton placeholder mirroring the riders layout (stats bar + a grid of
// white rider-card placeholders) so the page keeps its shape while loading.
// Returns a fragment so .stats and .grid are direct children of .root and
// inherit its column gap.
function RidersSkeleton() {
  return (
    <>
      <div className={s.stats} aria-busy="true" aria-label="Loading riders">
        {[70, 96, 104, 80].map((w, i) => (
          <span key={i} className={`${s.sk} ${s.skStat}`} style={{ width: w }} />
        ))}
      </div>
      <div className={s.grid}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className={s.skCard}>
            <span className={`${s.sk} ${s.skLineLg}`} style={{ width: "55%" }} />
            <span className={`${s.sk} ${s.skLine}`} style={{ width: "40%" }} />
            <span className={`${s.sk} ${s.skLine}`} style={{ width: "70%" }} />
          </div>
        ))}
      </div>
    </>
  );
}
