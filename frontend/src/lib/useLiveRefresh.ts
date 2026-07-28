import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { subscribeLive, type LiveTopic } from "./liveEvents";

/**
 * Run `onChange` whenever the server says one of `topics` changed.
 *
 * The callback is held in a ref so a screen can pass an inline arrow without
 * resubscribing on every render — resubscribing tears the shared stream down
 * and back up, which is exactly the churn this is meant to remove.
 */
export function useLiveRefresh(topics: LiveTopic[], onChange: () => void): void {
  const cb = useRef(onChange);
  cb.current = onChange;
  // Same reasoning for the topic list: a fresh array literal each render would
  // otherwise look like a changed dependency.
  const key = topics.join(",");

  useEffect(() => {
    const wanted = new Set(key.split(",") as LiveTopic[]);
    return subscribeLive((event) => {
      if (wanted.has(event.topic)) cb.current();
    });
  }, [key]);
}

/**
 * React Query flavour: invalidate cached queries when the server pushes.
 *
 * Invalidating rather than refetching directly means a screen that is mounted
 * but not visible does not fetch until it is looked at again, so a background
 * tab full of tills costs nothing.
 */
export function useLiveInvalidate(
  topics: LiveTopic[],
  queryKeys: readonly unknown[][],
): void {
  const qc = useQueryClient();
  const keysRef = useRef(queryKeys);
  keysRef.current = queryKeys;

  useLiveRefresh(topics, () => {
    for (const key of keysRef.current) {
      void qc.invalidateQueries({ queryKey: key });
    }
  });
}
