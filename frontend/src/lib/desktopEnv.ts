/** Detect Full POS desktop shell (Electron .exe / .dmg) vs browser / cloud UI. */

export type PosBridge = {
  request?: (method: string, path: string, body?: unknown) => Promise<unknown>;
  listConflicts?: () => Promise<Array<{ id: string; entity: string; path: string }>>;
  resolveConflict?: (id: string, action: "retry" | "discard") => Promise<unknown>;
  networkStatus?: () => Promise<{ online: boolean; last_error: string | null }>;
  listPendingOps?: () => Promise<Array<{ id: string; status: string; path: string }>>;
  offlinePrint?: (kind: "kot" | "receipt", payload: string) => Promise<unknown>;
  setAuthToken?: (token: string | null) => void;
  getAppInfo?: () => Promise<{ version: string; platform: string; arch: string }>;
};

export function getPosBridge(): PosBridge | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as unknown as { posBridge?: PosBridge }).posBridge;
}

/** True when running inside Electron preload (installed Full POS app). */
export function isDesktopShell(): boolean {
  return Boolean(getPosBridge());
}

/** file:// or hash routing preferred for packaged installs. */
export function prefersHashRouter(): boolean {
  if (typeof window === "undefined") return false;
  if (isDesktopShell()) return true;
  return window.location.protocol === "file:";
}

export function appProductName(): string {
  return "Full POS";
}
