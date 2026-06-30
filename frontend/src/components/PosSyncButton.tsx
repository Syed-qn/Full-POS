import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import {
  getPosConfig,
  getPosSyncStatus,
  savePosConfig,
  startPosSync,
  type PosSyncStatus,
} from "../lib/posApi";

/**
 * Connect a POS account and run the full background sync from the Menu page.
 *
 * The full pull (hundreds of dishes plus image generation and a Meta push) runs in the
 * background on the server, so this button just kicks it off and then polls
 * GET /pos/sync/status until it reports done or error. While it runs the manager can
 * keep working; we call onSynced once it finishes so the menu list refreshes.
 */
export function PosSyncButton({ onSynced }: { onSynced?: () => void }) {
  const [account, setAccount] = useState("");
  const [location, setLocation] = useState("");
  const [configured, setConfigured] = useState(false);
  const [showConnect, setShowConnect] = useState(false);
  const [saving, setSaving] = useState(false);
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

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [cfg, st] = await Promise.all([getPosConfig(), getPosSyncStatus()]);
        if (!alive) return;
        setAccount(cfg.pos_account || "");
        setLocation(cfg.pos_location || "");
        setConfigured(Boolean(cfg.pos_account && cfg.pos_location));
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
            toast(
              `POS sync done. ${st.created ?? 0} new, ${st.updated ?? 0} updated.`,
            );
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

  async function saveAndConnect() {
    if (!account.trim() || !location.trim()) {
      toast("Enter the POS account and location", "error");
      return;
    }
    setSaving(true);
    try {
      await savePosConfig({
        pos_enabled: true,
        pos_account: account.trim(),
        pos_location: location.trim(),
      });
      setConfigured(true);
      setShowConnect(false);
      toast("POS connected");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save POS settings", "error");
    } finally {
      setSaving(false);
    }
  }

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

  if (!configured && !showConnect) {
    return (
      <Button variant="ghost" onClick={() => setShowConnect(true)}>
        Connect POS
      </Button>
    );
  }

  if (showConnect) {
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          placeholder="POS account"
          style={{ width: 120 }}
        />
        <input
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="Location code"
          style={{ width: 120 }}
        />
        <Button onClick={saveAndConnect} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button variant="ghost" onClick={() => setShowConnect(false)}>
          Cancel
        </Button>
      </div>
    );
  }

  const running = busy || status?.state === "running";
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <Button onClick={runSync} disabled={running}>
        {running ? "Syncing…" : "Sync from POS"}
      </Button>
      <Button variant="ghost" onClick={() => setShowConnect(true)} disabled={running}>
        POS settings
      </Button>
      {status?.state === "done" && (
        <span style={{ fontSize: 13, opacity: 0.75 }}>
          {status.created ?? 0} new, {status.updated ?? 0} updated, {status.images ?? 0} images
        </span>
      )}
      {status?.state === "error" && (
        <span style={{ fontSize: 13, color: "var(--danger, #c0392b)" }}>
          Sync failed
        </span>
      )}
    </div>
  );
}
