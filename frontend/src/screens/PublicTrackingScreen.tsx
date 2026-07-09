import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  fetchPublicTracking,
  fetchPublicTrackingLocation,
  TrackingError,
  type PublicTrackingOut,
  type TrackingLocationOut,
} from "../lib/trackingApi";
import s from "./PublicTrackingScreen.module.css";

type Phase = "loading" | "active" | "ended" | "notfound" | "error";

/** Customer-facing milestones only — no kitchen/internal statuses. */
const TIMELINE_STEPS = [
  { key: "confirmed", label: "Order received", match: ["confirmed", "preparing", "ready", "assigned", "picked_up", "arriving", "delivered"] },
  { key: "preparing", label: "Being prepared", match: ["preparing", "ready", "assigned", "picked_up", "arriving", "delivered"] },
  { key: "on_the_way", label: "On the way", match: ["assigned", "picked_up", "arriving", "delivered"] },
  { key: "arriving", label: "Arriving soon", match: ["arriving", "delivered"] },
  { key: "delivered", label: "Delivered", match: ["delivered"] },
] as const;

const STATUS_COPY: Record<string, string> = {
  confirmed: "We've got your order",
  preparing: "The kitchen is preparing your food",
  ready: "Your order is ready for the rider",
  assigned: "A rider is on the way to pick up your order",
  picked_up: "Your order is on the way",
  arriving: "Your rider is almost there",
  delivered: "Delivered — enjoy your meal!",
};

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "Waiting for rider location";
  return new Date(iso).toLocaleTimeString();
}

function customerStatusLabel(statusKey: string): string {
  return STATUS_COPY[statusKey] ?? (statusKey ? statusKey.replace(/_/g, " ") : "Loading…");
}

/** Map only once a rider is assigned / en route (not kitchen-only phases). */
function shouldShowMap(statusKey: string, hasLocation: boolean): boolean {
  if (["assigned", "picked_up", "arriving"].includes(statusKey)) return true;
  if (statusKey === "delivered" && hasLocation) return true;
  return false;
}

