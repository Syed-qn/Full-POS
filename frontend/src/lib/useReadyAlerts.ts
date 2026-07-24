import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "../components/Toaster";
import { fetchReadyAlerts, type ReadyAlert } from "./kdsApi";
import { getStaffSession } from "./navAccess";

const POLL_MS = 5000;
const MAX_KEEP = 30;

/** Per-staff watermark so a reload doesn't replay history or blast old readies. */
function watermarkKey(staffId: number): string {
  return `ready_alerts_since_${staffId}`;
}

/** One short "ding" via WebAudio — no asset, no autoplay policy issues once the
 *  cashier/waiter has interacted with the terminal (they always have). */
function playChime(): void {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(1174, ctx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.45);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.46);
    osc.onended = () => ctx.close().catch(() => {});
  } catch {
    // Audio is a nicety — never let it break the poll.
  }
}

/** "Table 20 · Token 3 · Ready" (dine-in) or "Token 3 · Take Away · Ready". */
export function alertLine(a: ReadyAlert): string {
  const parts: string[] = [];
  if (a.table_label) parts.push(`Table ${a.table_label}`);
  if (a.daily_token != null) parts.push(`Token ${a.daily_token}`);
  if (!a.table_label) {
    const t =
      a.order_type === "takeaway"
        ? "Take Away"
        : a.order_type === "delivery"
          ? "Home Delivery"
          : a.order_type === "online"
            ? "Online"
            : null;
    if (t) parts.push(t);
  }
  parts.push("Ready");
  return parts.join(" · ");
}

/**
 * Polls the "your order is ready" feed for the CURRENT staff member and surfaces
 * it as a bell: an unread badge, an accumulated list, plus a toast + chime the
 * moment a new order plates. Routing is server-side (creator-only), so a waiter
 * only hears their tables and a cashier only their till orders.
 *
 * Disabled for non-staff sessions (manager/owner use the manager alert center).
 */
export function useReadyAlerts() {
  const staff = getStaffSession();
  const staffId = staff?.staff_id ?? null;
  const enabled = staffId != null;

  const [alerts, setAlerts] = useState<ReadyAlert[]>([]);
  const [unread, setUnread] = useState(0);
  // Watermark lives in a ref (used inside the interval) mirrored to localStorage.
  const sinceRef = useRef<string>("");

  useEffect(() => {
    if (!enabled || staffId == null) return;
    const key = watermarkKey(staffId);
    let stored = "";
    try {
      stored = localStorage.getItem(key) ?? "";
    } catch {
      stored = "";
    }
    // First ever load → start "now" so we don't dump the whole shift's history.
    sinceRef.current = stored || new Date().toISOString();
    try {
      localStorage.setItem(key, sinceRef.current);
    } catch {
      /* private mode — poll still works, just no persistence */
    }

    let cancelled = false;
    async function tick() {
      try {
        const rows = await fetchReadyAlerts(sinceRef.current);
        if (cancelled || rows.length === 0) return;
        // Advance the watermark past the newest ready we've now seen.
        const newest = rows.reduce(
          (m, r) => (r.ready_at > m ? r.ready_at : m),
          sinceRef.current,
        );
        sinceRef.current = newest;
        try {
          localStorage.setItem(key, newest);
        } catch {
          /* ignore */
        }
        setAlerts((prev) => [...rows, ...prev].slice(0, MAX_KEEP));
        setUnread((n) => n + rows.length);
        playChime();
        // One toast summarises the batch; the bell dropdown lists them all.
        toast(
          rows.length === 1
            ? `🔔 ${alertLine(rows[0])}`
            : `🔔 ${rows.length} orders ready`,
        );
      } catch {
        // Network blip — the next tick retries with the same watermark.
      }
    }

    const id = window.setInterval(tick, POLL_MS);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [enabled, staffId]);

  const markAllSeen = useCallback(() => setUnread(0), []);

  return { enabled, alerts, unread, markAllSeen };
}
