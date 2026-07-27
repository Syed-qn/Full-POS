import { apiClient } from "./apiClient";

/**
 * The branch this terminal is paired with.
 *
 * Staff numbers restart at 1 in every restaurant, so the number alone cannot
 * identify a person — the store code is what tells the server which branch's
 * "manager 1" is signing in. It is entered once per device and remembered, so
 * staff keep typing just their number and PIN.
 */
const STORE_KEY = "pos.store_code";

export function getPairedStore(): string {
  try {
    return localStorage.getItem(STORE_KEY) ?? "";
  } catch {
    // Private-mode / storage-disabled terminals still work — the operator just
    // re-enters the code each shift rather than being locked out.
    return "";
  }
}

export function setPairedStore(code: string): void {
  const clean = normalizeStoreCode(code);
  try {
    if (clean) localStorage.setItem(STORE_KEY, clean);
    else localStorage.removeItem(STORE_KEY);
  } catch {
    /* nothing to persist to; the in-memory value for this sign-in still applies */
  }
}

/** Codes are shown and printed in upper case; keypads and autocorrect are not. */
export function normalizeStoreCode(code: string): string {
  return (code ?? "").trim().toUpperCase();
}

export type StoreIdentity = {
  store_code: string;
  location_uuid: string;
  name: string;
};

/** Owner-only: the pairing keys for the signed-in restaurant, to set up a till. */
export async function getStoreIdentity(): Promise<StoreIdentity> {
  return apiClient.get<StoreIdentity>("/api/v1/staff/store-identity");
}