// Coloured pin with an emoji glyph — gives the map a Swiggy/Zomato look.
function pinIcon(L: typeof import("leaflet"), emoji: string, bg: string) {
  return L.divIcon({
    className: "",
    html:
      `<div style="width:34px;height:34px;border-radius:50% 50% 50% 0;` +
      `transform:rotate(-45deg);background:${bg};border:2px solid #fff;` +
      `box-shadow:0 2px 6px rgba(15,23,42,.35);display:flex;align-items:center;` +
      `justify-content:center;">` +
      `<span style="transform:rotate(45deg);font-size:16px;line-height:1;">${emoji}</span>` +
      `</div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 32],
  });
}

function riderIcon(L: typeof import("leaflet"), heading: number | null | undefined) {
  const hasHeading = typeof heading === "number" && !Number.isNaN(heading);
  const arrow = hasHeading
    ? `<div style="position:absolute;inset:0;transform:rotate(${heading}deg);">` +
      `<div style="position:absolute;top:-3px;left:50%;transform:translateX(-50%);` +
      `width:0;height:0;border-left:7px solid transparent;border-right:7px solid transparent;` +
      `border-bottom:11px solid #16a34a;"></div>` +
      `</div>`
    : "";
  return L.divIcon({
    className: "",
    html:
      `<div style="position:relative;width:40px;height:40px;">` +
      arrow +
      `<div style="position:absolute;top:4px;left:4px;width:32px;height:32px;` +
      `border-radius:50%;background:#16a34a;border:2px solid #fff;` +
      `box-shadow:0 2px 6px rgba(15,23,42,.35);display:flex;align-items:center;` +
      `justify-content:center;font-size:17px;line-height:1;">🛵</div>` +
      `</div>`,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  });
}

export function PublicTrackingScreen() {
  const { trackingToken = "" } = useParams();
  const [tracking, setTracking] = useState<PublicTrackingOut | null>(null);
  const [location, setLocation] = useState<TrackingLocationOut | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<import("leaflet").Map | null>(null);
  const riderRef = useRef<import("leaflet").Marker | null>(null);
  const restaurantRef = useRef<import("leaflet").Marker | null>(null);
  const destRef = useRef<import("leaflet").Marker | null>(null);
  const routeRef = useRef<import("leaflet").Polyline | null>(null);
  const fittedRef = useRef(false);

  useEffect(() => {
    const meta = document.querySelector('meta[name="viewport"]');
    const prev = meta?.getAttribute("content") ?? null;
    meta?.setAttribute("content", "width=device-width, initial-scale=1");
    return () => {
      if (meta && prev !== null) meta.setAttribute("content", prev);
    };
  }, []);

  function classifyError(err: unknown): boolean {
    if (err instanceof TrackingError) {
      if (err.status === 410) {
        setPhase("ended");
        return true;
      }
      if (err.status === 404) {
        setPhase("notfound");
        return true;
      }
    }
    return false;
  }

  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const data = await fetchPublicTracking(trackingToken);
        if (!alive) return;
        setTracking(data);
        setLocation(data.location);
        setError(null);
        setPhase("active");
      } catch (err) {
        if (!alive) return;
        if (!classifyError(err)) {
          setPhase("error");
          setError(err instanceof Error ? err.message : "Failed to load tracking");
        }
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
          setPhase("active");
        }
      } catch (err) {
        if (!alive) return;
        classifyError(err);
      }
    }
    if (!trackingToken) return;
    timerRef.current = window.setInterval(tick, 5000);
    tick();
    return () => {
      alive = false;
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
    };
  }, [trackingToken]);

  useEffect(() => {
    if ((phase === "ended" || phase === "notfound") && timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, [phase]);

  const statusKey = location?.status ?? tracking?.status ?? "";
  const showMap = shouldShowMap(statusKey, Boolean(location));

  useEffect(() => {
    if (!showMap || !mapRef.current || !tracking) return;
    const restaurant = tracking.restaurant ?? null;
    const dest = tracking.destination ?? null;
    const riderPos: [number, number] | null = location
      ? [location.latitude, location.longitude]
      : null;

    const anchor = riderPos
      ?? (restaurant ? ([restaurant.latitude, restaurant.longitude] as [number, number]) : null)
      ?? (dest ? ([dest.latitude, dest.longitude] as [number, number]) : null);
    if (!anchor) return;

    import("leaflet").then((L) => {
      if (!mapRef.current) return;
      if (!leafletMapRef.current) {
        const map = L.map(mapRef.current, { zoomControl: true }).setView(anchor, 14);
        leafletMapRef.current = map;
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: "© OpenStreetMap contributors",
        }).addTo(map);
        setTimeout(() => map.invalidateSize(), 0);
      }
      const map = leafletMapRef.current;

      if (restaurant && !restaurantRef.current) {
        restaurantRef.current = L.marker([restaurant.latitude, restaurant.longitude], {
          icon: pinIcon(L, "🍴", "#f97316"),
        })
          .addTo(map)
          .bindPopup(restaurant.label ?? "Restaurant");
      }
      if (dest && !destRef.current) {
        destRef.current = L.marker([dest.latitude, dest.longitude], {
          icon: pinIcon(L, "🏠", "#2563eb"),
        })
          .addTo(map)
          .bindPopup(dest.label ?? "Delivery address");
      }
      if (riderPos) {
        const heading = location?.heading ?? null;
        if (!riderRef.current) {
          riderRef.current = L.marker(riderPos, { icon: riderIcon(L, heading), zIndexOffset: 1000 })
            .addTo(map)
            .bindPopup("Your rider");
        } else {
          riderRef.current.setLatLng(riderPos);
          riderRef.current.setIcon(riderIcon(L, heading));
        }
      }

      if (restaurant && dest) {
        const line: [number, number][] = [
          [restaurant.latitude, restaurant.longitude],
          [dest.latitude, dest.longitude],
        ];
        if (!routeRef.current) {
          routeRef.current = L.polyline(line, {
            color: "#16a34a",
            weight: 4,
            opacity: 0.7,
            dashArray: "1 10",
            lineCap: "round",
          }).addTo(map);
        } else {
          routeRef.current.setLatLngs(line);
        }
      }

      if (!fittedRef.current) {
        const pts: [number, number][] = [];
        if (restaurant) pts.push([restaurant.latitude, restaurant.longitude]);
        if (dest) pts.push([dest.latitude, dest.longitude]);
        if (riderPos) pts.push(riderPos);
        if (pts.length >= 2) {
          map.fitBounds(L.latLngBounds(pts), { padding: [48, 48], maxZoom: 16 });
          fittedRef.current = true;
        } else if (pts.length === 1) {
          map.setView(pts[0], 15);
        }
      }
    });
  }, [tracking, location, showMap]);

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

  if (phase === "ended" || phase === "notfound") {
    const ended = phase === "ended";
    return (
      <main className={s.page}>
        <section className={s.card}>
          <h1 className={s.title}>Order tracking</h1>
          <div className={s.endState}>
            <div className={s.endEmoji}>{ended ? "✅" : "🔍"}</div>
            <h2 className={s.endTitle}>
              {ended ? "This delivery is complete" : "Tracking link not found"}
            </h2>
            <p className={s.endText}>
              {ended
                ? "Live tracking for this order has ended. Thanks for ordering — we hope you enjoyed your meal!"
                : "This tracking link is invalid or no longer exists. Please check the link in your WhatsApp chat."}
            </p>
          </div>
        </section>
      </main>
    );
  }

  const statusText = customerStatusLabel(statusKey);
  const etaHint =
    statusKey === "arriving"
      ? "Usually a few minutes"
      : statusKey === "picked_up" || statusKey === "assigned"
        ? "Typically within 40 minutes of ordering"
        : statusKey === "preparing" || statusKey === "ready" || statusKey === "confirmed"
          ? "We'll show the map once your rider is on the way"
          : null;

  return (
    <main className={s.page}>
      <section className={s.card}>
        <h1 className={s.title}>Track your order</h1>
        <p className={s.meta}>
          Order {tracking?.orderNumber ?? "—"}
        </p>

        <div className={s.statusHero} data-testid="status-hero">
          <strong>{statusText}</strong>
          {etaHint ? <span>{etaHint}</span> : null}
        </div>

        <ol className={s.timeline} data-testid="status-timeline" aria-label="Order progress">
          {TIMELINE_STEPS.map((step) => {
            const done = step.match.includes(statusKey as never);
            const current =
              done &&
              !(
                TIMELINE_STEPS.findIndex((t) => t.key === step.key) <
                  TIMELINE_STEPS.length - 1 &&
                TIMELINE_STEPS[TIMELINE_STEPS.findIndex((t) => t.key === step.key) + 1]?.match.includes(
                  statusKey as never,
                )
              );
            return (
              <li
                key={step.key}
                className={`${s.timelineStep} ${done ? s.timelineDone : ""} ${current ? s.timelineCurrent : ""}`}
              >
                <span className={s.timelineDot} aria-hidden />
                <span className={s.timelineLabel}>{step.label}</span>
              </li>
            );
          })}
        </ol>

        {phase === "error" && error ? <div className={s.error}>{error}</div> : null}

        {showMap ? (
          <>
            <div ref={mapRef} className={s.map} data-testid="tracking-map" />
            <div className={s.legend}>
              <span className={s.legendItem}>
                <span className={s.dotFrom} /> {tracking?.restaurant?.label ?? "Restaurant"}
              </span>
              <span className={s.legendItem}>
                <span className={s.dotRider} /> Rider
              </span>
              {tracking?.destination ? (
                <span className={s.legendItem}>
                  <span className={s.dotTo} /> {tracking.destination.label ?? "Your address"}
                </span>
              ) : null}
            </div>
            {tracking && !tracking.destination ? (
              <p className={s.note}>
                Exact delivery pin is not shared for this order — the map shows the restaurant and
                your rider only.
              </p>
            ) : null}
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
                Open rider location in Maps
              </a>
            ) : (
              <p className={s.waiting}>The rider hasn&apos;t shared a live GPS position yet.</p>
            )}
          </>
        ) : (
          <div className={s.mapPlaceholder} data-testid="map-placeholder">
            <p>
              Live map appears when your rider is on the way.
              {statusKey === "preparing" || statusKey === "ready" || statusKey === "confirmed"
                ? " Your food is being prepared — hang tight."
                : ""}
            </p>
          </div>
        )}

        <div className={s.helpRow}>
          <p className={s.helpText}>
            Need help? Reply on WhatsApp or contact the restaurant from your order chat.
          </p>
        </div>
      </section>
    </main>
  );
}
