import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  fetchRiderTracking,
  postRiderLocation,
  stopRiderTracking,
  type RiderTrackingOut,
} from "../lib/trackingApi";
import s from "./RiderTrackingScreen.module.css";

type QueueItem = {
  latitude: number;
  longitude: number;
  accuracy?: number | null;
  speed?: number | null;
  heading?: number | null;
};

const SEND_INTERVAL_MS = 5000;

export function RiderTrackingScreen() {
  const { riderToken = "" } = useParams();
  const [meta, setMeta] = useState<RiderTrackingOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tracking, setTracking] = useState(false);
  const [gpsStatus, setGpsStatus] = useState("Idle");
  const [lastSentAt, setLastSentAt] = useState<string | null>(null);
  const watchIdRef = useRef<number | null>(null);
  const queueRef = useRef<QueueItem[]>([]);
  const flushingRef = useRef(false);
  const lastSentMsRef = useRef(0);
  const storageKey = useMemo(() => `rider-tracking-queue:${riderToken}`, [riderToken]);

  // Override the app's forced 1440px desktop viewport with the device width while
  // this rider-facing page (used on a phone) is mounted; restore on leave.
  useEffect(() => {
    const vp = document.querySelector('meta[name="viewport"]');
    const prev = vp?.getAttribute("content") ?? null;
    vp?.setAttribute("content", "width=device-width, initial-scale=1");
    return () => {
      if (vp && prev !== null) vp.setAttribute("content", prev);
    };
  }, []);

  useEffect(() => {
    try {
      queueRef.current = JSON.parse(localStorage.getItem(storageKey) ?? "[]") as QueueItem[];
    } catch {
      queueRef.current = [];
    }
  }, [storageKey]);

  useEffect(() => {
    fetchRiderTracking(riderToken)
      .then((data) => {
        setMeta(data);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load rider tracker"));
  }, [riderToken]);

  useEffect(() => {
    function handleOnline() {
      void flushQueue();
    }
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  });

  useEffect(() => {
    return () => {
      if (watchIdRef.current !== null) navigator.geolocation.clearWatch(watchIdRef.current);
    };
  }, []);

  function persistQueue() {
    localStorage.setItem(storageKey, JSON.stringify(queueRef.current));
  }

  async function flushQueue() {
    if (!meta || flushingRef.current || !navigator.onLine || queueRef.current.length === 0) return;
    flushingRef.current = true;
    try {
      while (queueRef.current.length > 0) {
        const next = queueRef.current[0];
        await postRiderLocation(meta.orderId, riderToken, next);
        queueRef.current.shift();
        persistQueue();
        lastSentMsRef.current = Date.now();
        setLastSentAt(new Date().toLocaleTimeString());
      }
      setGpsStatus("Live updates sending");
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send location");
      setGpsStatus(navigator.onLine ? "Retrying failed updates" : "Offline queueing enabled");
    } finally {
      flushingRef.current = false;
    }
  }

  function enqueuePosition(position: GeolocationPosition) {
    const item: QueueItem = {
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      accuracy: position.coords.accuracy,
      speed: position.coords.speed ?? null,
      heading: position.coords.heading ?? null,
    };
    queueRef.current.push(item);
    persistQueue();
    if (Date.now() - lastSentMsRef.current >= SEND_INTERVAL_MS) {
      void flushQueue();
    } else {
      setGpsStatus("GPS active");
    }
  }

  function startTracking() {
    if (!navigator.geolocation) {
      setError("Geolocation is not available in this browser.");
      return;
    }
    if (watchIdRef.current !== null) navigator.geolocation.clearWatch(watchIdRef.current);
    watchIdRef.current = navigator.geolocation.watchPosition(
      (position) => {
        setTracking(true);
        setGpsStatus("GPS active");
        enqueuePosition(position);
      },
      (geoError) => {
        setTracking(false);
        setGpsStatus("GPS unavailable");
        setError(geoError.message || "Location permission denied");
      },
      {
        enableHighAccuracy: true,
        maximumAge: 2000,
        timeout: 15000,
      },
    );
    setGpsStatus("Requesting GPS permission");
  }

  async function stopTrackingNow() {
    if (watchIdRef.current !== null) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    if (meta) {
      try {
        await flushQueue();
        await stopRiderTracking(meta.orderId, riderToken);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to stop tracking");
      }
    }
    setTracking(false);
    setGpsStatus("Tracking stopped");
  }

  return (
    <main className={s.page}>
      <section className={s.card}>
        <h1 className={s.title}>Rider tracking</h1>
        <p className={s.meta}>
          Order {meta?.orderNumber ?? "—"} · Customer {meta?.customerName ?? "—"}
        </p>
        {error ? <div className={s.error}>{error}</div> : null}
        <div className={s.statusBox}>
          <div><span>Status</span><strong>{gpsStatus}</strong></div>
          <div><span>Network</span><strong>{navigator.onLine ? "Online" : "Offline"}</strong></div>
          <div><span>Last sent</span><strong>{lastSentAt ?? "Not sent yet"}</strong></div>
        </div>
        <div className={s.actions}>
          <button className={s.primary} onClick={startTracking}>
            {tracking ? "Restart GPS" : "Start tracking"}
          </button>
          <button className={s.secondary} onClick={stopTrackingNow}>
            Stop tracking
          </button>
        </div>
        <p className={s.help}>
          Keep this page open during delivery. If you go offline, updates are queued and sent when the network returns.
        </p>
      </section>
    </main>
  );
}
