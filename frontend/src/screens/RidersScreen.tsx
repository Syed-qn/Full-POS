import { useEffect, useMemo, useState } from "react";
import { RiderCard } from "../components/RiderCard";
import { RiderAddModal } from "../components/RiderAddModal";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/Button";
import { deleteRider, fetchRiders, setRiderStatus } from "../lib/ridersApi";
import type { RiderOut, RiderStatus } from "../lib/types";
import s from "./RidersScreen.module.css";

export function RidersScreen() {
  const [riders, setRiders] = useState<RiderOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<RiderOut | null>(null);

  useEffect(() => {
    fetchRiders()
      .then(setRiders)
      .finally(() => setLoaded(true));
  }, []);

  const counts = useMemo(() => {
    const c = { available: 0, on_delivery: 0, off_shift: 0, deactivated: 0 };
    for (const r of riders) c[r.status]++;
    return c;
  }, [riders]);

  async function onStatusChange(id: number, status: RiderStatus) {
    const updated = await setRiderStatus(id, status);
    setRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  async function onDelete(id: number) {
    if (!confirm("Remove this rider? This cannot be undone.")) return;
    try {
      await deleteRider(id);
      setRiders((rs) => rs.filter((r) => r.id !== id));
    } catch (e) {
      // Surface the reason (e.g. 409: rider has payment records → deactivate
      // instead) rather than silently failing.
      const msg = e instanceof Error ? e.message : "Could not remove this rider.";
      alert(msg);
    }
  }

  return (
    <div className={s.root}>
      <PageHeader
        title="Riders"
        subtitle="Your own delivery fleet — shifts, status & live tracking"
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
            onDelete={onDelete}
            onEdit={setEditing}
          />
        ))}
      </div>

      {showAdd && (
        <RiderAddModal
          onClose={() => setShowAdd(false)}
          onSaved={(rider) => setRiders((rs) => [...rs, rider])}
        />
      )}

      {editing && (
        <RiderAddModal
          rider={editing}
          onClose={() => setEditing(null)}
          onSaved={(rider) =>
            setRiders((rs) => rs.map((r) => (r.id === rider.id ? rider : r)))
          }
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
