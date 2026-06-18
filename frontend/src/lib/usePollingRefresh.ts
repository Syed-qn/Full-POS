import { useEffect, useRef } from "react";

/**
 * Run `fn` every `intervalMs` in the background, on top of whatever initial /
 * on-change fetching a screen already does. The callback is held in a ref so it
 * always sees the latest props/state (filters, activeId, …) without the timer
 * resubscribing — so polling never clobbers selection, filters, or scroll.
 *
 * Use this for screens that own their data + filters and want live updates.
 * (For screens whose data IS the poll, use `usePoll`.)
 */
export function usePollingRefresh(fn: () => void, intervalMs = 4000): void {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const id = setInterval(() => ref.current(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
