import { fetchOnboardingStatus } from "./onboardingApi";

const STORAGE_KEY = "ops_onboarding_complete";

/** Cached onboarding flag — avoids a Render round-trip on every sidebar click. */
export function readCachedOnboardingComplete(): boolean | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (raw === "1") return true;
  if (raw === "0") return false;
  return null;
}

export function writeCachedOnboardingComplete(complete: boolean): void {
  sessionStorage.setItem(STORAGE_KEY, complete ? "1" : "0");
}

export function clearCachedOnboardingComplete(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}

/** Fetch once per session; subsequent calls return the cached value immediately. */
let inflight: Promise<boolean> | null = null;

export function resolveOnboardingComplete(): Promise<boolean> {
  const cached = readCachedOnboardingComplete();
  if (cached !== null) return Promise.resolve(cached);
  if (!inflight) {
    inflight = fetchOnboardingStatus()
      .then((s) => {
        writeCachedOnboardingComplete(s.complete);
        return s.complete;
      })
      .catch(() => {
        writeCachedOnboardingComplete(true);
        return true;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}