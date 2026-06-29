import { useEffect, useRef } from "react";

function isDocumentHidden(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "hidden";
}

/**
 * Run `fn` every `intervalMs` in the background, on top of whatever initial /
 * on-change fetching a screen already does. The callback is held in a ref so it
 * always sees the latest props/state (filters, activeId, …) without the timer
 * resubscribing — so polling never clobbers selection, filters, or scroll.
 *
 * Skips ticks while a request is in-flight or the tab is hidden; refreshes once
 * when the tab becomes visible again.
 */
export function usePollingRefresh(fn: () => void | Promise<void>, intervalMs = 12_000): void {
  const ref = useRef(fn);
  const inFlight = useRef(false);
  ref.current = fn;

  useEffect(() => {
    const run = () => {
      if (isDocumentHidden() || inFlight.current) return;
      inFlight.current = true;
      Promise.resolve(ref.current()).finally(() => {
        inFlight.current = false;
      });
    };

    const id = setInterval(run, intervalMs);
    const onVis = () => {
      if (!isDocumentHidden()) run();
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVis);
    }
    return () => {
      clearInterval(id);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVis);
      }
    };
  }, [intervalMs]);
}