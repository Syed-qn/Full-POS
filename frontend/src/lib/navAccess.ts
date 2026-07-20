/**
 * Role / license navigation gates + role landings (R0–R1).
 *
 * Backend model:
 * - Restaurant owner login → JWT aud="manager", no `role` claim → full access.
 * - Staff PIN login → JWT aud="staff", `role` claim from staff_members.role.
 *
 * Default / backward compatible: unknown or missing role → show all routes
 * (never lock out owners/managers who lack a role claim).
 *
 * Placement SSOT: docs/ROLE_SCREEN_FEATURE_PLACEMENT.md
 */

export type StaffRole =
  | "owner"
  | "manager"
  | "staff"
  | "waiter"
  | "kitchen"
  | "cashier"
  | "rider";

export const KNOWN_ROLES: readonly StaffRole[] = [
  "owner",
  "manager",
  "staff",
  "waiter",
  "kitchen",
  "cashier",
  "rider",
] as const;

/** Roles that always see every authenticated module. */
export const FULL_ACCESS_ROLES: readonly StaffRole[] = ["owner", "manager"] as const;

const SESSION_KEY = "ops_staff_session";

export type StaffSessionMeta = {
  role: string;
  training_mode?: boolean;
  name?: string;
  staff_id?: number;
};

export type RoleChrome = {
  /** Hide left nav (kitchen fullscreen). */
  showSidebar: boolean;
  /** Role mode string for data attributes / CSS. */
  mode: "owner" | "waiter" | "cashier" | "kitchen" | "staff" | "rider" | "full";
};

export function setStaffSession(meta: StaffSessionMeta | null): void {
  if (meta == null) {
    sessionStorage.removeItem(SESSION_KEY);
    return;
  }
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(meta));
}

export function getStaffSession(): StaffSessionMeta | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StaffSessionMeta;
    if (!parsed || typeof parsed.role !== "string") return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearStaffSession(): void {
  setStaffSession(null);
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  return atob(padded);
}

