import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  canAccess,
  clearStaffSession,
  filterNavItems,
  getSessionRole,
  isTrainingMode,
  matchRouteKey,
  normalizeRole,
  ROUTE_ROLE_MAP,
  setStaffSession,
  type StaffRole,
} from "./navAccess";

/** Build an unsigned JWT-like string with the given payload (UI decode only). */
function fakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "none", typ: "JWT" }))
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  const body = btoa(JSON.stringify(payload))
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${body}.sig`;
}

describe("normalizeRole", () => {
  it("accepts known roles case-insensitively", () => {
    expect(normalizeRole("Manager")).toBe("manager");
    expect(normalizeRole("KITCHEN")).toBe("kitchen");
    expect(normalizeRole("cashier")).toBe("cashier");
  });

  it("returns null for empty or unknown (full access)", () => {
    expect(normalizeRole(null)).toBeNull();
    expect(normalizeRole(undefined)).toBeNull();
    expect(normalizeRole("")).toBeNull();
    expect(normalizeRole("franchise_admin")).toBeNull();
  });
});

describe("matchRouteKey", () => {
  it("maps nested order and customer paths", () => {
    expect(matchRouteKey("/")).toBe("/");
    expect(matchRouteKey("/orders/12")).toBe("/orders");
    expect(matchRouteKey("/orders/12/pay")).toBe("/payments");
    expect(matchRouteKey("/customers/3")).toBe("/customers");
    expect(matchRouteKey("/kds/grill")).toBe("/kds");
    expect(matchRouteKey("/menu")).toBe("/menu");
  });
});

describe("canAccess — default / manager / owner", () => {
  it("allows everything when role is null/undefined (owner JWT, backward compat)", () => {
    for (const route of Object.keys(ROUTE_ROLE_MAP)) {
      expect(canAccess(route, null)).toBe(true);
      expect(canAccess(route, undefined)).toBe(true);
    }
    expect(canAccess("/settings", null)).toBe(true);
    expect(canAccess("/staff", undefined)).toBe(true);
  });

  it("allows everything for owner and manager", () => {
    for (const route of Object.keys(ROUTE_ROLE_MAP)) {
      expect(canAccess(route, "owner")).toBe(true);
      expect(canAccess(route, "manager")).toBe(true);
    }
  });

  it("allows unknown role strings (do not lock out)", () => {
    expect(canAccess("/settings", "superuser")).toBe(true);
    expect(canAccess("/staff", "legacy_admin")).toBe(true);
  });

  it("allows unmapped routes for restricted roles (no invented locks)", () => {
    expect(canAccess("/some-future-module", "kitchen")).toBe(true);
  });
});

describe("canAccess — role matrix", () => {
  const cases: Array<{
    role: StaffRole;
    allowed: string[];
    denied: string[];
  }> = [
    {
      role: "kitchen",
      allowed: ["/", "/orders", "/orders/9", "/kds", "/kds/1"],
      denied: [
        "/menu",
        "/settings",
        "/staff",
        "/new-order",
        "/payments",
        "/floor",
        "/marketing",
        "/customers",
      ],
    },
    {
      role: "cashier",
      allowed: ["/", "/floor", "/orders", "/new-order", "/payments", "/orders/1/pay", "/customers"],
      denied: ["/menu", "/kds", "/staff", "/settings", "/marketing", "/riders"],
    },
    {
      role: "rider",
      allowed: ["/", "/orders", "/riders"],
      denied: ["/menu", "/new-order", "/kds", "/payments", "/settings", "/staff", "/floor"],
    },
    {
      role: "staff",
      allowed: [
        "/",
        "/floor",
        "/orders",
        "/new-order",
        "/kds",
        "/payments",
        "/riders",
        "/conversations",
        "/customers",
        "/tickets",
        "/reliability",
      ],
      denied: ["/menu", "/inventory", "/staff", "/settings", "/marketing", "/reports", "/compliance"],
    },
  ];

  for (const { role, allowed, denied } of cases) {
    it(`${role}: allows daily modules and denies admin`, () => {
      for (const r of allowed) expect(canAccess(r, role), `${role} should access ${r}`).toBe(true);
      for (const r of denied) expect(canAccess(r, role), `${role} should deny ${r}`).toBe(false);
    });
  }
});

describe("filterNavItems", () => {
  const items = [
    { to: "/", label: "Live Ops" },
    { to: "/menu", label: "Menu" },
    { to: "/kds", label: "Kitchen" },
    { to: "/settings", label: "Settings" },
  ];

  it("returns all items when role is null", () => {
    expect(filterNavItems(items, null)).toHaveLength(4);
  });

  it("filters for kitchen", () => {
    const out = filterNavItems(items, "kitchen");
    expect(out.map((i) => i.to)).toEqual(["/", "/kds"]);
  });
});

describe("getSessionRole + training from token/session", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("returns null for manager-audience token without role (owner)", () => {
    const token = fakeJwt({ sub: "1", aud: "manager" });
    localStorage.setItem("ops_token", token);
    expect(getSessionRole()).toBeNull();
    expect(canAccess("/settings", getSessionRole())).toBe(true);
  });

  it("reads role from staff JWT claim", () => {
    const token = fakeJwt({ sub: "42", aud: "staff", role: "kitchen" });
    localStorage.setItem("ops_token", token);
    expect(getSessionRole()).toBe("kitchen");
    expect(canAccess("/menu", getSessionRole())).toBe(false);
    expect(canAccess("/kds", getSessionRole())).toBe(true);
  });

  it("falls back to sessionStorage when JWT has no role", () => {
    setStaffSession({ role: "cashier", training_mode: true, name: "Ali", staff_id: 7 });
    expect(getSessionRole()).toBe("cashier");
    expect(isTrainingMode()).toBe(true);
  });

  it("clears training when session cleared", () => {
    setStaffSession({ role: "staff", training_mode: true });
    expect(isTrainingMode()).toBe(true);
    clearStaffSession();
    expect(isTrainingMode()).toBe(false);
    expect(getSessionRole()).toBeNull();
  });
});
