import { useEffect, useMemo, useState } from "react";
import { RiderCard } from "../components/RiderCard";
import { RiderAddModal } from "../components/RiderAddModal";
import { AppInviteModal } from "../components/AppInviteModal";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/Button";
import { apiClient } from "../lib/apiClient";
import { deleteRider, fetchRiderAppInfo, fetchRiders, setRiderStatus } from "../lib/ridersApi";
import { usePollingRefresh } from "../lib/usePollingRefresh";
import type { RestaurantOut, RiderOut, RiderStatus } from "../lib/types";
import s from "./RidersScreen.module.css";

export function RidersScreen() {
  const [riders, setRiders] = useState<RiderOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<RiderOut | null>(null);
  const [inviteFor, setInviteFor] = useState<RiderOut | null>(null);
  const [apkUrl, setApkUrl] = useState<string | null>(null);
  const [restaurantPhone, setRestaurantPhone] = useState<string | null>(null);

  useEffect(() => {
    fetchRiders()
      .then(setRiders)
      .finally(() => setLoaded(true));
    fetchRiderAppInfo()
      .then((info) => setApkUrl(info.apkUrl))
      .catch(() => {});
    apiClient
      .get<RestaurantOut>("/api/v1/me")
      .then((me) => setRestaurantPhone(me.phone))
      .catch(() => {});
  }, []);

  // Live updates: refresh rider list/status in the background (no skeleton flash).
  usePollingRefresh(() => {
    fetchRiders().then(setRiders).catch(() => {});
  });

  const counts = useMemo(() => {
    const c = { available: 0, on_delivery: 0, off_shift: 0, deactivated: 0 };
    for (const r of riders) c[r.status]++;
    return c;
  }, [riders]);

  async function onStatusChange(id: number, status: RiderStatus) {
    const updated = await setRiderStatus(id, status);
    setRiders((rs) => rs.map((r) => (r.id === id ? updated : r)));
  }

  function onInviteApp(id: number) {
    // Open a confirmation dialog (the rider must message the restaurant first so
    // WhatsApp's 24h window is open) instead of sending immediately.
    const rider = riders.find((r) => r.id === id);
    if (rider) setInviteFor(rider);
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

      <div className={s.appBanner}>
        <span className={s.appBannerIcon}>📱</span>
        <div className={s.appBannerText}>
          <strong>Rider Tracker app</strong> — riders install it once to share
          live location automatically (even with the screen off). Use{" "}
          <em>Send app link</em> on a rider to text them a pairing code.
        </div>
        {apkUrl ? (
          <a className={s.appBannerLink} href={apkUrl} target="_blank" rel="noreferrer">
            Download APK
          </a>
        ) : (
          <span className={s.appBannerMuted}>APK link not set up yet</span>
        )}
      </div>

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
            onInviteApp={onInviteApp}
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

      {inviteFor && (
        <AppInviteModal
          rider={inviteFor}
          restaurantPhone={restaurantPhone}
          onClose={() => setInviteFor(null)}
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
