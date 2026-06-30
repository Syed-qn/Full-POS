import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { getPosSyncStatus, startPosSync, type PosSyncStatus } from "../lib/posApi";

/**
 * Run the full background POS sync from the Menu page.
 *
 * The POS account/location are fixed server-side (the Cratis HNC feed), so there's no
 * connect/settings form — this is just a one-click "Sync from POS". The full pull
 * (hundreds of dishes plus image generation and a Meta push) runs in the background on
 * the server; this button kicks it off and polls GET /pos/sync/status until it reports
 * done or error. We call onSynced once it finishes so the menu list refreshes.
 */
export function PosSyncButton({ onSynced }: { onSynced?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<PosSyncStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onSyncedRef = useRef(onSynced);
  onSyncedRef.current = onSynced;

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    setBusy(true);
    pollRef.current = setInterval(async () => {
      try {
        const st = await getPosSyncStatus();
        setStatus(st);
        if (st.state === "done" || st.state === "error") {
          stopPolling();
          setBusy(false);
          if (st.state === "done") {
            toast("POS sync done");
            onSyncedRef.current?.();
          } else {
            toast(st.error || "POS sync failed", "error");
          }
        }
      } catch {
        /* transient; keep polling */
      }
    }, 4000);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stopPolling]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const st = await getPosSyncStatus();
        if (!alive) return;
        setStatus(st.state === "idle" ? null : st);
        if (st.state === "running") startPolling();
      } catch {
        /* POS is optional; stay quiet if it is not reachable */
      }
    })();
    return () => {
      alive = false;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function runSync() {
    setBusy(true);
    try {
      const res = await startPosSync();
      toast(res.detail || "Sync started");
      setStatus({ state: "running" });
      startPolling();
    } catch (e) {
      setBusy(false);
      toast(e instanceof Error ? e.message : "Could not start POS sync", "error");
    }
  }

  const running = busy || status?.state === "running";
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <Button onClick={runSync} disabled={running}>
        {running ? "Syncing…" : "Sync from POS"}
      </Button>
      {status?.state === "error" && (
        <span style={{ fontSize: 13, color: "var(--danger, #c0392b)" }}>
          Sync failed
        </span>
      )}
    </div>
  );
}
