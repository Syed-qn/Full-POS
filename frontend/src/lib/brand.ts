import { useEffect, useState } from "react";
import { apiClient } from "./apiClient";

/**
 * The restaurant's own name, from /api/v1/me. This is the TENANT name (e.g.
 * "Full POS Demo") — not the product name in `desktopEnv.appProductName()`,
 * which is always "Full POS". Every chrome surface shows this one, so the
 * manager sidebar and the waiter/cashier top bar cannot disagree.
 *
 * Cached for the tab's lifetime: it never changes during a session, and
 * refetching per mount made the name flash while the request was in flight.
 */
let cached: string | null = null;
let inflight: Promise<void> | null = null;
const listeners = new Set<(name: string) => void>();

function load(): void {
  if (cached || inflight) return;
  inflight = apiClient
    .get<{ name: string }>("/api/v1/me")
    .then((r) => {
      const name = r?.name ?? "";
      if (name) {
        cached = name;
        for (const fn of listeners) fn(name);
      }
    })
    // Keep whatever is on screen; never blank a good name on a failed call.
    .catch(() => undefined)
    .finally(() => {
      inflight = null;
    });
}

/** Restaurant name, or "" until it is known. */
export function useRestaurantName(): string {
  const [name, setName] = useState(() => cached ?? "");

  useEffect(() => {
    if (cached) {
      setName(cached);
      return;
    }
    listeners.add(setName);
    load();
    return () => {
      listeners.delete(setName);
    };
  }, []);

  return name;
}

/** Test seam — drops the cached name so a fresh fetch happens. */
export function resetRestaurantNameCache(): void {
  cached = null;
  inflight = null;
}
