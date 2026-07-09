import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { BranchOpsScreen } from "./BranchOpsScreen";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function fakeOrgToken(orgId: number): string {
  return `header.${btoa(JSON.stringify({ sub: String(orgId), aud: "org" }))}.sig`;
}

describe("BranchOpsScreen", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_org_token", fakeOrgToken(7));
    vi.stubGlobal(
      "fetch",
      vi.fn((url: unknown, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith("/api/v1/organizations/branches") && init?.method === "POST") {
          return Promise.resolve(json({ id: 13, name: "Jumeirah" }, 201));
        }
        if (path.endsWith("/api/v1/organizations/branches")) {
          return Promise.resolve(json([{ id: 11, name: "Downtown" }, { id: 12, name: "Marina" }]));
        }
        if (path.includes("/rollup-sales")) {
          return Promise.resolve(
            json({
              total_gross_sales_aed: "4200.00",
              branches: [
                { restaurant_id: 11, name: "Downtown", gross_sales_aed: "2800.00" },
                { restaurant_id: 12, name: "Marina", gross_sales_aed: "1400.00" },
              ],
            }),
          );
        }
        if (path.includes("/inventory-summary")) {
          return Promise.resolve(
            json({
              total_inventory_value_aed: "900.00",
              total_low_stock_count: 3,
              branches: [
                { restaurant_id: 11, restaurant_name: "Downtown", inventory_value_aed: "600.00", low_stock_count: 1 },
                { restaurant_id: 12, restaurant_name: "Marina", inventory_value_aed: "300.00", low_stock_count: 2 },
              ],
            }),
          );
        }
        if (path.includes("/branch-comparison")) {
          return Promise.resolve(
            json([
              { restaurant_id: 11, restaurant_name: "Downtown", order_count: 32, revenue_aed: "2800.00" },
              { restaurant_id: 12, restaurant_name: "Marina", order_count: 18, revenue_aed: "1400.00" },
            ]),
          );
        }
        if (path.includes("/stock-transfers")) {
          return Promise.resolve(
            json({ id: 44, status: "draft", from_restaurant_id: 11, to_restaurant_id: 12 }, 201),
          );
        }
        return Promise.resolve(json({}));
      }),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("shows branch sales, inventory summary, and comparison rows", async () => {
    renderWithProviders(<BranchOpsScreen />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Branches" })).toBeInTheDocument());
    expect(await screen.findByText("AED 4,200.00")).toBeInTheDocument();
    expect(screen.getByText("AED 900.00")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Downtown" })).toBeInTheDocument();
    expect(screen.getByText("32 orders")).toBeInTheDocument();
  });

  it("creates branches and stock transfers with the org token", async () => {
    renderWithProviders(<BranchOpsScreen />);
    await screen.findByRole("cell", { name: "Downtown" });

    fireEvent.change(screen.getByLabelText("Branch name"), { target: { value: "Jumeirah" } });
    fireEvent.change(screen.getByLabelText("Latitude"), { target: { value: "25.20" } });
    fireEvent.change(screen.getByLabelText("Longitude"), { target: { value: "55.25" } });
    fireEvent.click(screen.getByRole("button", { name: /add branch/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/organizations/branches"),
        expect.objectContaining({ method: "POST" }),
      ),
    );

    fireEvent.change(screen.getByLabelText("From branch"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("To branch"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("Ingredient"), { target: { value: "Rice" } });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "5.000" } });
    fireEvent.click(screen.getByRole("button", { name: /create transfer/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/organizations/7/stock-transfers"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
