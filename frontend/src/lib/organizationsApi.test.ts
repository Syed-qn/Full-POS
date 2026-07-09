import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ORG_TOKEN_KEY,
  completeStockTransfer,
  createBranch,
  createStockTransfer,
  getBranchComparison,
  getOrgToken,
  getOrganizationInventorySummary,
  getRollupSales,
  listBranches,
  loginOrganization,
  setOrgToken,
  signupOrganization,
} from "./organizationsApi";

function respondJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function bodyOf(init: RequestInit | undefined): unknown {
  return JSON.parse(String(init?.body));
}

describe("organizationsApi", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    fetchMock = vi.fn().mockImplementation(() => respondJson({}));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.restoreAllMocks());

  it("stores organization login token separately from the restaurant token", async () => {
    localStorage.setItem("ops_token", "restaurant-token");
    fetchMock.mockResolvedValueOnce(respondJson({ access_token: "org-jwt", token_type: "bearer" }));

    await loginOrganization("owner@example.com", "secret");

    expect(localStorage.getItem(ORG_TOKEN_KEY)).toBe("org-jwt");
    expect(localStorage.getItem("ops_token")).toBe("restaurant-token");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/organizations/login");
    expect(bodyOf(fetchMock.mock.calls[0][1])).toEqual({
      owner_email: "owner@example.com",
      password: "secret",
    });
  });

  it("stores organization signup token", async () => {
    fetchMock.mockResolvedValueOnce(respondJson({ access_token: "new-org-jwt", token_type: "bearer" }, 201));

    await signupOrganization("Group One", "owner@example.com", "secret");

    expect(getOrgToken()).toBe("new-org-jwt");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/organizations/signup");
    expect(bodyOf(fetchMock.mock.calls[0][1])).toEqual({
      name: "Group One",
      owner_email: "owner@example.com",
      password: "secret",
    });
  });

  it("uses ops_org_token for authenticated branch and reporting requests", async () => {
    setOrgToken("org-token");

    await listBranches();
    await createBranch({ name: "Downtown", lat: 25.2048, lng: 55.2708 });
    await getRollupSales("2026-07-09");
    await getBranchComparison(4, "2026-07-01", "2026-07-09");
    await getOrganizationInventorySummary();

    for (const call of fetchMock.mock.calls) {
      expect(call[1]?.headers).toMatchObject({ Authorization: "Bearer org-token" });
    }
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/organizations/branches",
      "/api/v1/organizations/branches",
      "/api/v1/organizations/rollup-sales?target_date=2026-07-09",
      "/api/v1/organizations/4/branch-comparison?start_date=2026-07-01&end_date=2026-07-09",
      "/api/v1/organizations/inventory-summary",
    ]);
    expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
    expect(bodyOf(fetchMock.mock.calls[1][1])).toEqual({ name: "Downtown", lat: 25.2048, lng: 55.2708 });
  });

  it("creates and completes stock transfers with the organization token", async () => {
    setOrgToken("org-token");

    await createStockTransfer(4, {
      from_restaurant_id: 10,
      to_restaurant_id: 11,
      lines: [{ ingredient_name: "Rice", unit: "kg", quantity: "5.000" }],
    });
    await completeStockTransfer(99);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/organizations/4/stock-transfers");
    expect(bodyOf(fetchMock.mock.calls[0][1])).toMatchObject({
      from_restaurant_id: 10,
      to_restaurant_id: 11,
    });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/stock-transfers/99/complete");
    expect(fetchMock.mock.calls[1][1]?.headers).toMatchObject({ Authorization: "Bearer org-token" });
  });
});
