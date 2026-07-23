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

  // NOTE: manual assign used to live here, driven by selecting an order in the
  // queue and a rider in the fleet. Both selectors went with the 3-pane block.
  // Assigning a rider by hand is still available in the order detail drawer
  // (Orders / Live Ops → open an order → assign), which is the only remaining
  // entry point.

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
        subtitle="Your fleet: duty, pairing, cash settlement"
        right={<Button onClick={() => setShowAdd(true)}>+ Add Rider</Button>}
      />

      {riders.length > 0 && (
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
            <span className={s.statDot} style={{ background: "var(--text-muted)" }} /> {counts.off_shift}{" "}
            off shift
          </span>
          {counts.deactivated > 0 && (
            <span className={s.stat}>
              <span className={s.statDot} style={{ background: "var(--sla-critical)" }} />{" "}
              {counts.deactivated} deactivated
            </span>
          )}
        </div>
      )}

      {!loaded && <RidersSkeleton />}

      {loaded && riders.length === 0 && (
        <div className={s.empty}>No riders yet. Click "+ Add Rider" to register your first rider.</div>
      )}

      {loaded && riders.length > 0 && (
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
  // Mirror the real content: the stats row, then a card grid whose placeholders
  // match a RiderCard (avatar + name/phone, dispatch banner, location line, two
  // delivery stats, a row of action buttons). The old skeleton drew the removed
  // 3-pane ops block, so the page visibly reshaped when riders loaded in.
  return (
    <>
      <div className={s.stats} aria-busy="true" aria-label="Loading riders">
        {[70, 96, 104, 80].map((w, i) => (
          <span key={i} className={`${s.sk} ${s.skStat}`} style={{ width: w }} />
        ))}
      </div>
      <div className={s.detail}>
        <div
          className={s.grid}
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))" }}
        >
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className={s.skCard}>
              <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 14 }}>
                <span className={s.sk} style={{ width: 44, height: 44, borderRadius: "50%" }} />
                <div style={{ flex: 1 }}>
                  <span
                    className={`${s.sk} ${s.skLineLg}`}
                    style={{ width: "50%", marginBottom: 8 }}
                  />
                  <span className={`${s.sk} ${s.skLine}`} style={{ width: "35%" }} />
                </div>
              </div>
              <span
                className={`${s.sk} ${s.skLine}`}
                style={{ height: 34, width: "100%", marginBottom: 12 }}
              />
              <span
                className={`${s.sk} ${s.skLine}`}
                style={{ width: "60%", marginBottom: 12 }}
              />
              <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
                <span className={`${s.sk} ${s.skLine}`} style={{ height: 40, flex: 1 }} />
                <span className={`${s.sk} ${s.skLine}`} style={{ height: 40, flex: 1 }} />
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
                  gap: 8,
                }}
              >
                {Array.from({ length: 4 }).map((_, j) => (
                  <span key={j} className={`${s.sk} ${s.skLine}`} style={{ height: 36 }} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
