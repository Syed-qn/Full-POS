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
  /** Owning business. Null for a standalone restaurant with no organization. */
  account_uuid: string | null;
  location_uuid: string;
  /** Short typeable form of location_uuid, for a keypad with no link. */
  store_code: string;
  name: string;
};

/** Owner-only: the pairing keys for the signed-in restaurant, to set up a till. */
export async function getStoreIdentity(): Promise<StoreIdentity> {
  return apiClient.get<StoreIdentity>("/api/v1/staff/store-identity");
}

export type StorePairing = { name: string; lat: number; lng: number };

/** Metres between two points. Branches in one city sit a few hundred metres
 *  apart, so plain lat/lng subtraction is too coarse to compare them. */
export function metresBetween(
  aLat: number, aLng: number, bLat: number, bLng: number,
): number {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(bLat - aLat);
  const dLng = toRad(bLng - aLng);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** How far the coordinates in a pairing link may sit from the branch's own
 *  before we treat the link as pointing somewhere else. Two branches in the
 *  same district are further apart than this; GPS-grade rounding is not. */
export const PAIRING_TOLERANCE_M = 300;

/**
 * The link that pairs a terminal with one branch.
 *
 * Carries account + location as opaque ids — which business, which branch —
 * plus the branch's coordinates so the till can check the link still points at
 * the place it is standing in. Nothing here is human-readable on purpose: a
 * short code in a link is a code someone can retype at another branch.
 */
export function pairingLink(origin: string, p: {
  account_uuid?: string | null; location_uuid: string; lat: number; lng: number;
}): string {
  const q = new URLSearchParams();
  if (p.account_uuid) q.set("account", p.account_uuid);
  q.set("location", p.location_uuid);
  q.set("lat", String(p.lat));
  q.set("lng", String(p.lng));
  return `${origin}/login?${q.toString()}`;
}

/**
 * Which branch a pairing key points at, resolved before anyone signs in.
 *
 * Two branches in the same city are told apart by their key, not their
 * coordinates — this exists so the person pairing a terminal SEES the branch
 * name and can catch a wrong link before staff start taking orders on it.
 */
export async function lookupStore(
  location: string,
  account?: string | null,
): Promise<StorePairing | null> {
  const key = normalizeStoreCode(location);
  if (!key) return null;
  const q = new URLSearchParams({ location: key });
  if (account) q.set("account", account);
  try {
    const p = await apiClient.get<StorePairing>(
      `/api/v1/staff/store-pairing?${q.toString()}`,
      { skipAuthRedirect: true },
    );
    // Only render a banner we can fully trust: a partial response would either
    // throw on the coordinate formatting or, worse, name the wrong branch with
    // blank coordinates — the one thing this banner exists to prevent.
    if (!p || typeof p.name !== "string" || !p.name) return null;
    if (typeof p.lat !== "number" || typeof p.lng !== "number") return null;
    return p;
  } catch {
    // Unknown key or offline — the pad still works; sign-in is the real check.
    return null;
  }
}
