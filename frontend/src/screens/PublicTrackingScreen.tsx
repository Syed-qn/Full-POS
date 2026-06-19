import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  fetchPublicTracking,
  fetchPublicTrackingLocation,
  type PublicTrackingOut,
  type TrackingLocationOut,
} from "../lib/trackingApi";
import s from "./PublicTrackingScreen.module.css";

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "Waiting for rider location";
  return new Date(iso).toLocaleTimeString();
}

export function PublicTrackingScreen() {
  const { trackingToken = "" } = useParams();
  const [tracking, setTracking] = useState<PublicTrackingOut | null>(null);
  const [location, setLocation] = useState<TrackingLocationOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<import("leaflet").Map | null>(null);
  const markerRef = useRef<import("leaflet").CircleMarker | null>(null);

  // The app forces a 1440px desktop viewport for the manager dashboard, which
  // makes this customer-facing page render zoomed-out on phones. Override it to
  // the device width while this screen is mounted, then restore on leave.
  useEffect(() => {
    const meta = document.querySelector('meta[name="viewport"]');
    const prev = meta?.getAttribute("content") ?? null;
    meta?.setAttribute("content", "width=device-width, initial-scale=1");
    return () => {
      if (meta && prev !== null) meta.setAttribute("content", prev);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await fetchPublicTracking(trackingToken);
        if (!alive) return;
        setTracking(data);
        setLocation(data.location);
        setError(null);
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "Failed to load tracking");
      }
    }
    load();
    return () => {
      alive = false;
    };
  }, [trackingToken]);

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const next = await fetchPublicTrackingLocation(trackingToken);
        if (alive) {
          setLocation(next);
          setError(null);
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : "Tracking unavailable");
      }
    }
    if (!trackingToken) return;
    const timer = window.setInterval(tick, 5000);
    tick();
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [trackingToken]);

  useEffect(() => {
    if (!mapRef.current || !location) return;
    const pos: [number, number] = [location.latitude, location.longitude];
    import("leaflet").then((L) => {
      if (!mapRef.current) return;
      if (!leafletMapRef.current) {
        const map = L.map(mapRef.current, { zoomControl: true }).setView(pos, 15);
        leafletMapRef.current = map;
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: "© OpenStreetMap contributors",
        }).addTo(map);
        // The map container is sized by CSS (and flex-grows on mobile); re-measure
        // once layout settles so tiles fill the box instead of rendering partial.
        setTimeout(() => map.invalidateSize(), 0);
        markerRef.current = L.circleMarker(pos, {
          radius: 10,
          color: "#fff",
          weight: 2,
          fillColor: "#16a34a",
          fillOpacity: 1,
        }).addTo(map);
      } else {
        leafletMapRef.current.setView(pos, leafletMapRef.current.getZoom());
        markerRef.current?.setLatLng(pos);
      }
    });
  }, [location]);

  useEffect(() => {
    const onResize = () => leafletMapRef.current?.invalidateSize();
    window.addEventListener("resize", onResize);
    window.addEventListener("orientationchange", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("orientationchange", onResize);
      leafletMapRef.current?.remove();
      leafletMapRef.current = null;
    };
  }, []);

  return (
    <main className={s.page}>
      <section className={s.card}>
        <h1 className={s.title}>Live order tracking</h1>
        <p className={s.meta}>
          Order {tracking?.orderNumber ?? "—"} · Status {location?.status ?? tracking?.status ?? "loading"}
        </p>
        {error ? <div className={s.error}>{error}</div> : null}
        <div ref={mapRef} className={s.map} />
        <div className={s.infoRow}>
          <span>Last updated</span>
          <strong>{formatTime(location?.updatedAt ?? tracking?.lastUpdatedAt)}</strong>
        </div>
        {location ? (
          <a
            className={s.link}
            href={`https://www.google.com/maps/search/?api=1&query=${location.latitude},${location.longitude}`}
            target="_blank"
            rel="noreferrer"
          >
            Open in Maps
          </a>
        ) : (
          <p className={s.waiting}>The rider hasn’t shared a live GPS position yet.</p>
        )}
      </section>
    </main>
  );
}
