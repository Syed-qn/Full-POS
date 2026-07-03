import { useEffect, useRef, useState } from "react";
import { PollingTransport } from "./transport/pollingTransport";

export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number | null = 4000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (intervalMs === null) return;
    const transport = new PollingTransport<T>(() => fetcherRef.current(), intervalMs);
    const unsub = transport.subscribe(
      (v) => {
        setData(v);
        setError(null);
      },
      (e) => setError(e),
    );
    return unsub;
  }, [intervalMs]);

  return { data, error };
}
