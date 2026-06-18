import { useEffect, useRef, useState } from "react";
import { fetchRiderLocation } from "../lib/ridersApi";
import type { RiderLocationOut, RiderOut } from "../lib/types";
import s from "./RiderMapModal.module.css";

/** "seen 2 min ago" style relative time from an ISO timestamp. */
function seenAgo(iso: string): string {
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

// A ping older than this means the rider has likely stopped sharing — the dot
// shown is their last-known spot, not where they are right now.
const STALE_MS = 3 * 60 * 1000;

export function RiderMapModal({
  rider,
  onClose,
}: {
  rider: RiderOut;
  onClose: () => void;
}) {
  const [loc, setLoc] = useState<RiderLocationOut | null>(null);
  const [loaded, setLoaded] = useState(false);
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<import("leaflet").Map | null>(null);
  const markerRef = useRef<import("leaflet").CircleMarker | null>(null);

  // Poll the rider's latest ping every 5s while the modal is open. Live-location
  // updates arrive from WhatsApp every ~1–2 min, so 5s comfortably keeps up.
  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const next = await fetchRiderLocation(rider.id);
        if (alive) setLoc(next);
      } catch {
        /* keep last value on a transient error */
      } finally {
        if (alive) setLoaded(true);
      }
    }
    tick();
    const t = setInterval(tick, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [rider.id]);

  // Create / update the Leaflet map as new positions arrive.
  useEffect(() => {
    if (!mapRef.current || loc === null) return;
    const pos: [number, number] = [loc.lat, loc.lng];

    import("leaflet").then((L) => {
      if (!mapRef.current) return;
      if (!leafletMapRef.current) {
        const map = L.map(mapRef.current, { zoomControl: true }).setView(pos, 16);
        leafletMapRef.current = map;
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: "© OpenStreetMap contributors",
        }).addTo(map);
        markerRef.current = L.circleMarker(pos, {
          radius: 9,
          color: "#fff",
          weight: 2,
          fillColor: "#2563eb",
          fillOpacity: 1,
        })
          .bindTooltip(rider.name)
          .addTo(map);
      } else {
        leafletMapRef.current.setView(pos, leafletMapRef.current.getZoom());
        markerRef.current?.setLatLng(pos);
      }
    });
  }, [loc, rider.name]);

  useEffect(() => {
    return () => {
      leafletMapRef.current?.remove();
      leafletMapRef.current = null;
    };
  }, []);

  const stale = loc !== null && Date.now() - new Date(loc.ts).getTime() > STALE_MS;

  return (
    <div className={s.overlay} onClick={onClose}>
      <div className={s.modal} onClick={(e) => e.stopPropagation()}>
        <div className={s.header}>
          <div className={s.headText}>
            <h2 className={s.title}>{rider.name}</h2>
            {loc ? (
              <span className={`${s.seen} ${stale ? s.seenStale : ""}`}>
                <span className={s.seenDot} />
                {stale ? "Last seen " : "Live · "}
                {seenAgo(loc.ts)}
              </span>
            ) : (
              <span className={s.seen}>Location tracking</span>
            )}
          </div>
          <button className={s.close} onClick={onClose} aria-label="Close">×</button>
        </div>

        {loc ? (
          <>
            <div ref={mapRef} className={s.map} />
            <div className={s.footer}>
              <a
                className={s.mapsLink}
                href={`https://www.google.com/maps/search/?api=1&query=${loc.lat},${loc.lng}`}
                target="_blank"
                rel="noreferrer"
              >
                Open in Google Maps ↗
              </a>
            </div>
          </>
        ) : (
          <div className={s.empty}>
            {!loaded
              ? "Loading…"
              : "No location yet. The rider shares live location after tapping " +
                "“Picked up” — it'll appear here once they do."}
          </div>
        )}
      </div>
    </div>
  );
}
