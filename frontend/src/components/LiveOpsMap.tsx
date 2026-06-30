import { useEffect, useRef } from "react";
import { fetchLiveOpsMap } from "../lib/dispatchApi";
import type { LiveOpsMapOut } from "../lib/types";
import { usePoll } from "../lib/usePoll";
import s from "./LiveOpsMap.module.css";

const URGENCY_COLOR: Record<string, string> = {
  safe: "#10b981",
  warn: "#f59e0b",
  critical: "#ef4444",
};

export function LiveOpsMap({ mapData }: { mapData?: LiveOpsMapOut }) {
  const polled = usePoll(() => fetchLiveOpsMap(), 8000);
  const data = mapData ?? polled.data;
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<import("leaflet").Map | null>(null);
  const layerGroupRef = useRef<import("leaflet").LayerGroup | null>(null);

  useEffect(() => {
    let cancelled = false;
    import("leaflet").then((L) => {
      if (cancelled || !mapRef.current || leafletMapRef.current) return;
      const map = L.map(mapRef.current, { zoomControl: true }).setView([25.2, 55.27], 13);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap",
      }).addTo(map);
      leafletMapRef.current = map;
      layerGroupRef.current = L.layerGroup().addTo(map);
    });
    return () => {
      cancelled = true;
      leafletMapRef.current?.remove();
      leafletMapRef.current = null;
      layerGroupRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!data) return;
    import("leaflet").then((L) => {
      const map = leafletMapRef.current;
      const group = layerGroupRef.current;
      if (!map || !group) return;
      group.clearLayers();

      L.circleMarker([data.origin.lat, data.origin.lng], {
        radius: 8,
        color: "#111827",
        fillColor: "#111827",
        fillOpacity: 1,
      })
        .bindTooltip("Restaurant")
        .addTo(group);

      for (const ring of data.sla_rings) {
        L.circle([ring.lat, ring.lng], {
          radius: ring.radius_km * 1000,
          color: URGENCY_COLOR[ring.urgency] ?? "#9ca3af",
          fillColor: URGENCY_COLOR[ring.urgency] ?? "#9ca3af",
          fillOpacity: 0.12,
          weight: 2,
        })
          .bindTooltip(`${ring.order_number} — ${ring.minutes_remaining} min left`)
          .addTo(group);
      }

      for (const batch of data.batches) {
        if (batch.polyline.length >= 2) {
          L.polyline(
            batch.polyline.map(([lat, lng]) => [lat, lng] as [number, number]),
            { color: batch.color, weight: 4, opacity: 0.85 },
          )
            .bindTooltip(
              `Batch #${batch.batch_id}${batch.rider_name ? ` — ${batch.rider_name}` : ""}`,
            )
            .addTo(group);
        }
        for (const stop of batch.stops) {
          L.circleMarker([stop.lat, stop.lng], {
            radius: 6,
            color: batch.color,
            fillColor: "#fff",
            fillOpacity: 1,
            weight: 3,
          })
            .bindTooltip(`${stop.order_number} (stop ${stop.sequence})`)
            .addTo(group);
        }
      }

      const points: [number, number][] = [
        [data.origin.lat, data.origin.lng],
        ...data.sla_rings.map((r) => [r.lat, r.lng] as [number, number]),
      ];
      if (points.length > 1) {
        map.fitBounds(L.latLngBounds(points), { padding: [24, 24], maxZoom: 14 });
      }
      map.invalidateSize();
    });
  }, [data]);

  if (!data) {
    return <div className={s.placeholder} aria-busy="true">Loading fleet map…</div>;
  }

  return (
    <section className={s.wrap} aria-label="Live fleet map">
      <div className={s.legend}>
        <span className={s.legendItem}><span className={s.dotSafe} /> SLA safe</span>
        <span className={s.legendItem}><span className={s.dotWarn} /> SLA warn</span>
        <span className={s.legendItem}><span className={s.dotCrit} /> SLA critical</span>
      </div>
      <div ref={mapRef} className={s.map} />
    </section>
  );
}