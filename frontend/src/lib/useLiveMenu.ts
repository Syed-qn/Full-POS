import { useCallback, useEffect, useRef, useState } from "react";
import { fetchActiveMenu } from "./menuApi";
import type { DishOut } from "./types";

/**
 * The active menu, kept CURRENT on a terminal that stays open all shift.
 *
 * The order screens used to fetch the menu once on mount. A wall-mounted waiter
 * or cashier terminal is opened at the start of service and never reloaded, so
 * "86 the salmon" only reached the floor when somebody happened to refresh the
 * page. The sale was still refused server-side (POST /orders/pos rejects an
 * unavailable dish), but the waiter discovered it at the till with the guest
 * waiting — the worst possible moment.
 *
 * So: poll while the tab is visible, and refetch the instant it regains focus.
 * One small payload a minute, and an 86'd dish disappears from every terminal
 * within POLL_MS instead of "whenever someone reloads".
 */
/* 15s. Not order-board cadence (Live Ops polls at 4s because an SLA clock moves
   second by second) — a menu edit is a human action a few times per service, so
   4 requests/minute/terminal is the right trade against Railway egress. Fast
   enough that a waiter effectively never taps a dish the kitchen just 86'd. */
const POLL_MS = 15_000;

/** Survives remounts so a repeat table tap paints instantly instead of flashing
 *  "Loading menu…". Opt-in (`cache: true`): it belongs to the waiter/cashier
 *  terminal, where the floor and the order pad are separate routes and staff
 *  bounce between them all service. A dashboard route wants an honest skeleton
 *  on first paint instead. */
let menuCache: DishOut[] | null = null;

export interface LiveMenu {
  /** Available dishes only — the unavailable ones are never orderable. */
  dishes: DishOut[];
  /** Is there an active menu at all? null until the first fetch settles.
   *  false means the restaurant has none (404) — a different thing from an
   *  active menu whose dishes are all unavailable, which is `true` + empty. */
  exists: boolean | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useLiveMenu({ cache = false }: { cache?: boolean } = {}): LiveMenu {
  const seed = cache ? menuCache : null;
  const [dishes, setDishes] = useState<DishOut[]>(seed ?? []);
  const [exists, setExists] = useState<boolean | null>(seed === null ? null : true);
  const [loading, setLoading] = useState(seed === null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  // Read inside load() without making it depend on `dishes` (which would tear
  // down and rebuild the poll interval on every successful fetch).
  const dishesRef = useRef(dishes);
  dishesRef.current = dishes;

  const load = useCallback(async () => {
    try {
      // fetchActiveMenu maps a 404 to null: the restaurant has no active menu.
      const menu = await fetchActiveMenu();
      const avail = (menu?.dishes ?? []).filter((d) => d.is_available);
      if (cache) menuCache = avail;
      if (alive.current) {
        setDishes(avail);
        setExists(menu !== null);
        setError(null);
      }
    } catch (e) {
      // A failed poll must never blank a working terminal mid-service: keep the
      // last good menu and only surface an error if we have nothing at all.
      if (alive.current && dishesRef.current.length === 0) {
        setError(e instanceof Error ? e.message : "Menu unavailable");
      }
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [cache]);

  useEffect(() => {
    alive.current = true;
    void load();

    const timer = setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState === "visible") {
        void load();
      }
    }, POLL_MS);

    // Coming back to the tab is the moment staleness is most likely AND most
    // visible, so refetch immediately rather than waiting out the interval.
    const onVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);

    return () => {
      alive.current = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [load]);

  return { dishes, exists, loading, error, refresh: load };
}
