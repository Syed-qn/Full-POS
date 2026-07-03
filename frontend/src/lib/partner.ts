// Partner attribution for onboarding. The POS embeds the app link with
// ?partner=<slug>. A new restaurant then goes signup -> login -> onboarding ->
// connect, and single page navigations drop the query string. So we capture the
// slug on first load into localStorage and read it back at connect time.
const KEY = "onboard_partner";

/** Capture ?partner=<slug> from the current URL into localStorage (run once at
 *  app start, before any navigation). Lowercased to match the APP_PARTNERS key. */
export function capturePartnerFromUrl(): void {
  try {
    const p = new URLSearchParams(window.location.search).get("partner");
    if (p && p.trim()) localStorage.setItem(KEY, p.trim().toLowerCase());
  } catch {
    /* storage unavailable — ignore */
  }
}

/** The partner slug for this onboarding: the live URL param if present, else the
 *  value captured at app start. Null = standalone (no POS). */
export function getOnboardPartner(): string | null {
  try {
    const url = new URLSearchParams(window.location.search).get("partner");
    if (url && url.trim()) return url.trim().toLowerCase();
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

/** Clear the stored partner once onboarding is done (or for a fresh standalone signup). */
export function clearOnboardPartner(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