/** Decode JWT payload without verifying signature (UI gating only). */
export function decodeTokenClaims(
  token: string | null | undefined,
): Record<string, unknown> | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length < 2 || !parts[1]) return null;
  try {
    return JSON.parse(decodeBase64Url(parts[1])) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Normalize a raw role string. Unknown values return null so callers treat
 * them as full access (do not lock out).
 */
export function normalizeRole(raw: string | null | undefined): StaffRole | null {
  if (raw == null) return null;
  const r = String(raw).trim().toLowerCase();
  if (!r) return null;
  if ((KNOWN_ROLES as readonly string[]).includes(r)) return r as StaffRole;
  return null;
}

/**
 * Resolve the active session role for nav gating.
 * - Prefer JWT `role` claim (staff tokens).
 * - Owner/manager tokens (aud=manager, no role) → null (full access).
 * - Fall back to sessionStorage meta from staff PIN login.
 */
export function getSessionRole(token?: string | null): StaffRole | null {
  const tok =
    token !== undefined
      ? token
      : typeof localStorage !== "undefined"
        ? localStorage.getItem("ops_token")
        : null;
  const claims = decodeTokenClaims(tok);
  if (claims) {
    if (typeof claims.role === "string" && claims.role.trim()) {
      return normalizeRole(claims.role);
    }
    // Manager/owner restaurant token — no role claim.
    if (claims.aud === "manager") return null;
  }
  const session = getStaffSession();
  if (session?.role) return normalizeRole(session.role);
  return null;
}

/** Training mode chrome when staff PIN session stored the flag. */
export function isTrainingMode(): boolean {
  const session = getStaffSession();
  return Boolean(session?.training_mode);
}

/**
 * Post-login home path for a role.
 * null / owner / manager → Live Ops.
 */
export function getRoleHomePath(role: StaffRole | string | null | undefined): string {
  const r =
    role == null || role === ""
      ? null
      : typeof role === "string"
        ? normalizeRole(role)
        : role;
  if (r == null) return "/";
  switch (r) {
    case "staff":
      return "/floor";
    case "waiter":
    case "cashier":
      return "/new-order";
    case "kitchen":
      return "/kds";
    case "rider":
      return "/riders";
    case "owner":
    case "manager":
    default:
      return "/";
  }
}

/** Shell chrome flags per role. */
export function getRoleChrome(role: StaffRole | string | null | undefined): RoleChrome {
  const r =
    role == null || role === ""
      ? null
      : typeof role === "string"
        ? normalizeRole(role)
        : role;
  if (r === "kitchen") return { showSidebar: false, mode: "kitchen" };
  if (r === "waiter") return { showSidebar: true, mode: "waiter" };
  if (r === "cashier") return { showSidebar: true, mode: "cashier" };
  if (r === "staff") return { showSidebar: true, mode: "staff" };
  if (r === "rider") return { showSidebar: true, mode: "rider" };
  return { showSidebar: true, mode: r === "owner" || r === "manager" ? "owner" : "full" };
}

/** True when role should not see payment / tender UI (waiter floor staff). */
export function isWaiterRole(role?: StaffRole | string | null): boolean {
  const r = role === undefined ? getSessionRole() : typeof role === "string" ? normalizeRole(role) : role;
  return r === "waiter" || r === "staff";
}

/** True when role is kitchen cook board. */
export function isKitchenRole(role?: StaffRole | string | null): boolean {
  const r = role === undefined ? getSessionRole() : typeof role === "string" ? normalizeRole(role) : role;
  return r === "kitchen";
}

/** True when role is cashier money terminal. */
export function isCashierRole(role?: StaffRole | string | null): boolean {
  const r = role === undefined ? getSessionRole() : typeof role === "string" ? normalizeRole(role) : role;
  return r === "cashier";
}

/**
 * Route → roles allowed (owner/manager always pass via canAccess).
 * Paths are prefixes; longest match wins. Nested routes inherit.
 */
export const ROUTE_ROLE_MAP: Record<string, readonly StaffRole[]> = {
  "/": ["owner", "manager", "staff", "waiter", "kitchen", "cashier", "rider"],
  "/floor": ["owner", "manager", "staff", "waiter", "cashier"],
  "/orders": ["owner", "manager", "staff", "waiter", "kitchen", "cashier", "rider"],
  "/new-order": ["owner", "manager", "staff", "waiter", "cashier"],
  "/kds": ["owner", "manager", "staff", "kitchen"],
  "/payments": ["owner", "manager", "cashier"],
  "/riders": ["owner", "manager", "staff", "rider"],
  "/conversations": ["owner", "manager", "staff"],
  "/menu": ["owner", "manager"],
  "/inventory": ["owner", "manager"],
  "/customers": ["owner", "manager", "staff", "cashier"],
  "/staff": ["owner", "manager"],
  "/marketing": ["owner", "manager"],
  "/reports": ["owner", "manager"],
  "/ai": ["owner", "manager"],
  "/branches": ["owner", "manager"],
  "/channels": ["owner", "manager"],
  "/reliability": ["owner", "manager"],
  "/settings": ["owner", "manager"],
  "/tickets": ["owner", "manager", "staff"],
  "/coupons": ["owner", "manager"],
  "/compliance": ["owner", "manager"],
  "/analytics": ["owner", "manager"],
  "/predictions": ["owner", "manager"],
};

/** Normalize a pathname for map lookup (strip query/hash; collapse nested). */
export function matchRouteKey(pathname: string): string {
  const path = (pathname.split("?")[0] ?? "/").split("#")[0] || "/";
  if (path === "/" || path === "") return "/";

  // Explicit nested mappings
  if (/^\/orders\/[^/]+\/pay\/?$/.test(path)) return "/payments";
  if (/^\/orders(\/|$)/.test(path)) return "/orders";
  if (/^\/customers(\/|$)/.test(path)) return "/customers";
  if (/^\/kds(\/|$)/.test(path)) return "/kds";

  const keys = Object.keys(ROUTE_ROLE_MAP)
    .filter((k) => k !== "/")
    .sort((a, b) => b.length - a.length);
  for (const key of keys) {
    if (path === key || path.startsWith(`${key}/`)) return key;
  }
  return path;
}

/**
 * Whether `role` may open `route`.
 * - null / undefined / unknown → true (backward compatible)
 * - owner / manager → true
 * - unmapped routes → true (do not invent locks)
 */
export function canAccess(
  route: string,
  role: StaffRole | string | null | undefined,
): boolean {
  const normalized =
    role == null || role === ""
      ? null
      : typeof role === "string"
        ? normalizeRole(role)
        : role;

  // Unknown raw string that failed normalize → treat as full access
  if (role != null && role !== "" && normalized == null) return true;

  if (normalized == null) return true;
  if ((FULL_ACCESS_ROLES as readonly string[]).includes(normalized)) return true;

  const key = matchRouteKey(route);
  const allowed = ROUTE_ROLE_MAP[key];
  if (!allowed) return true;
  return (allowed as readonly string[]).includes(normalized);
}

export function filterNavItems<T extends { to: string }>(
  items: readonly T[],
  role: StaffRole | string | null | undefined,
): T[] {
  return items.filter((it) => canAccess(it.to, role));
}
