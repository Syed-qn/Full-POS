import { useEffect, useState } from "react";
import { getPosBridge, isDesktopShell } from "./desktopEnv";

export type OfflineStatus = {
  /** True when browser reports online and desktop bridge (if present) does not report offline. */
  online: boolean;
  offline: boolean;
  /** Desktop local write-queue size; 0 when not desktop or unavailable. */
  pendingCount: number;
  hasPending: boolean;
  isDesktop: boolean;
};

/** Read browser online flag safely (SSR / test environments). */
export function readNavigatorOnline(): boolean {
  if (typeof navigator === "undefined") return true;
  return navigator.onLine !== false;
}

/**
 * Live offline / pending-sync status for shell chrome and core screens.
 * - Browser: `navigator.onLine` + online/offline window events
 * - Desktop (Electron posBridge): poll `networkStatus` + `listPendingOps`
 */
export function useOfflineStatus(pollMs = 5000): OfflineStatus {
  const [browserOnline, setBrowserOnline] = useState(readNavigatorOnline);
  const [desktopOnline, setDesktopOnline] = useState<boolean | null>(null);
  const [pendingCount, setPendingCount] = useState(0);
  const isDesktop = isDesktopShell();

  useEffect(() => {
    const onOnline = () => setBrowserOnline(true);
    const onOffline = () => setBrowserOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    setBrowserOnline(readNavigatorOnline());
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  useEffect(() => {
    if (!isDesktop) {
      setDesktopOnline(null);
      setPendingCount(0);
      return;
    }
    const bridge = getPosBridge();
    let cancelled = false;

    async function tick() {
      try {
        if (bridge?.networkStatus) {
          const st = await bridge.networkStatus();
          if (!cancelled) setDesktopOnline(st.online);
        }
        if (bridge?.listPendingOps) {
          const ops = await bridge.listPendingOps();
          if (!cancelled) setPendingCount(ops.length);
        }
      } catch {
        if (!cancelled) setDesktopOnline(false);
      }
    }

    void tick();
    const id = window.setInterval(() => void tick(), pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [isDesktop, pollMs]);

  // Offline if browser is offline OR desktop explicitly reports offline.
  const online = browserOnline && desktopOnline !== false;

  return {
    online,
    offline: !online,
    pendingCount,
    hasPending: pendingCount > 0,
    isDesktop,
  };
}
